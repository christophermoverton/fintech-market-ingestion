import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from examples.dividend_research_mart_quickstart import run_quickstart
from examples.dividend_research_pipeline_workflow import run_pipeline_workflow
from src.cli import build_dividend_research_mart as build_cli
from src.cli import join_dividend_event_windows as join_cli
from src.cli import validate_dividend_research_mart as validate_cli
from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_research_mart import (
    DIVIDEND_RESEARCH_MART_METADATA_FILENAME,
    read_dividend_research_mart,
    validate_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
    write_dividend_corporate_actions,
)
from src.ingestion.dividend_event_window import (
    DIVIDEND_EVENT_WINDOW_DATASET_FILENAME,
    DIVIDEND_EVENT_WINDOW_DATASET_ROLE,
    DIVIDEND_EVENT_WINDOW_METADATA_FILENAME,
    join_dividend_events_to_bars_result,
    write_dividend_event_window_output,
)


def test_m7_research_mart_builder_cli_matches_python_api(tmp_path, capsys):
    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    cli_research_root = tmp_path / "cli" / "data" / "research" / "dividends"
    api_research_root = tmp_path / "api" / "data" / "research" / "dividends"

    exit_code = build_cli.main(
        [
            "--snapshot-root",
            str(snapshot_root),
            "--research-root",
            str(cli_research_root),
        ]
    )
    cli_summary = read_json_stdout(capsys)
    api_result = write_dividend_research_mart_from_snapshot(
        snapshot_root=snapshot_root,
        research_root=api_research_root,
    )
    api_metadata = api_result.metadata

    assert exit_code == 0
    assert cli_summary["input_record_count"] == api_result.input_record_count
    assert cli_summary["written_record_count"] == api_result.written_record_count
    assert (
        cli_summary["invalid_partition_record_count"] == api_result.invalid_partition_record_count
    )
    assert cli_summary["symbols"] == api_metadata["symbols"]
    assert cli_summary["years"] == api_metadata["years"]
    assert cli_summary["event_anchor"] == api_metadata["event_anchor"]
    assert Path(cli_summary["metadata_path"]).name == DIVIDEND_RESEARCH_MART_METADATA_FILENAME


def test_m7_research_mart_validation_cli_matches_python_api(tmp_path, capsys):
    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    research_root = tmp_path / "data" / "research" / "dividends"
    write_dividend_research_mart_from_snapshot(snapshot_root, research_root)

    exit_code = validate_cli.main(["--research-root", str(research_root)])
    cli_summary = read_json_stdout(capsys)
    api_summary = validate_dividend_research_mart(research_root).as_dict()

    assert exit_code == 0
    assert cli_summary == api_summary
    assert cli_summary["valid"] is True


def test_m7_event_window_join_cli_output_matches_python_api(tmp_path, capsys):
    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    research_root = tmp_path / "data" / "research" / "dividends"
    write_dividend_research_mart_from_snapshot(snapshot_root, research_root)
    bars_path = make_synthetic_bars(tmp_path / "bars" / "daily_bars.parquet")
    output_path = tmp_path / "data" / "research" / "event_windows" / "joined.parquet"

    exit_code = join_cli.main(
        [
            "--dividend-source",
            "research-mart",
            "--snapshot-root",
            str(snapshot_root),
            "--research-root",
            str(research_root),
            "--bars-path",
            str(bars_path),
            "--pre-window-days",
            "1",
            "--post-window-days",
            "1",
            "--output-path",
            str(output_path),
        ]
    )
    cli_summary = read_json_stdout(capsys)
    direct = join_dividend_events_to_bars_result(
        read_dividend_research_mart(research_root),
        pd.read_parquet(bars_path),
        pre_window_days=1,
        post_window_days=1,
    )

    assert exit_code == 0
    pd.testing.assert_frame_equal(pd.read_parquet(output_path), direct.frame)
    assert cli_summary["event_count"] == direct.event_count
    assert cli_summary["bar_count"] == direct.bar_count
    assert cli_summary["joined_row_count"] == direct.joined_row_count


