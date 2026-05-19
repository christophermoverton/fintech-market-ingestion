import json

import pytest

from src.cli import ingest_corporate_actions as cli
from src.ingestion.alpaca_corporate_actions_client import CorporateActionRecord
from src.ingestion.corporate_actions_storage import (
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
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if sort not in {"asc", "desc"}:
            raise ValueError("sort must be either 'asc' or 'desc'")
        return self.records


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


def ca_record(payload):
    return CorporateActionRecord.from_payload(payload)


def test_cli_argument_parsing_for_required_arguments(tmp_path):
    parser = cli.build_parser()

    args = parser.parse_args(
        [
            "--symbols",
            "AAPL",
            "MSFT",
            "--start",
            "2025-01-01",
            "--end",
            "2025-12-31",
            "--types",
            "cash_dividend",
            "stock_dividend",
            "--output-root",
            str(tmp_path),
            "--sort",
            "desc",
            "--limit",
            "250",
        ]
    )

    assert args.symbols == ["AAPL", "MSFT"]
    assert args.start == "2025-01-01"
    assert args.end == "2025-12-31"
    assert args.types == ["cash_dividend", "stock_dividend"]
    assert args.output_root == str(tmp_path)
    assert args.sort == "desc"
    assert args.limit == 250


def test_successful_mocked_ingestion_writes_expected_files(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    client = FakeCorporateActionsClient(
        [
            ca_record(cash_dividend_payload()),
            ca_record(stock_dividend_payload()),
        ]
    )

    result = cli.ingest_dividend_corporate_actions(
        symbols=["AAPL", "MSFT"],
        start="2025-01-01",
        end="2025-12-31",
        types=["cash_dividend", "stock_dividend"],
        output_root=root,
        sort="desc",
        limit=500,
        client=client,
    )

    assert client.calls == [
        {
            "symbols": ["AAPL", "MSFT"],
            "start": "2025-01-01",
            "end": "2025-12-31",
            "types": ["cash_dividend", "stock_dividend"],
            "limit": 500,
            "sort": "desc",
        }
    ]
    assert (root / DIVIDEND_DATASET_FILENAME).exists()
    assert (root / DIVIDEND_METADATA_FILENAME).exists()
    assert result.fetched_record_count == 2
    assert result.normalized_record_count == 2
    assert result.written_record_count == 2
    assert result.duplicate_record_count == 0


def test_empty_api_result_writes_empty_dataset_and_metadata(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    client = FakeCorporateActionsClient([])

    result = cli.ingest_dividend_corporate_actions(
        symbols=["AAPL"],
        start="2025-01-01",
        end="2025-01-31",
        output_root=root,
        client=client,
    )
    loaded = read_dividend_corporate_actions(root)
    metadata = read_dividend_corporate_actions_metadata(root)

    assert result.fetched_record_count == 0
    assert result.normalized_record_count == 0
    assert result.written_record_count == 0
    assert loaded.empty
    assert metadata["record_count"] == 0
    assert metadata["written_record_count"] == 0


def test_invalid_symbols_fail_before_client_call(tmp_path):
    client = FakeCorporateActionsClient([])

    with pytest.raises(ValueError, match="At least one symbol is required"):
        cli.ingest_dividend_corporate_actions(
            symbols=["   "],
            start="2025-01-01",
            end="2025-01-31",
            output_root=tmp_path,
            client=client,
        )

    assert client.calls == []


def test_unsupported_action_type_fails_clearly_before_client_call(tmp_path):
    client = FakeCorporateActionsClient([])

    with pytest.raises(ValueError, match="Unsupported dividend corporate action type"):
        cli.ingest_dividend_corporate_actions(
            symbols=["AAPL"],
            start="2025-01-01",
            end="2025-01-31",
            types=["forward_split"],
            output_root=tmp_path,
            client=client,
        )

    assert client.calls == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit must be between"),
        ({"sort": "newest"}, "sort must be either"),
    ],
)
def test_invalid_sort_or_limit_propagates_clear_client_validation(tmp_path, kwargs, message):
    client = FakeCorporateActionsClient([])

    with pytest.raises(ValueError, match=message):
        cli.ingest_dividend_corporate_actions(
            symbols=["AAPL"],
            start="2025-01-01",
            end="2025-01-31",
            output_root=tmp_path,
            client=client,
            **kwargs,
        )

    assert len(client.calls) == 1


def test_summary_output_includes_counts_and_paths(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    client = FakeCorporateActionsClient([ca_record(cash_dividend_payload())])

    result = cli.ingest_dividend_corporate_actions(
        symbols=["AAPL"],
        start="2025-01-01",
        end="2025-01-31",
        output_root=root,
        client=client,
    )
    summary = result.as_dict()

    assert summary["requested_symbols"] == ["AAPL"]
    assert summary["start"] == "2025-01-01"
    assert summary["end"] == "2025-01-31"
    assert summary["fetched_record_count"] == 1
    assert summary["normalized_record_count"] == 1
    assert summary["written_record_count"] == 1
    assert summary["duplicate_record_count"] == 0
    assert summary["data_path"] == str(root / DIVIDEND_DATASET_FILENAME)
    assert summary["metadata_path"] == str(root / DIVIDEND_METADATA_FILENAME)


def test_pipeline_api_can_be_called_directly_without_cli(tmp_path):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    client = FakeCorporateActionsClient([ca_record(cash_dividend_payload())])

    result = cli.ingest_dividend_corporate_actions(
        symbols=[" AAPL "],
        start="2025-01-01",
        end="2025-01-31",
        output_root=root,
        client=client,
    )

    assert result.requested_symbols == ["AAPL"]
    assert result.storage.data_path.exists()
    assert read_dividend_corporate_actions(root).loc[0, "corporate_action_id"] == "ca-cash-1"


def test_main_prints_json_summary_without_live_credentials(monkeypatch, tmp_path, capsys):
    root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    client = FakeCorporateActionsClient([ca_record(cash_dividend_payload())])
    monkeypatch.setattr(cli.AlpacaCorporateActionsClient, "from_env", lambda: client)

    exit_code = cli.main(
        [
            "--symbols",
            "AAPL",
            "--start",
            "2025-01-01",
            "--end",
            "2025-01-31",
            "--output-root",
            str(root),
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["requested_symbols"] == ["AAPL"]
    assert summary["written_record_count"] == 1
    assert summary["data_path"] == str(root / DIVIDEND_DATASET_FILENAME)


def test_output_root_rejects_market_data_paths(tmp_path):
    client = FakeCorporateActionsClient([])

    with pytest.raises(ValueError, match="must not point into bars/trades/quotes"):
        cli.ingest_dividend_corporate_actions(
            symbols=["AAPL"],
            start="2025-01-01",
            end="2025-01-31",
            output_root=tmp_path / "data" / "curated" / "bars_daily",
            client=client,
        )

    assert client.calls == []
