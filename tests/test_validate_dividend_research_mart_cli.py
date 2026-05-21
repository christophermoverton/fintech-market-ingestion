import json
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from src.cli import validate_dividend_research_mart as cli
from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    DIVIDEND_RESEARCH_MART_METADATA_FILENAME,
    DIVIDEND_RESEARCH_MART_PARTITION_COLUMNS,
    inspect_dividend_research_mart,
    validate_dividend_research_mart,
    write_dividend_research_mart,
)
from src.ingestion.dividend_research_semantics import DEFAULT_DIVIDEND_EVENT_ANCHOR


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
def research_mart(tmp_path):
    root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    write_dividend_research_mart(
        [
            normalized(cash_dividend_payload(id="ca-snap-1", symbol="aapl", ex_date="2025-01-10")),
            normalized(stock_dividend_payload(id="ca-snap-2", symbol="MSFT", ex_date="2024-02-10")),
        ],
        root_dir=root,
        source_snapshot_path=tmp_path
        / "data"
        / "curated"
        / "corporate_actions"
        / "dividends"
        / "dividends.parquet",
        start="2024-01-01",
        end="2025-12-31",
    )
    return root


def metadata_path(root):
    return root / DIVIDEND_RESEARCH_MART_METADATA_FILENAME


def read_metadata(root):
    return json.loads(metadata_path(root).read_text(encoding="utf-8"))


def write_metadata(root, metadata):
    metadata_path(root).write_text(
        json.dumps(metadata, sort_keys=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )


def snapshot_file_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_positive_synthetic_mart_validation_passes(research_mart):
    result = validate_dividend_research_mart(research_mart)

    assert result.valid is True
    assert result.errors == []
    assert result.warnings == []
    assert result.inspection.valid is True


def test_inspection_summary_reports_expected_coverage_and_contract(research_mart):
    inspection = inspect_dividend_research_mart(research_mart)

    assert inspection.as_dict() == {
        "research_root": str(research_mart),
        "metadata_path": str(metadata_path(research_mart)),
        "exists": True,
        "valid": True,
        "row_count": 2,
        "symbol_count": 2,
        "year_count": 2,
        "symbols": ["AAPL", "MSFT"],
        "years": [2024, 2025],
        "partition_columns": DIVIDEND_RESEARCH_MART_PARTITION_COLUMNS,
        "event_anchor": DEFAULT_DIVIDEND_EVENT_ANCHOR,
        "event_anchor_source": "normalized.ex_date",
        "dataset": "corporate_actions_dividends_research_mart",
        "dataset_role": "research_mart",
        "source_dataset_role": "deterministic_snapshot",
        "schema_fields": read_metadata(research_mart)["schema_fields"],
        "missing_required_fields": [],
        "validation_errors": [],
        "validation_warning_count": 0,
        "validation_error_count": 0,
    }


def test_missing_metadata_returns_invalid_with_clear_error(research_mart):
    metadata_path(research_mart).unlink()

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert any("metadata does not exist" in error for error in result.errors)


def test_invalid_metadata_json_returns_invalid_with_clear_error(research_mart):
    metadata_path(research_mart).write_text("{not-json", encoding="utf-8")

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert any("metadata is not valid JSON" in error for error in result.errors)


def test_bad_event_anchor_metadata_returns_invalid(research_mart):
    metadata = read_metadata(research_mart)
    metadata["event_anchor"] = "payable_date"
    write_metadata(research_mart, metadata)

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert any("event_anchor must be ex_date" in error for error in result.errors)


def test_bad_partition_columns_metadata_returns_invalid(research_mart):
    metadata = read_metadata(research_mart)
    metadata["partition_columns"] = ["symbol"]
    write_metadata(research_mart, metadata)

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert any("partition_columns" in error for error in result.errors)


def test_missing_required_schema_metadata_field_returns_invalid(research_mart):
    metadata = read_metadata(research_mart)
    metadata["schema_fields"] = [
        field for field in metadata["schema_fields"] if field != "corporate_action_id"
    ]
    write_metadata(research_mart, metadata)

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert result.inspection.missing_required_fields == ["corporate_action_id"]
    assert any("schema_fields is missing required field" in error for error in result.errors)


def test_row_count_mismatch_returns_invalid(research_mart):
    metadata = read_metadata(research_mart)
    metadata["row_count"] = 999
    write_metadata(research_mart, metadata)

    result = validate_dividend_research_mart(research_mart)

    assert result.valid is False
    assert any(
        "row_count=999 does not match loaded row_count=2" in error for error in result.errors
    )


def test_cli_output_matches_python_validation_result(research_mart, capsys):
    exit_code = cli.main(["--research-root", str(research_mart)])
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert json.loads(stdout) == validate_dividend_research_mart(research_mart).as_dict()


def test_cli_returns_zero_and_reports_invalid_json_for_validation_failure(research_mart, capsys):
    metadata_path(research_mart).unlink()

    exit_code = cli.main(["--research-root", str(research_mart)])
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["valid"] is False
    assert any("metadata does not exist" in error for error in summary["errors"])


def test_summary_output_writes_same_deterministic_json(research_mart, tmp_path, capsys):
    summary_output = tmp_path / "summary.json"

    exit_code = cli.main(
        [
            "--research-root",
            str(research_mart),
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert stdout == summary_output.read_text(encoding="utf-8")
    assert stdout.endswith("\n")


def test_summary_output_parent_directories_are_created(research_mart, tmp_path, capsys):
    summary_output = tmp_path / "nested" / "summaries" / "summary.json"

    cli.main(
        [
            "--research-root",
            str(research_mart),
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert summary_output.exists()
    assert summary_output.read_text(encoding="utf-8") == stdout


def test_validation_and_inspection_do_not_mutate_research_mart_files(research_mart):
    before = snapshot_file_bytes(research_mart)

    validate_dividend_research_mart(research_mart)
    inspect_dividend_research_mart(research_mart)
    cli.main(["--research-root", str(research_mart)])

    assert snapshot_file_bytes(research_mart) == before


def test_validation_requires_no_live_credentials(monkeypatch, research_mart):
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    assert validate_dividend_research_mart(research_mart).valid is True


def test_cli_parser_defaults_to_research_mart_root():
    parser = cli.build_parser()

    args = parser.parse_args([])

    assert args.research_root == str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT)
    assert args.summary_output is None


def test_console_script_entry_point_is_declared_and_importable():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["fintech-validate-dividend-research-mart"]
        == "src.cli.validate_dividend_research_mart:main"
    )
    assert callable(cli.main)