def test_m7_event_window_contract_output_cli_matches_writer_contract(tmp_path, capsys):
    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    research_root = tmp_path / "data" / "research" / "dividends"
    write_dividend_research_mart_from_snapshot(snapshot_root, research_root)
    bars_path = make_synthetic_bars(tmp_path / "bars" / "daily_bars.parquet")
    cli_output_root = tmp_path / "data" / "research" / "event_windows" / "cli-run"
    api_output_root = tmp_path / "data" / "research" / "event_windows" / "api-run"

    exit_code = join_cli.main(
        [
            "--dividend-source",
            "research-mart",
            "--snapshot-root",
            str(snapshot_root),
            "--research-root",
            str(research_root),
            "--bars-path",
            str(bars_path),
            "--pre-window-days",
            "1",
            "--post-window-days",
            "1",
            "--output-root",
            str(cli_output_root),
        ]
    )
    cli_summary = read_json_stdout(capsys)
    direct_join = join_dividend_events_to_bars_result(
        read_dividend_research_mart(research_root),
        pd.read_parquet(bars_path),
        pre_window_days=1,
        post_window_days=1,
    )
    api_output = write_dividend_event_window_output(
        direct_join,
        output_root=api_output_root,
        source_dividend_path=research_root,
        source_bar_path=bars_path,
        pre_window_days=1,
        post_window_days=1,
        bar_timeframe="1D",
    )
    cli_metadata = json.loads(
        (cli_output_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).read_text(encoding="utf-8")
    )

    assert exit_code == 0
    assert (cli_output_root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME).exists()
    assert (cli_output_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).exists()
    assert cli_summary["output_root"] == str(cli_output_root)
    assert cli_summary["data_path"] == str(cli_output_root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME)
    assert cli_summary["metadata_path"] == str(
        cli_output_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME
    )
    assert cli_summary["dataset_role"] == DIVIDEND_EVENT_WINDOW_DATASET_ROLE
    assert cli_metadata["dataset_role"] == api_output.metadata["dataset_role"]
    assert cli_metadata["event_count"] == api_output.metadata["event_count"]
    assert cli_metadata["bar_count"] == api_output.metadata["bar_count"]
    assert cli_metadata["joined_row_count"] == api_output.metadata["joined_row_count"]
    assert cli_metadata["schema_fields"] == api_output.metadata["schema_fields"]


def test_m7_notebook_quickstart_smoke_runs_without_credentials(monkeypatch, tmp_path):
    clear_alpaca_env(monkeypatch)

    summary = run_quickstart(tmp_path / "quickstart")

    assert summary["validation_valid"] is True
    assert Path(summary["event_window_data_path"]).exists()
    assert Path(summary["event_window_metadata_path"]).exists()
    assert summary["joined_row_count"] > 0


def test_m7_pipeline_workflow_smoke_runs_without_credentials_or_scheduler_dependencies(
    monkeypatch, tmp_path
):
    clear_alpaca_env(monkeypatch)

    summary = run_pipeline_workflow(tmp_path / "pipeline")

    assert set(summary["stage_status_values"].values()) == {"completed"}
    assert Path(summary["event_window_metadata_path"]).exists()
    assert summary["scheduler_dependencies"] == []
    assert summary["no_live_credentials_required"] is True


def test_m7_cli_and_writer_surfaces_do_not_mutate_inputs(tmp_path, capsys):
    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    research_root = tmp_path / "data" / "research" / "dividends"
    write_dividend_research_mart_from_snapshot(snapshot_root, research_root)
    bars_path = make_synthetic_bars(tmp_path / "bars" / "daily_bars.parquet")

    snapshot_before = hash_tree(snapshot_root)
    research_before = hash_tree(research_root)
    bars_before = hash_file(bars_path)

    validate_cli.main(["--research-root", str(research_root)])
    capsys.readouterr()
    join_cli.main(
        [
            "--dividend-source",
            "research-mart",
            "--snapshot-root",
            str(snapshot_root),
            "--research-root",
            str(research_root),
            "--bars-path",
            str(bars_path),
            "--output-path",
            str(tmp_path / "outputs" / "joined.parquet"),
        ]
    )
    capsys.readouterr()
    direct_join = join_dividend_events_to_bars_result(
        read_dividend_research_mart(research_root),
        pd.read_parquet(bars_path),
    )
    write_dividend_event_window_output(
        direct_join,
        output_root=tmp_path / "outputs" / "contract",
        source_dividend_path=research_root,
        source_bar_path=bars_path,
    )

    assert hash_tree(snapshot_root) == snapshot_before
    assert hash_tree(research_root) == research_before
    assert hash_file(bars_path) == bars_before


