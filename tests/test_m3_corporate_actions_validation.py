import json
from pathlib import Path

import pytest

from examples import corporate_actions_dividend_ingestion_example as example
from src.cli.ingest_corporate_actions import (
    build_parser,
    ingest_dividend_corporate_actions,
)
from src.ingestion.alpaca_corporate_actions_client import CorporateActionRecord
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
    read_dividend_corporate_actions,
    read_dividend_corporate_actions_metadata,
)


class FakeCorporateActionsClient:
    def __init__(self, records):
        self.records = list(records)
        self.calls = []

    def fetch_corporate_actions(self, symbols, start, end, types, limit, sort):
        self.calls.append(
            {
                "symbols": list(symbols),
                "start": start,
                "end": end,
                "types": list(types),
                "limit": limit,
                "sort": sort,
            }
        )
        return self.records


def cash_dividend_payload(**overrides):
    payload = {
        "id": "m3-cash-1",
        "symbol": "AAPL",
        "type": "cash_dividend",
        "process_date": "2024-02-15",
        "declaration_date": "2024-02-01",
        "ex_date": "2024-02-09",
        "record_date": "2024-02-12",
        "payable_date": "2024-02-29",
        "cash_amount": "0.24",
        "stock_amount": None,
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def stock_dividend_payload(**overrides):
    payload = {
        "id": "m3-stock-1",
        "symbol": "MSFT",
        "type": "stock_dividend",
        "process_date": "2024-03-15",
        "declaration_date": "2024-03-01",
        "ex_date": "2024-03-08",
        "record_date": "2024-03-11",
        "payable_date": "2024-03-29",
        "cash_amount": None,
        "stock_amount": "0.05",
        "currency": None,
    }
    payload.update(overrides)
    return payload


def ca_record(payload):
    return CorporateActionRecord.from_payload(payload)


def test_m3_end_to_end_mocked_dividend_ingestion_is_deterministic(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT
    records = [
        ca_record(stock_dividend_payload()),
        ca_record(cash_dividend_payload()),
        ca_record(cash_dividend_payload()),
    ]

    first = ingest_dividend_corporate_actions(
        symbols=["AAPL", "MSFT"],
        start="2024-01-01",
        end="2024-12-31",
        types=["cash_dividend", "stock_dividend"],
        output_root=root,
        client=FakeCorporateActionsClient(records),
    )
    first_df = read_dividend_corporate_actions(root)
    first_metadata = read_dividend_corporate_actions_metadata(root)

    second = ingest_dividend_corporate_actions(
        symbols=["AAPL", "MSFT"],
        start="2024-01-01",
        end="2024-12-31",
        types=["cash_dividend", "stock_dividend"],
        output_root=root,
        client=FakeCorporateActionsClient(records),
    )
    second_df = read_dividend_corporate_actions(root)
    second_metadata = read_dividend_corporate_actions_metadata(root)

    assert first.fetched_record_count == 3
    assert first.normalized_record_count == 3
    assert first.written_record_count == 2
    assert first.duplicate_record_count == 1
    assert second.written_record_count == first.written_record_count
    assert second.duplicate_record_count == first.duplicate_record_count

    assert (root / DIVIDEND_DATASET_FILENAME).exists()
    assert (root / DIVIDEND_METADATA_FILENAME).exists()
    assert first_df["corporate_action_type"].tolist() == ["cash_dividend", "stock_dividend"]
    assert first_df["corporate_action_id"].tolist() == ["m3-cash-1", "m3-stock-1"]
    assert second_df["corporate_action_id"].tolist() == first_df["corporate_action_id"].tolist()
    assert second_df["source_payload_hash"].tolist() == first_df["source_payload_hash"].tolist()
    assert "open" not in first_df.columns
    assert "high" not in first_df.columns
    assert "low" not in first_df.columns
    assert "close" not in first_df.columns
    assert "volume" not in first_df.columns

    stable_metadata_keys = [
        "dataset",
        "path",
        "format",
        "data_file",
        "source",
        "sources",
        "ingest_start_date",
        "ingest_end_date",
        "action_types",
        "record_count",
        "written_record_count",
        "duplicate_record_count",
        "duplicate_handling",
        "event_key",
    ]
    assert {key: first_metadata[key] for key in stable_metadata_keys} == {
        key: second_metadata[key] for key in stable_metadata_keys
    }


def test_m3_empty_result_persists_empty_schema_and_zero_metadata(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT

    result = ingest_dividend_corporate_actions(
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-12-31",
        output_root=root,
        client=FakeCorporateActionsClient([]),
    )
    df = read_dividend_corporate_actions(root)
    metadata = read_dividend_corporate_actions_metadata(root)

    assert result.fetched_record_count == 0
    assert result.written_record_count == 0
    assert df.empty
    assert "corporate_action_id" in df.columns
    assert metadata["record_count"] == 0
    assert metadata["written_record_count"] == 0
    assert metadata["duplicate_record_count"] == 0


def test_m3_unsupported_type_fails_before_persistence(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT
    client = FakeCorporateActionsClient([ca_record(cash_dividend_payload())])

    with pytest.raises(ValueError, match="Unsupported dividend corporate action type"):
        ingest_dividend_corporate_actions(
            symbols=["AAPL"],
            start="2024-01-01",
            end="2024-12-31",
            types=["forward_split"],
            output_root=root,
            client=client,
        )

    assert client.calls == []
    assert not root.exists()


def test_m3_path_separation_from_ohlcv_market_data(tmp_path):
    root = tmp_path / DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT

    ingest_dividend_corporate_actions(
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-12-31",
        output_root=root,
        client=FakeCorporateActionsClient([ca_record(cash_dividend_payload())]),
    )

    assert "corporate_actions" in root.parts
    assert "dividends" in root.parts
    assert not (tmp_path / "data" / "curated" / "bars_daily").exists()
    assert not (tmp_path / "data" / "curated" / "bars_1m").exists()
    assert not (tmp_path / "data" / "curated" / "trades").exists()
    assert not (tmp_path / "data" / "curated" / "quotes").exists()


def test_m3_docs_storage_defaults_and_cli_flags_are_aligned():
    docs = Path("docs/corporate_actions_dividends.md").read_text(encoding="utf-8")
    parser = build_parser()
    parser_flags = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }

    assert str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT).replace("\\", "/") in docs
    assert (
        f"{DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT.as_posix()}/{DIVIDEND_DATASET_FILENAME}" in docs
    )
    assert (
        f"{DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT.as_posix()}/{DIVIDEND_METADATA_FILENAME}" in docs
    )
    for flag in ["--symbols", "--start", "--end", "--types", "--output-root", "--sort", "--limit"]:
        assert flag in parser_flags
        assert flag in docs


def test_m3_ci_safe_example_runs_without_credentials(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    output_root = tmp_path / "artifacts" / "examples" / "corporate_actions_dividends"

    exit_code = example.main(["--output-root", str(output_root)])
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["fetched_record_count"] == 2
    assert summary["written_record_count"] == 2
    assert (output_root / DIVIDEND_DATASET_FILENAME).exists()
    assert (output_root / DIVIDEND_METADATA_FILENAME).exists()
