import json
from pathlib import Path

import pandas as pd

from examples.dividend_research_mart_quickstart import main, run_quickstart
from src.ingestion.corporate_actions_research_mart import (
    DIVIDEND_RESEARCH_MART_METADATA_FILENAME,
)
from src.ingestion.corporate_actions_storage import (
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
)
from src.ingestion.dividend_event_window import (
    DIVIDEND_EVENT_WINDOW_DATASET_FILENAME,
    DIVIDEND_EVENT_WINDOW_METADATA_FILENAME,
)

EXPECTED_SUMMARY_KEYS = {
    "output_root",
    "snapshot_root",
    "research_root",
    "bars_path",
    "event_window_output_root",
    "event_window_data_path",
    "event_window_metadata_path",
    "dividend_record_count",
    "research_mart_row_count",
    "validation_valid",
    "validation_error_count",
    "event_count",
    "bar_count",
    "joined_row_count",
    "symbols",
    "years",
    "preview_rows",
}


def test_quickstart_example_runs_in_temp_directory(tmp_path):
    summary = run_quickstart(tmp_path / "quickstart")

    assert summary["validation_valid"] is True
    assert summary["dividend_record_count"] == 2
    assert summary["research_mart_row_count"] == 2
    assert summary["joined_row_count"] > 0


def test_quickstart_example_requires_no_live_alpaca_credentials(monkeypatch, tmp_path):
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    summary = run_quickstart(tmp_path / "quickstart")

    assert summary["validation_valid"] is True


def test_quickstart_example_writes_expected_output_files(tmp_path):
    output_root = tmp_path / "quickstart"
    summary = run_quickstart(output_root)

    snapshot_root = Path(summary["snapshot_root"])
    research_root = Path(summary["research_root"])
    bars_path = Path(summary["bars_path"])
    event_window_root = Path(summary["event_window_output_root"])

    assert (snapshot_root / DIVIDEND_DATASET_FILENAME).exists()
    assert (snapshot_root / DIVIDEND_METADATA_FILENAME).exists()
    assert (research_root / DIVIDEND_RESEARCH_MART_METADATA_FILENAME).exists()
    assert sorted(research_root.rglob("*.parquet"))
    assert bars_path.exists()
    assert (event_window_root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME).exists()
    assert (event_window_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).exists()
    assert (output_root / "summary.json").exists()


def test_quickstart_example_summary_contains_deterministic_expected_keys(tmp_path):
    output_root = tmp_path / "quickstart"
    summary = run_quickstart(output_root)
    summary_text = (output_root / "summary.json").read_text(encoding="utf-8")

    assert set(summary) == EXPECTED_SUMMARY_KEYS
    assert json.loads(summary_text) == summary
    assert summary_text == json.dumps(summary, sort_keys=True, indent=2) + "\n"
    assert summary["symbols"] == ["AAPL", "MSFT"]
    assert summary["years"] == [2024]
    assert summary["preview_rows"]


def test_quickstart_example_research_mart_validation_is_valid(tmp_path):
    summary = run_quickstart(tmp_path / "quickstart")

    assert summary["validation_valid"] is True
    assert summary["validation_error_count"] == 0


def test_quickstart_example_joined_row_count_is_positive(tmp_path):
    summary = run_quickstart(tmp_path / "quickstart")

    assert summary["event_count"] == 2
    assert summary["bar_count"] == 6
    assert summary["joined_row_count"] == 6
    assert len(summary["preview_rows"]) == 5


def test_quickstart_example_does_not_write_repo_level_data_when_given_temp_output_root(
    monkeypatch, tmp_path
):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    output_root = tmp_path / "quickstart"
    monkeypatch.chdir(cwd)

    summary = run_quickstart(output_root)

    assert not (cwd / "data").exists()
    for key in [
        "snapshot_root",
        "research_root",
        "bars_path",
        "event_window_output_root",
        "event_window_data_path",
        "event_window_metadata_path",
    ]:
        assert Path(summary[key]).resolve().is_relative_to(output_root.resolve())


def test_quickstart_example_uses_plain_python_entry_point(tmp_path, capsys):
    exit_code = main(["--output-root", str(tmp_path / "quickstart")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["validation_valid"] is True


def test_quickstart_example_rerun_is_deterministic_with_same_output_root(tmp_path):
    output_root = tmp_path / "quickstart"

    first = run_quickstart(output_root)
    first_summary_text = (output_root / "summary.json").read_text(encoding="utf-8")
    first_bars = pd.read_parquet(first["bars_path"])

    second = run_quickstart(output_root)
    second_summary_text = (output_root / "summary.json").read_text(encoding="utf-8")
    second_bars = pd.read_parquet(second["bars_path"])

    assert second == first
    assert second_summary_text == first_summary_text
    pd.testing.assert_frame_equal(second_bars, first_bars)