def test_m7_workflow_surfaces_require_no_live_credentials(monkeypatch, tmp_path):
    clear_alpaca_env(monkeypatch)

    snapshot_root = make_synthetic_dividend_snapshot(tmp_path / "snapshot")
    research_root = tmp_path / "data" / "research" / "dividends"
    bars_path = make_synthetic_bars(tmp_path / "bars" / "daily_bars.parquet")
    build_summary = build_cli.build_dividend_research_mart(snapshot_root, research_root)
    validation_summary = validate_cli.validate_research_mart(research_root)
    join_summary = join_cli.join_dividend_event_windows(
        dividend_source="research-mart",
        snapshot_root=snapshot_root,
        research_root=research_root,
        bars_path=bars_path,
        output_root=tmp_path / "outputs" / "contract",
    )

    assert build_summary["written_record_count"] == 2
    assert validation_summary["valid"] is True
    assert join_summary["joined_row_count"] > 0


def test_m7_example_workflows_are_deterministic_on_rerun(tmp_path):
    quickstart_root = tmp_path / "quickstart"
    pipeline_root = tmp_path / "pipeline"

    first_quickstart = run_quickstart(quickstart_root)
    first_quickstart_summary = (quickstart_root / "summary.json").read_text(encoding="utf-8")
    second_quickstart = run_quickstart(quickstart_root)
    second_quickstart_summary = (quickstart_root / "summary.json").read_text(encoding="utf-8")

    first_pipeline = run_pipeline_workflow(pipeline_root)
    first_pipeline_summary = (pipeline_root / "workflow_summary.json").read_text(encoding="utf-8")
    second_pipeline = run_pipeline_workflow(pipeline_root)
    second_pipeline_summary = (pipeline_root / "workflow_summary.json").read_text(encoding="utf-8")

    assert second_quickstart == first_quickstart
    assert second_quickstart_summary == first_quickstart_summary
    assert second_pipeline == first_pipeline
    assert second_pipeline_summary == first_pipeline_summary


def make_synthetic_dividend_snapshot(root: Path) -> Path:
    snapshot_root = root / "data" / "curated" / "corporate_actions" / "dividends"
    records = [
        normalize_corporate_action_payload(
            {
                "id": "m7-aapl-cash-dividend",
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
            },
            source="synthetic_m7",
        ),
        normalize_corporate_action_payload(
            {
                "id": "m7-msft-stock-dividend",
                "symbol": "MSFT",
                "type": "stock_dividend",
                "process_date": "2025-01-15",
                "declaration_date": "2025-01-02",
                "ex_date": "2025-01-10",
                "record_date": "2025-01-13",
                "payable_date": "2025-01-31",
                "cash_amount": None,
                "stock_amount": "0.05",
                "currency": None,
            },
            source="synthetic_m7",
        ),
    ]
    write_dividend_corporate_actions(
        records,
        root_dir=snapshot_root,
        ingest_start_date="2025-01-01",
        ingest_end_date="2025-01-31",
        source="synthetic_m7",
        action_types=["cash_dividend", "stock_dividend"],
    )
    assert (snapshot_root / DIVIDEND_DATASET_FILENAME).exists()
    assert (snapshot_root / DIVIDEND_METADATA_FILENAME).exists()
    return snapshot_root


def make_synthetic_bars(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    bars = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "ts_utc": f"2025-01-{day:02d}T00:00:00Z",
                "open": 100.0 + day,
                "high": 101.0 + day,
                "low": 99.0 + day,
                "close": 100.5 + day,
                "volume": 1_000 + day,
                "timeframe": "1D",
            }
            for day in range(9, 12)
        ]
        + [
            {
                "symbol": "MSFT",
                "ts_utc": f"2025-01-{day:02d}T00:00:00Z",
                "open": 200.0 + day,
                "high": 201.0 + day,
                "low": 199.0 + day,
                "close": 200.5 + day,
                "volume": 2_000 + day,
                "timeframe": "1D",
            }
            for day in range(9, 12)
        ]
    )
    bars.sort_values(["symbol", "ts_utc"]).to_parquet(path, index=False)
    return path


def read_json_stdout(capsys) -> dict[str, Any]:
    stdout = capsys.readouterr().out
    assert stdout.endswith("\n")
    return json.loads(stdout)


def clear_alpaca_env(monkeypatch) -> None:
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)


def hash_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): hash_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
