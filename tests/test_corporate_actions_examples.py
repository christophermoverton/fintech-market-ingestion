import json
from pathlib import Path

from examples import corporate_actions_dividend_ingestion_example as example
from src.cli.ingest_corporate_actions import build_parser

DOC_PATH = Path("docs/corporate_actions_dividends.md")
EXAMPLE_PATH = Path("examples/corporate_actions_dividend_ingestion_example.py")


def test_dividend_ingestion_example_runs_without_credentials(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    output_root = tmp_path / "artifacts" / "examples" / "corporate_actions_dividends"

    exit_code = example.main(["--output-root", str(output_root)])
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["fetched_record_count"] == 2
    assert summary["written_record_count"] == 2
    assert (output_root / "dividends.parquet").exists()
    assert (output_root / "metadata.json").exists()


def test_documented_cli_flags_match_parser():
    parser = build_parser()
    parser_flags = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option.startswith("--")
    }
    docs = DOC_PATH.read_text(encoding="utf-8")

    for flag in [
        "--symbols",
        "--start",
        "--end",
        "--types",
        "--output-root",
        "--sort",
        "--limit",
    ]:
        assert flag in parser_flags
        assert flag in docs


def test_corporate_actions_docs_and_example_use_repository_relative_paths():
    combined = DOC_PATH.read_text(encoding="utf-8") + EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "C:/" not in combined
    assert "C:\\" not in combined
    assert "/Users/" not in combined


def test_corporate_actions_docs_and_example_do_not_contain_secret_values():
    combined = DOC_PATH.read_text(encoding="utf-8") + EXAMPLE_PATH.read_text(encoding="utf-8")
    lower = combined.lower()

    assert "your_key_here" not in lower
    assert "your_secret_here" not in lower
    assert "sk_" not in lower
