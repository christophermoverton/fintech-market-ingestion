from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.notebook_doctor import main as notebook_doctor_cli_main
from src.notebook_doctor import (
    build_notebook_doctor_report,
    dumps_notebook_doctor_report_json,
)


def _write_placeholder_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"placeholder")


def _create_workspace(
    root: Path, *, include_research: bool = True, include_notebooks: bool = True
) -> None:
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / "data" / "curated").mkdir(parents=True, exist_ok=True)
    if include_research:
        (root / "data" / "research").mkdir(parents=True, exist_ok=True)
    (root / "artifacts").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    if include_notebooks:
        (root / "notebooks").mkdir(parents=True, exist_ok=True)


def _find_check(report: dict, name: str) -> dict:
    for check in report["checks"]:
        if check["name"] == name:
            return check
    raise AssertionError(f"missing check: {name}")


def test_missing_root_fails(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"

    report = build_notebook_doctor_report(root=missing)

    assert report["overall_status"] == "fail"
    assert _find_check(report, "project_root_exists")["status"] == "fail"


def test_initialized_workspace_reports_readiness(tmp_path: Path) -> None:
    _create_workspace(tmp_path)
    _write_placeholder_parquet(
        tmp_path
        / "data"
        / "curated"
        / "bars_daily"
        / "symbol=AAPL"
        / "date=2026-05-28"
        / "part-0.parquet"
    )

    report = build_notebook_doctor_report(root=tmp_path)

    assert report["overall_status"] in {"pass", "warn"}
    assert _find_check(report, "project_root_exists")["status"] == "pass"


def test_missing_drive_root_when_provided_fails(tmp_path: Path) -> None:
    _create_workspace(tmp_path)

    report = build_notebook_doctor_report(
        root=tmp_path,
        drive_root=tmp_path / "missing_drive",
    )

    assert report["overall_status"] == "fail"
    assert _find_check(report, "drive_root_exists")["status"] == "fail"


def test_archive_root_exists_with_no_packs_warns(tmp_path: Path) -> None:
    _create_workspace(tmp_path)
    archive_root = tmp_path / "backups"
    archive_root.mkdir(parents=True, exist_ok=True)

    report = build_notebook_doctor_report(
        root=tmp_path,
        archive_root=archive_root,
        check_archive_root=True,
    )

    assert _find_check(report, "archive_root_exists")["status"] == "pass"
    assert _find_check(report, "archive_pack_candidates")["status"] == "warn"


def test_archive_root_with_candidate_pack_passes_candidate_check(tmp_path: Path) -> None:
    _create_workspace(tmp_path)
    pack_root = tmp_path / "backups" / "backup_001"
    (pack_root / "shards").mkdir(parents=True, exist_ok=True)
    (pack_root / "manifest.json").write_text("{}\n", encoding="utf-8")

    report = build_notebook_doctor_report(
        root=tmp_path,
        archive_root=tmp_path / "backups",
        check_archive_root=True,
    )

    candidate_check = _find_check(report, "archive_pack_candidates")
    assert candidate_check["status"] == "pass"
    assert candidate_check["candidate_count"] == 1


def test_secret_checks_report_set_not_set_without_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_workspace(tmp_path)
    (tmp_path / ".env").write_text("ALPACA_API_KEY_ID=from_file\n", encoding="utf-8")

    monkeypatch.setenv("ALPACA_API_KEY_ID", "actual-key-value")
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)

    report = build_notebook_doctor_report(
        root=tmp_path,
        check_secrets=True,
    )

    key_check = _find_check(report, "secret_ALPACA_API_KEY_ID")
    secret_check = _find_check(report, "secret_ALPACA_API_SECRET_KEY")

    assert key_check["status"] == "pass"
    assert key_check["value"] == "SET"
    assert secret_check["status"] == "warn"
    assert secret_check["value"] == "NOT SET"

    dumped = dumps_notebook_doctor_report_json(report)
    assert "actual-key-value" not in dumped


def test_expected_dataset_present_passes_dataset_check(tmp_path: Path) -> None:
    _create_workspace(tmp_path)
    _write_placeholder_parquet(
        tmp_path
        / "data"
        / "curated"
        / "bars_daily"
        / "symbol=AAPL"
        / "date=2026-05-28"
        / "part-0.parquet"
    )

    report = build_notebook_doctor_report(
        root=tmp_path,
        check_curated_root=True,
        expect_datasets=("bars_daily",),
    )

    assert _find_check(report, "dataset_bars_daily_present")["status"] == "pass"


def test_expected_dataset_missing_fails(tmp_path: Path) -> None:
    _create_workspace(tmp_path)

    report = build_notebook_doctor_report(
        root=tmp_path,
        check_curated_root=True,
        expect_datasets=("bars_1m",),
    )

    assert report["overall_status"] == "fail"
    assert _find_check(report, "dataset_bars_1m_present")["status"] == "fail"


def test_json_output_is_deterministic(tmp_path: Path) -> None:
    _create_workspace(tmp_path)

    report_one = build_notebook_doctor_report(
        root=tmp_path,
        check_archive_root=True,
    )
    report_two = build_notebook_doctor_report(
        root=tmp_path,
        check_archive_root=True,
    )

    dumped_one = dumps_notebook_doctor_report_json(report_one)
    dumped_two = dumps_notebook_doctor_report_json(report_two)

    assert dumped_one == dumped_two
    assert dumped_one.endswith("\n")


def test_cli_help_works(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        notebook_doctor_cli_main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out


def test_cli_json_smoke(tmp_path: Path, capsys) -> None:
    _create_workspace(tmp_path)
    _write_placeholder_parquet(
        tmp_path
        / "data"
        / "curated"
        / "bars_daily"
        / "symbol=AAPL"
        / "date=2026-05-28"
        / "part-0.parquet"
    )

    rc = notebook_doctor_cli_main(
        [
            "--root",
            str(tmp_path),
            "--check-curated-root",
            "--expect-dataset",
            "bars_daily",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert rc in {0, 1}

    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    assert payload["report_type"] == "fintech_notebook_doctor"
    assert "checks" in payload


def test_exit_code_behavior_warn_and_fail(tmp_path: Path) -> None:
    _create_workspace(tmp_path, include_research=False, include_notebooks=False)

    warn_rc = notebook_doctor_cli_main(["--root", str(tmp_path)])
    fail_rc = notebook_doctor_cli_main(
        [
            "--root",
            str(tmp_path),
            "--expect-dataset",
            "bars_1m",
            "--check-curated-root",
        ]
    )

    assert warn_rc == 0
    assert fail_rc == 1
