import hashlib
import json
from pathlib import Path

import pandas as pd

from examples.dividend_research_pipeline_workflow import (
    STAGE_ORDER,
    build_research_mart,
    build_workflow_context,
    create_synthetic_daily_bars,
    create_synthetic_dividend_snapshot,
    join_event_windows,
    main,
    run_pipeline_workflow,
    validate_research_mart,
    write_event_window_output,
)
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
    "stage_order",
    "stage_status_values",
    "stage_results",
    "generated_paths",
    "validation_valid",
    "dividend_record_count",
    "research_mart_row_count",
    "event_count",
    "bar_count",
    "joined_row_count",
    "symbols",
    "years",
    "event_window_metadata_path",
    "event_window_data_path",
    "no_live_credentials_required",
    "scheduler_dependencies",
}


def test_pipeline_workflow_runs_in_temp_directory(tmp_path):
    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert summary["validation_valid"] is True
    assert summary["dividend_record_count"] == 2
    assert summary["research_mart_row_count"] == 2
    assert summary["joined_row_count"] > 0


def test_pipeline_workflow_requires_no_live_alpaca_credentials(monkeypatch, tmp_path):
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert summary["no_live_credentials_required"] is True
    assert summary["validation_valid"] is True


def test_pipeline_workflow_writes_expected_files(tmp_path):
    output_root = tmp_path / "pipeline"
    summary = run_pipeline_workflow(output_root)
    generated = summary["generated_paths"]

    snapshot_root = Path(generated["snapshot_root"])
    research_root = Path(generated["research_root"])
    bars_path = Path(generated["bars_path"])
    event_window_root = Path(generated["event_window_output_root"])

    assert (snapshot_root / DIVIDEND_DATASET_FILENAME).exists()
    assert (snapshot_root / DIVIDEND_METADATA_FILENAME).exists()
    assert (research_root / DIVIDEND_RESEARCH_MART_METADATA_FILENAME).exists()
    assert sorted(research_root.rglob("*.parquet"))
    assert bars_path.exists()
    assert (event_window_root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME).exists()
    assert (event_window_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).exists()
    assert (output_root / "workflow_summary.json").exists()


def test_pipeline_workflow_summary_contains_deterministic_expected_keys(tmp_path):
    output_root = tmp_path / "pipeline"
    summary = run_pipeline_workflow(output_root)
    summary_text = (output_root / "workflow_summary.json").read_text(encoding="utf-8")

    assert set(summary) == EXPECTED_SUMMARY_KEYS
    assert json.loads(summary_text) == summary
    assert summary_text == json.dumps(summary, sort_keys=True, indent=2) + "\n"
    assert summary["symbols"] == ["AAPL", "MSFT"]
    assert summary["years"] == [2024]
    assert summary["scheduler_dependencies"] == []


def test_pipeline_workflow_stage_order_is_deterministic(tmp_path):
    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert summary["stage_order"] == STAGE_ORDER
    assert [stage["name"] for stage in summary["stage_results"]] == STAGE_ORDER


def test_pipeline_workflow_all_stage_statuses_completed(tmp_path):
    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert set(summary["stage_status_values"].values()) == {"completed"}
    assert {stage["status"] for stage in summary["stage_results"]} == {"completed"}


def test_pipeline_workflow_research_mart_validation_is_valid(tmp_path):
    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert summary["validation_valid"] is True
    validation_stage = next(
        stage for stage in summary["stage_results"] if stage["name"] == "validate_research_mart"
    )
    assert validation_stage["metadata"]["error_count"] == 0


def test_pipeline_workflow_joined_row_count_is_positive(tmp_path):
    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert summary["event_count"] == 2
    assert summary["bar_count"] == 6
    assert summary["joined_row_count"] == 6


def test_pipeline_workflow_does_not_write_repo_level_data_when_given_temp_output_root(
    monkeypatch, tmp_path
):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    output_root = tmp_path / "pipeline"
    monkeypatch.chdir(cwd)

    summary = run_pipeline_workflow(output_root)

    assert not (cwd / "data").exists()
    for generated_path in summary["generated_paths"].values():
        assert Path(generated_path).resolve().is_relative_to(output_root.resolve())
    assert Path(summary["event_window_data_path"]).resolve().is_relative_to(output_root.resolve())
    assert (
        Path(summary["event_window_metadata_path"]).resolve().is_relative_to(output_root.resolve())
    )


def test_pipeline_workflow_synthetic_snapshot_files_remain_stable_after_later_stages(
    tmp_path,
):
    context = build_workflow_context(tmp_path / "pipeline")

    create_synthetic_dividend_snapshot(context)
    before = _hash_tree(context.snapshot_root)

    build_research_mart(context)
    validate_research_mart(context)
    create_synthetic_daily_bars(context)
    join_event_windows(context)
    write_event_window_output(context)

    assert _hash_tree(context.snapshot_root) == before


def test_pipeline_workflow_rerun_is_deterministic_with_same_output_root(tmp_path):
    output_root = tmp_path / "pipeline"

    first = run_pipeline_workflow(output_root)
    first_summary_text = (output_root / "workflow_summary.json").read_text(encoding="utf-8")
    first_bars = pd.read_parquet(first["generated_paths"]["bars_path"])

    second = run_pipeline_workflow(output_root)
    second_summary_text = (output_root / "workflow_summary.json").read_text(encoding="utf-8")
    second_bars = pd.read_parquet(second["generated_paths"]["bars_path"])

    assert second == first
    assert second_summary_text == first_summary_text
    pd.testing.assert_frame_equal(second_bars, first_bars)


def test_pipeline_workflow_imports_no_scheduler_dependencies():
    source = Path("examples/dividend_research_pipeline_workflow.py").read_text(encoding="utf-8")

    for dependency in ["airflow", "prefect", "dagster"]:
        assert f"import {dependency}" not in source
        assert f"from {dependency}" not in source


def test_pipeline_workflow_uses_plain_python_entry_point(tmp_path, capsys):
    exit_code = main(["--output-root", str(tmp_path / "pipeline")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["validation_valid"] is True


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
