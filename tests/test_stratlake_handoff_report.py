from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.stratlake_handoff_report import main as handoff_cli_main
from src.handoff.stratlake_handoff import (
    build_stratlake_handoff_report,
    dumps_stratlake_handoff_report_json,
    write_stratlake_handoff_report,
)


def _write_placeholder_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"placeholder")


def _create_daily_dataset(curated_root: Path) -> None:
    _write_placeholder_parquet(
        curated_root / "bars_daily" / "symbol=AAPL" / "date=2025-01-02" / "part-000.parquet"
    )
    _write_placeholder_parquet(
        curated_root / "bars_daily" / "symbol=MSFT" / "date=2025-01-03" / "part-001.parquet"
    )


def _create_1m_dataset(curated_root: Path) -> None:
    _write_placeholder_parquet(
        curated_root / "bars_1m" / "symbol=AAPL" / "date=2025-01-02" / "part-000.parquet"
    )
    _write_placeholder_parquet(
        curated_root / "bars_1m" / "symbol=AAPL" / "date=2025-01-03" / "part-001.parquet"
    )


def test_missing_curated_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_stratlake_handoff_report(
            root=tmp_path,
            curated_root=tmp_path / "data" / "curated",
            generated_at_utc="2026-05-28T00:00:00Z",
        )


