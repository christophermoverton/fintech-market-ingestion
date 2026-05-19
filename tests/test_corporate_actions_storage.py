import json

import pandas as pd

from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
    read_dividend_corporate_actions,
    read_dividend_corporate_actions_metadata,
    write_dividend_corporate_actions,
)


def cash_dividend_payload(**overrides):
    payload = {
        "id": "ca-cash-1",
        "symbol": "AAPL",
        "type": "cash_dividend",
        "process_date": "2025-01-15",
        "declaration_date": "2025-01-02",
        "ex_date": "2025-01-10",
        "record_date": "2025-01-13",
        "payable_date": "2025-01-31",
        "cash_amount": "0.25",
        "stock_amount": None,
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def stock_dividend_payload(**overrides):
    payload = {
        "id": "ca-stock-1",
        "symbol": "MSFT",
        "type": "stock_dividend",
        "process_date": "2025-02-15",
        "declaration_date": "2025-02-01",
        "ex_date": "2025-02-10",
        "record_date": "2025-02-12",
        "payable_date": "2025-02-28",
        "cash_amount": None,
        "stock_amount": "0.05",
        "currency": None,
    }
    payload.update(overrides)
    return payload


def normalized(payload):
    return normalize_corporate_action_payload(payload)


def test_write_read_round_trip(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    record = normalized(cash_dividend_payload())

    result = write_dividend_corporate_actions(
        [record],
        root_dir=root,
        ingest_start_date="2025-01-01",
        ingest_end_date="2025-01-31",
        source="alpaca",
        action_types=["cash_dividend"],
    )
    loaded = read_dividend_corporate_actions(root)

    assert result.data_path == root / DIVIDEND_DATASET_FILENAME
    assert result.metadata_path == root / DIVIDEND_METADATA_FILENAME
    assert len(loaded) == 1
    row = loaded.iloc[0].to_dict()
    assert row["corporate_action_id"] == record.corporate_action_id
    assert row["symbol"] == record.symbol
    assert row["corporate_action_type"] == record.corporate_action_type
    assert row["source_payload_hash"] == record.source_payload_hash
    assert json.loads(row["raw"]) == record.raw


def test_empty_record_list_writes_empty_dataset_and_metadata(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"

    result = write_dividend_corporate_actions(
        [],
        root_dir=root,
        ingest_start_date="2025-01-01",
        ingest_end_date="2025-01-31",
        source="alpaca",
        action_types=["cash_dividend", "stock_dividend"],
    )
    loaded = read_dividend_corporate_actions(root)
    metadata = read_dividend_corporate_actions_metadata(root)

    assert result.input_record_count == 0
    assert result.written_record_count == 0
    assert loaded.empty
    assert list(loaded.columns)
    assert metadata["record_count"] == 0
    assert metadata["written_record_count"] == 0


def test_output_ordering_is_deterministic(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    records = [
        normalized(stock_dividend_payload(symbol="MSFT", ex_date="2025-01-03", id="ca-3")),
        normalized(cash_dividend_payload(symbol="AAPL", ex_date="2025-01-10", id="ca-2")),
        normalized(cash_dividend_payload(symbol="AAPL", ex_date="2025-01-05", id="ca-1")),
    ]

    write_dividend_corporate_actions(records, root_dir=root)
    loaded = read_dividend_corporate_actions(root)

    assert loaded["corporate_action_id"].tolist() == ["ca-1", "ca-2", "ca-3"]


def test_repeated_writes_with_identical_records_are_idempotent(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    records = [normalized(cash_dividend_payload())]

    first = write_dividend_corporate_actions(records, root_dir=root)
    second = write_dividend_corporate_actions(records, root_dir=root)
    loaded = read_dividend_corporate_actions(root)

    assert first.written_record_count == 1
    assert second.written_record_count == 1
    assert len(loaded) == 1


def test_duplicate_input_records_are_deduplicated_by_event_key(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    record = normalized(cash_dividend_payload())

    result = write_dividend_corporate_actions([record, record], root_dir=root)
    loaded = read_dividend_corporate_actions(root)

    assert result.input_record_count == 2
    assert result.written_record_count == 1
    assert result.duplicate_record_count == 1
    assert len(loaded) == 1


def test_corporate_actions_path_is_separate_from_market_data_paths(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT

    write_dividend_corporate_actions([normalized(cash_dividend_payload())], root_dir=root)

    assert "corporate_actions" in root.parts
    assert "dividends" in root.parts
    assert "bars_daily" not in root.parts
    assert "bars_1m" not in root.parts
    assert not (tmp_path / "data" / "curated" / "bars_daily").exists()
    assert not (tmp_path / "data" / "curated" / "bars_1m").exists()


def test_metadata_includes_source_window_types_and_counts(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    records = [
        normalized(cash_dividend_payload()),
        normalized(stock_dividend_payload()),
    ]

    write_dividend_corporate_actions(
        records,
        root_dir=root,
        ingest_start_date="2025-01-01",
        ingest_end_date="2025-02-28",
        source="alpaca",
        action_types=["cash_dividend", "stock_dividend"],
    )
    metadata = read_dividend_corporate_actions_metadata(root)

    assert metadata["dataset"] == "corporate_actions_dividends"
    assert metadata["format"] == "parquet"
    assert metadata["source"] == "alpaca"
    assert metadata["sources"] == ["alpaca"]
    assert metadata["ingest_start_date"] == "2025-01-01"
    assert metadata["ingest_end_date"] == "2025-02-28"
    assert metadata["action_types"] == ["cash_dividend", "stock_dividend"]
    assert metadata["record_count"] == 2
    assert metadata["written_record_count"] == 2
    assert metadata["duplicate_record_count"] == 0
    assert metadata["event_key"] == [
        "corporate_action_id",
        "symbol",
        "corporate_action_type",
        "ex_date",
        "process_date",
    ]


def test_raw_payload_and_hash_survive_persistence(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    record = normalized(cash_dividend_payload(extra_vendor_field={"nested": True}))

    write_dividend_corporate_actions([record], root_dir=root)
    loaded = read_dividend_corporate_actions(root)

    assert loaded.loc[0, "source_payload_hash"] == record.source_payload_hash
    assert json.loads(loaded.loc[0, "raw"]) == record.raw


def test_dictionary_inputs_are_supported(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    record = normalized(cash_dividend_payload()).as_dict()

    write_dividend_corporate_actions([record], root_dir=root)
    loaded = read_dividend_corporate_actions(root)

    assert len(loaded) == 1
    assert loaded.loc[0, "corporate_action_id"] == "ca-cash-1"


def test_missing_dataset_read_returns_empty_schema(tmp_path):
    loaded = read_dividend_corporate_actions(tmp_path / "missing")

    assert isinstance(loaded, pd.DataFrame)
    assert loaded.empty
    assert "corporate_action_id" in loaded.columns
