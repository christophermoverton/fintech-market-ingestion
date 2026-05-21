import json

import pandas as pd
import pytest

from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    read_dividend_research_mart,
    write_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (
    DIVIDEND_DATASET_FILENAME,
    read_dividend_corporate_actions,
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
        "process_date": "2024-02-15",
        "declaration_date": "2024-02-01",
        "ex_date": "2024-02-10",
        "record_date": "2024-02-12",
        "payable_date": "2024-02-28",
        "cash_amount": None,
        "stock_amount": "0.05",
        "currency": None,
    }
    payload.update(overrides)
    return payload


def normalized(payload):
    return normalize_corporate_action_payload(payload)


def test_research_mart_preserves_quarterly_cash_dividend_amounts(tmp_path):
    snapshot_root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    quarterly_payloads = [
        cash_dividend_payload(
            id="aapl-dividend-2024-02",
            ex_date="2024-02-09",
            record_date="2024-02-12",
            payable_date="2024-02-15",
            process_date="2024-02-15",
            rate=0.24,
            cash_amount=None,
        ),
        cash_dividend_payload(
            id="aapl-dividend-2024-05",
            ex_date="2024-05-10",
            record_date="2024-05-13",
            payable_date="2024-05-16",
            process_date="2024-05-16",
            rate=0.25,
            cash_amount=None,
        ),
        cash_dividend_payload(
            id="aapl-dividend-2024-08",
            ex_date="2024-08-12",
            record_date="2024-08-12",
            payable_date="2024-08-15",
            process_date="2024-08-15",
            rate=0.25,
            cash_amount=None,
        ),
        cash_dividend_payload(
            id="aapl-dividend-2024-11",
            ex_date="2024-11-08",
            record_date="2024-11-11",
            payable_date="2024-11-14",
            process_date="2024-11-14",
            rate=0.25,
            cash_amount=None,
        ),
    ]
    records = [normalized(payload) for payload in quarterly_payloads]

    assert len(records) == 4
    assert [record.cash_amount for record in records] == [0.24, 0.25, 0.25, 0.25]

    snapshot_result = write_dividend_corporate_actions(
        records,
        root_dir=snapshot_root,
        ingest_start_date="2024-01-01",
        ingest_end_date="2024-12-31",
        source="alpaca",
        action_types=["cash_dividend"],
    )
    snapshot_loaded = read_dividend_corporate_actions(snapshot_root)
    mart_result = write_dividend_research_mart_from_snapshot(snapshot_root, research_root)
    research_loaded = read_dividend_research_mart(research_root)

    assert snapshot_result.written_record_count == 4
    assert mart_result.written_record_count == 4
    assert len(snapshot_loaded) == 4
    assert len(research_loaded) == 4
    assert research_loaded["symbol"].tolist() == ["AAPL", "AAPL", "AAPL", "AAPL"]
    assert research_loaded["year"].tolist() == [2024, 2024, 2024, 2024]
    assert research_loaded["cash_amount"].notna().all()
    assert research_loaded["cash_amount"].tolist() == [0.24, 0.25, 0.25, 0.25]