def test_empty_curated_root_summary(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    curated_root.mkdir(parents=True)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        qa_root=tmp_path / "artifacts" / "qa",
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["available_datasets"] == []
    assert report["timeframes"] == []
    assert report["symbols"] == []
    assert report["date_min"] is None
    assert report["date_max"] is None
    assert report["non_canonical"] is True
    assert report["stratlake_marketlake_root"] == "data/curated"
    assert report["qa"]["status"] == "unknown"


def test_daily_only_dataset_summary(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["available_datasets"] == ["bars_daily"]
    assert report["timeframes"] == ["1D"]
    assert report["symbols"] == ["AAPL", "MSFT"]
    assert report["date_min"] == "2025-01-02"
    assert report["date_max"] == "2025-01-03"

    daily = report["datasets"]["bars_daily"]
    assert daily["dataset_path"] == "data/curated/bars_daily"
    assert daily["timeframe"] == "1D"
    assert daily["file_count"] == 2
    assert daily["row_count"] is None


def test_1m_only_dataset_summary(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_1m_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["available_datasets"] == ["bars_1m"]
    assert report["timeframes"] == ["1Min"]
    assert report["symbols"] == ["AAPL"]
    assert report["date_min"] == "2025-01-02"
    assert report["date_max"] == "2025-01-03"


def test_combined_daily_and_1m_dataset_summary(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)
    _create_1m_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["available_datasets"] == ["bars_1m", "bars_daily"]
    assert report["timeframes"] == ["1D", "1Min"]
    assert report["symbols"] == ["AAPL", "MSFT"]
    assert report["date_min"] == "2025-01-02"
    assert report["date_max"] == "2025-01-03"


def test_qa_missing_root_gives_unknown_status(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        qa_root=tmp_path / "artifacts" / "qa",
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["qa"]["status"] == "unknown"
    assert report["qa"]["latest_run_id"] is None
    assert report["qa"]["artifacts"] == []


def test_qa_existing_artifacts_are_referenced(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    qa_run = tmp_path / "artifacts" / "qa" / "qa_bars_daily_1D_2025-01-01_2025-01-31_XNYS"
    qa_run.mkdir(parents=True, exist_ok=True)
    (qa_run / "qa_summary_by_symbol.csv").write_text("symbol,rows\nAAPL,2\n", encoding="utf-8")
    (qa_run / "qa_coverage_by_symbol.csv").write_text("symbol,coverage\nAAPL,1.0\n", encoding="utf-8")
    (qa_run / "qa_summary_global.csv").write_text(
        "overall_status,total_rows\nPASS,2\n",
        encoding="utf-8",
    )

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        qa_root=tmp_path / "artifacts" / "qa",
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["qa"]["status"] == "passed"
    assert report["qa"]["latest_run_id"] == "qa_bars_daily_1D_2025-01-01_2025-01-31_XNYS"
    assert report["qa"]["latest_run_path"].startswith("artifacts/qa/")
    assert report["qa"]["artifacts"] == [
        "qa_coverage_by_symbol.csv",
        "qa_summary_by_symbol.csv",
        "qa_summary_global.csv",
    ]


def test_qa_selected_run_uses_deterministic_lexical_order(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    qa_root = tmp_path / "artifacts" / "qa"
    older = qa_root / "qa_bars_daily_1D_2025-01-01_2025-01-02_XNYS"
    newer = qa_root / "qa_bars_daily_1D_2025-01-01_2025-01-31_XNYS"
    older.mkdir(parents=True, exist_ok=True)
    newer.mkdir(parents=True, exist_ok=True)
    (older / "qa_summary_global.csv").write_text("overall_status,total_rows\nPASS,1\n", encoding="utf-8")
    (newer / "qa_summary_global.csv").write_text("overall_status,total_rows\nWARN,1\n", encoding="utf-8")

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        qa_root=qa_root,
    )

    assert report["qa"]["latest_run_id"] == newer.name
    assert report["qa"]["status"] == "warning"


def test_deterministic_json_serialization(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report_one = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )
    report_two = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    dumped_one = dumps_stratlake_handoff_report_json(report_one)
    dumped_two = dumps_stratlake_handoff_report_json(report_two)

    assert dumped_one == dumped_two
    assert dumped_one.endswith("\n")


def test_default_generated_at_utc_is_none_and_deterministic(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report_one = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
    )
    report_two = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
    )

    assert report_one["generated_at_utc"] is None
    assert report_two["generated_at_utc"] is None
    assert dumps_stratlake_handoff_report_json(report_one) == dumps_stratlake_handoff_report_json(
        report_two
    )


def test_explicit_generated_at_utc_is_preserved(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T12:00:00Z",
    )

    assert report["generated_at_utc"] == "2026-05-28T12:00:00Z"


def test_write_report_creates_output_path(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    output_path = tmp_path / "artifacts" / "handoff" / "stratlake_marketlake_handoff.json"
    written = write_stratlake_handoff_report(report, output_path=output_path)

    assert written == output_path
    assert output_path.exists()
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["curated_root"] == "data/curated"


def test_project_relative_serialization_and_runtime_paths(tmp_path: Path) -> None:
    curated_root = tmp_path / "data" / "curated"
    _create_daily_dataset(curated_root)

    report = build_stratlake_handoff_report(
        root=tmp_path,
        curated_root=curated_root,
        qa_root=tmp_path / "artifacts" / "qa",
        generated_at_utc="2026-05-28T00:00:00Z",
    )

    assert report["curated_root"] == "data/curated"
    assert report["curated_root_runtime_path"].endswith("/data/curated")
    assert report["qa"]["qa_root"] == "artifacts/qa"


def test_stratlake_handoff_cli_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        handoff_cli_main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out


def test_stratlake_handoff_cli_smoke(tmp_path: Path, capsys) -> None:
    workspace_root = tmp_path / "workspace"
    curated_root = workspace_root / "data" / "curated"
    _create_daily_dataset(curated_root)

    output = workspace_root / "artifacts" / "handoff" / "stratlake_marketlake_handoff.json"

    rc = handoff_cli_main(
        [
            "--root",
            str(workspace_root),
            "--curated-root",
            str(curated_root),
            "--output",
            str(output),
            "--generated-at-utc",
            "2026-05-28T00:00:00Z",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "StratLake handoff report:" in captured.out
    assert output.exists()


def test_stratlake_handoff_cli_output_is_deterministic_without_timestamp(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    curated_root = workspace_root / "data" / "curated"
    _create_daily_dataset(curated_root)

    output = workspace_root / "artifacts" / "handoff" / "stratlake_marketlake_handoff.json"

    rc_first = handoff_cli_main(
        [
            "--root",
            str(workspace_root),
            "--curated-root",
            "data/curated",
            "--output",
            str(output),
        ]
    )
    assert rc_first == 0
    first_text = output.read_text(encoding="utf-8")

    rc_second = handoff_cli_main(
        [
            "--root",
            str(workspace_root),
            "--curated-root",
            "data/curated",
            "--output",
            str(output),
        ]
    )
    assert rc_second == 0
    second_text = output.read_text(encoding="utf-8")

    assert first_text == second_text
    assert '"generated_at_utc": null' in first_text
