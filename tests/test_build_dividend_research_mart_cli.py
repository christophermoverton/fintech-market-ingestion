import json
from pathlib import Path

import pytest
import tomllib

from src.cli import build_dividend_research_mart as cli
from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    read_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
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


@pytest.fixture
def dividend_snapshot(tmp_path):
    snapshot_root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    records = [
        normalized(cash_dividend_payload(id="ca-snap-1", symbol="aapl", ex_date="2025-01-10")),
        normalized(stock_dividend_payload(id="ca-snap-2", symbol="MSFT", ex_date="2024-02-10")),
    ]
    write_dividend_corporate_actions(
        records,
        root_dir=snapshot_root,
        ingest_start_date="2024-01-01",
        ingest_end_date="2025-12-31",
        source="alpaca",
        action_types=["cash_dividend", "stock_dividend"],
    )
    return snapshot_root


def test_cli_parser_defaults_and_summary_output_argument(tmp_path):
    parser = cli.build_parser()

    args = parser.parse_args(["--summary-output", str(tmp_path / "summary.json")])

    assert args.snapshot_root == str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT)
    assert args.research_root == str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT)
    assert args.summary_output == str(tmp_path / "summary.json")


def test_cli_parser_accepts_explicit_roots_and_summary_output(tmp_path):
    parser = cli.build_parser()
    snapshot_root = tmp_path / "snapshot"
    research_root = tmp_path / "research"
    summary_output = tmp_path / "summary.json"

    args = parser.parse_args(
        [
            "--snapshot-root",
            str(snapshot_root),
            "--research-root",
            str(research_root),
            "--summary-output",
            str(summary_output),
        ]
    )

    assert args.snapshot_root == str(snapshot_root)
    assert args.research_root == str(research_root)
    assert args.summary_output == str(summary_output)


def test_cli_builds_research_mart_from_synthetic_snapshot(dividend_snapshot, tmp_path):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"

    summary = cli.build_dividend_research_mart(dividend_snapshot, research_root)
    loaded = read_dividend_research_mart(research_root)

    assert loaded["symbol"].tolist() == ["AAPL", "MSFT"]
    assert loaded["year"].tolist() == [2025, 2024]
    assert summary == {
        "snapshot_root": str(dividend_snapshot),
        "research_root": str(research_root),
        "input_record_count": 2,
        "written_record_count": 2,
        "invalid_partition_record_count": 0,
        "metadata_path": str(research_root / "metadata.json"),
        "event_anchor": "ex_date",
        "symbol_count": 2,
        "year_count": 2,
        "symbols": ["AAPL", "MSFT"],
        "years": [2024, 2025],
    }


def test_cli_summary_fields_match_direct_python_api_result(dividend_snapshot, tmp_path):
    direct_root = tmp_path / "direct" / "research"
    cli_root = tmp_path / "cli" / "research"

    direct_result = write_dividend_research_mart_from_snapshot(dividend_snapshot, direct_root)
    cli_summary = cli.build_dividend_research_mart(dividend_snapshot, cli_root)
    direct_summary = cli._summary_from_result(
        direct_result,
        snapshot_root=dividend_snapshot,
        research_root=direct_root,
    )

    comparable_cli_summary = dict(cli_summary)
    comparable_cli_summary["research_root"] = direct_summary["research_root"]
    comparable_cli_summary["metadata_path"] = direct_summary["metadata_path"]

    assert comparable_cli_summary == direct_summary


def test_main_prints_and_writes_same_deterministic_json(dividend_snapshot, tmp_path, capsys):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    summary_output = tmp_path / "summary.json"

    exit_code = cli.main(
        [
            "--snapshot-root",
            str(dividend_snapshot),
            "--research-root",
            str(research_root),
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert stdout == summary_output.read_text(encoding="utf-8")
    assert stdout.endswith("\n")
    assert json.loads(stdout)["metadata_path"] == str(research_root / "metadata.json")


def test_main_creates_summary_output_parent_directories(dividend_snapshot, tmp_path, capsys):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    summary_output = tmp_path / "nested" / "summaries" / "summary.json"

    exit_code = cli.main(
        [
            "--snapshot-root",
            str(dividend_snapshot),
            "--research-root",
            str(research_root),
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert summary_output.exists()
    assert summary_output.read_text(encoding="utf-8") == stdout


def test_cli_does_not_mutate_canonical_snapshot_files(dividend_snapshot, tmp_path):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    data_path = dividend_snapshot / DIVIDEND_DATASET_FILENAME
    metadata_path = dividend_snapshot / DIVIDEND_METADATA_FILENAME
    before_data = data_path.read_bytes()
    before_metadata = metadata_path.read_bytes()

    cli.build_dividend_research_mart(dividend_snapshot, research_root)

    assert data_path.read_bytes() == before_data
    assert metadata_path.read_bytes() == before_metadata


def test_cli_requires_no_live_credentials(monkeypatch, dividend_snapshot, tmp_path):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    summary = cli.build_dividend_research_mart(dividend_snapshot, research_root)

    assert summary["written_record_count"] == 2


def test_cli_rejects_research_root_equal_to_snapshot_root(dividend_snapshot):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.build_dividend_research_mart(dividend_snapshot, dividend_snapshot)


def test_cli_rejects_research_root_inside_snapshot_root(dividend_snapshot):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.build_dividend_research_mart(dividend_snapshot, dividend_snapshot / "research")


def test_cli_rejects_research_root_containing_snapshot_root(dividend_snapshot):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.build_dividend_research_mart(dividend_snapshot, dividend_snapshot.parent)


def test_cli_rejects_curated_research_output_root(dividend_snapshot, tmp_path):
    curated_research_root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"

    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.build_dividend_research_mart(dividend_snapshot, curated_research_root)


def test_console_script_entry_point_is_declared_and_importable():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["fintech-build-dividend-research-mart"]
        == "src.cli.build_dividend_research_mart:main"
    )
    assert callable(cli.main)