def test_research_mart_writes_partitioned_output_by_symbol_and_year(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_RESEARCH_MART_ROOT
    records = [
        normalized(cash_dividend_payload(symbol="aapl", ex_date="2025-01-10", id="ca-1")),
        normalized(stock_dividend_payload(symbol="MSFT", ex_date="2024-02-10", id="ca-2")),
    ]

    result = write_dividend_research_mart(records, root_dir=root)
    loaded = read_dividend_research_mart(root)

    assert (root / "symbol=AAPL" / "year=2025").exists()
    assert (root / "symbol=MSFT" / "year=2024").exists()
    assert result.written_record_count == 2
    assert loaded["symbol"].tolist() == ["AAPL", "MSFT"]
    assert loaded["year"].tolist() == [2025, 2024]


def test_research_mart_preserves_canonical_dividend_fields_and_partition_columns(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    source = normalized(cash_dividend_payload(id="ca-preserve-1", extra_field={"a": 1}))

    write_dividend_research_mart([source], root_dir=root)
    loaded = read_dividend_research_mart(root)

    assert loaded.loc[0, "corporate_action_id"] == "ca-preserve-1"
    assert loaded.loc[0, "symbol"] == "AAPL"
    assert loaded.loc[0, "corporate_action_type"] == "cash_dividend"
    assert loaded.loc[0, "year"] == 2025
    assert json.loads(loaded.loc[0, "raw"]) == source.raw


def test_research_mart_repeated_writes_are_deterministic(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    records = [
        normalized(cash_dividend_payload(id="ca-1", ex_date="2025-01-10")),
        normalized(stock_dividend_payload(id="ca-2", ex_date="2024-02-10")),
    ]

    first = write_dividend_research_mart(records, root_dir=root)
    first_loaded = read_dividend_research_mart(root)
    second = write_dividend_research_mart(records, root_dir=root)
    second_loaded = read_dividend_research_mart(root)

    assert first.metadata == second.metadata
    assert first_loaded.equals(second_loaded)


def test_research_mart_metadata_distinguishes_research_role_and_anchor(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    result = write_dividend_research_mart(
        [normalized(cash_dividend_payload(id="ca-meta-1"))],
        root_dir=root,
        source_snapshot_path=tmp_path
        / "data"
        / "curated"
        / "corporate_actions"
        / "dividends"
        / "dividends.parquet",
        start="2025-01-01",
        end="2025-01-31",
    )

    metadata = result.metadata
    assert metadata["dataset"] == "corporate_actions_dividends_research_mart"
    assert metadata["dataset_role"] == "research_mart"
    assert metadata["source_dataset_role"] == "deterministic_snapshot"
    assert metadata["partition_columns"] == ["symbol", "year"]
    assert metadata["event_anchor"] == "ex_date"
    assert metadata["event_anchor_source"] == "normalized.ex_date"
    assert metadata["source_snapshot_path"].endswith("dividends.parquet")


def test_snapshot_to_research_mart_helper_preserves_snapshot_artifact(tmp_path):
    snapshot_root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    records = [
        normalized(cash_dividend_payload(id="ca-snap-1", ex_date="2025-01-10")),
        normalized(stock_dividend_payload(id="ca-snap-2", ex_date="2024-02-10")),
    ]

    write_dividend_corporate_actions(
        records,
        root_dir=snapshot_root,
        ingest_start_date="2024-01-01",
        ingest_end_date="2025-12-31",
        source="alpaca",
        action_types=["cash_dividend", "stock_dividend"],
    )
    before_snapshot_bytes = (snapshot_root / DIVIDEND_DATASET_FILENAME).read_bytes()

    result = write_dividend_research_mart_from_snapshot(snapshot_root, research_root)
    after_snapshot_bytes = (snapshot_root / DIVIDEND_DATASET_FILENAME).read_bytes()
    snapshot_loaded = read_dividend_corporate_actions(snapshot_root)
    research_loaded = read_dividend_research_mart(research_root)

    assert before_snapshot_bytes == after_snapshot_bytes
    assert len(snapshot_loaded) == 2
    assert len(research_loaded) == 2
    assert result.metadata["source_snapshot_path"].endswith("dividends.parquet")


def test_research_mart_rejects_missing_partition_fields(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    invalid = normalized(cash_dividend_payload(id="ca-bad-1", ex_date=None))

    with pytest.raises(ValueError, match="missing required partition fields"):
        write_dividend_research_mart([invalid], root_dir=root)


def test_research_mart_rejects_blank_symbol_partition_fields(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    invalid = pd.DataFrame(
        [
            {
                "corporate_action_id": "ca-bad-2",
                "symbol": "   ",
                "corporate_action_type": "cash_dividend",
                "source": "alpaca",
                "process_date": "2025-01-15",
                "declaration_date": "2025-01-02",
                "ex_date": "2025-01-10",
                "record_date": "2025-01-13",
                "payable_date": "2025-01-31",
                "cash_amount": 0.25,
                "stock_amount": None,
                "currency": "USD",
                "source_payload_hash": "hash-ca-bad-2",
                "raw": "{}",
            }
        ]
    )

    with pytest.raises(ValueError, match="missing required partition fields"):
        write_dividend_research_mart(invalid, root_dir=root)


def test_research_mart_loader_requires_existing_dataset_root(tmp_path):
    missing_root = tmp_path / "does-not-exist"

    with pytest.raises(FileNotFoundError, match="root does not exist"):
        read_dividend_research_mart(missing_root)
