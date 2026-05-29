"""Read-only notebook readiness checks for fintech-market-ingestion."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

NOTEBOOK_DOCTOR_SCHEMA_VERSION = 1
NOTEBOOK_DOCTOR_REPORT_TYPE = "fintech_notebook_doctor"

LIKELY_DATASETS: tuple[str, ...] = (
    "bars_daily",
    "bars_1m",
    "corporate_actions",
)
SECRET_ENV_VARS: tuple[str, ...] = (
    "ALPACA_API_KEY_ID",
    "ALPACA_API_SECRET_KEY",
)

_STATUS_ORDER: tuple[str, ...] = ("pass", "warn", "fail", "skip")


def build_notebook_doctor_report(
    *,
    root: Path | str,
    drive_root: Path | str | None = None,
    archive_root: Path | str | None = None,
    check_archive_root: bool = False,
    check_curated_root: bool = False,
    check_research_root: bool = False,
    check_notebooks: bool = False,
    check_secrets: bool = False,
    require_secrets: bool = False,
    expect_datasets: tuple[str, ...] = (),
    restore_root: Path | str | None = None,
) -> dict[str, Any]:
    workspace_root = Path(root).expanduser().resolve(strict=False)
    checks: list[dict[str, Any]] = []

    root_exists = workspace_root.exists()
    _add_check(
        checks,
        name="project_root_exists",
        status="pass" if root_exists else "fail",
        severity="error",
        message=(
            "Project root exists."
            if root_exists
            else f"Project root does not exist: {workspace_root.as_posix()}"
        ),
        path=workspace_root.as_posix(),
    )

    root_is_dir = workspace_root.is_dir()
    _add_check(
        checks,
        name="project_root_is_directory",
        status="pass" if root_is_dir else "fail",
        severity="error",
        message=(
            "Project root is a directory." if root_is_dir else "Project root is not a directory."
        ),
        path=workspace_root.as_posix(),
    )

    _check_required_workspace_dirs(checks, workspace_root)
    _check_curated_root_and_datasets(
        checks,
        workspace_root,
        check_curated_root=check_curated_root,
        expect_datasets=expect_datasets,
    )
    _check_research_root(
        checks,
        workspace_root,
        check_research_root=check_research_root,
    )
    _check_notebooks_root(
        checks,
        workspace_root,
        check_notebooks=check_notebooks,
    )

    if drive_root is not None:
        drive_runtime_root = _resolve_runtime_path(workspace_root, drive_root)
        _check_directory(
            checks,
            name="drive_root_exists",
            path=drive_runtime_root,
            missing_status="fail",
            missing_message=(
                "Drive root is not reachable at the provided path. "
                "Mount Drive first if this path should exist."
            ),
            present_message="Drive root exists and is readable.",
            require_readable=True,
            severity="error",
        )
    else:
        drive_runtime_root = None

    if archive_root is not None or check_archive_root:
        inferred_archive_root = False
        if archive_root is not None:
            archive_runtime_root = _resolve_runtime_path(workspace_root, archive_root)
        else:
            inferred_archive_root = True
            if drive_runtime_root is not None:
                archive_runtime_root = drive_runtime_root / "backups"
            else:
                archive_runtime_root = workspace_root / "backups"

        if inferred_archive_root:
            _add_check(
                checks,
                name="archive_root_inferred",
                status="warn",
                severity="warning",
                message=(
                    "Archive root was inferred. Pass --archive-root to pin the exact backup root."
                ),
                path=archive_runtime_root.as_posix(),
            )

        archive_ok = _check_directory(
            checks,
            name="archive_root_exists",
            path=archive_runtime_root,
            missing_status="fail",
            missing_message="Archive root is missing.",
            present_message="Archive root exists and is readable.",
            require_readable=True,
            severity="error",
        )
        if archive_ok:
            _check_archive_candidates(checks, archive_runtime_root)

    if check_secrets:
        _check_secret_presence(
            checks,
            workspace_root,
            require_secrets=require_secrets,
        )

    if restore_root is not None:
        _check_restore_root(checks, workspace_root, restore_root)

    summary = _build_summary(checks)
    overall_status = _overall_status_from_summary(summary)

    return {
        "schema_version": NOTEBOOK_DOCTOR_SCHEMA_VERSION,
        "report_type": NOTEBOOK_DOCTOR_REPORT_TYPE,
        "root": workspace_root.as_posix(),
        "overall_status": overall_status,
        "checks": checks,
        "summary": summary,
        "notes": [
            "This doctor is read-only.",
            "Secret checks report SET/NOT SET only and never print values.",
            "No Drive mounting, API calls, ingestion, QA, restore, archive writes, or session mutations are performed.",
        ],
    }


def dumps_notebook_doctor_report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def render_notebook_doctor_report_text(report: dict[str, Any]) -> str:
    lines = [
        "Fintech notebook doctor",
        f"overall_status: {report['overall_status']}",
        "",
    ]

    for check in report.get("checks", []):
        lines.append(f"[{check['status']}] {check['name']} - {check['message']}")

    return "\n".join(lines) + "\n"


def _check_required_workspace_dirs(checks: list[dict[str, Any]], root: Path) -> None:
    _check_directory(
        checks,
        name="configs_dir_exists",
        path=root / "configs",
        missing_status="warn",
        missing_message="configs directory is missing.",
        present_message="configs directory exists.",
        require_readable=False,
        severity="warning",
    )
    _check_directory(
        checks,
        name="data_dir_exists",
        path=root / "data",
        missing_status="fail",
        missing_message="data directory is missing.",
        present_message="data directory exists.",
        require_readable=False,
        severity="error",
    )
    _check_directory(
        checks,
        name="artifacts_dir_exists",
        path=root / "artifacts",
        missing_status="warn",
        missing_message="artifacts directory is missing.",
        present_message="artifacts directory exists.",
        require_readable=False,
        severity="warning",
    )
    _check_directory(
        checks,
        name="reports_dir_exists",
        path=root / "reports",
        missing_status="warn",
        missing_message="reports directory is missing.",
        present_message="reports directory exists.",
        require_readable=False,
        severity="warning",
    )


def _check_curated_root_and_datasets(
    checks: list[dict[str, Any]],
    root: Path,
    *,
    check_curated_root: bool,
    expect_datasets: tuple[str, ...],
) -> None:
    curated_root = root / "data" / "curated"
    curated_exists = curated_root.exists() and curated_root.is_dir()

    if not curated_exists and not check_curated_root:
        _add_check(
            checks,
            name="curated_root_exists",
            status="warn",
            severity="warning",
            message="data/curated is missing.",
            path=curated_root.as_posix(),
        )
        _add_check(
            checks,
            name="curated_dataset_scan",
            status="skip",
            severity="info",
            message="Skipped curated dataset checks because data/curated is missing.",
            path=curated_root.as_posix(),
        )
        return

    curated_ok = _check_directory(
        checks,
        name="curated_root_exists",
        path=curated_root,
        missing_status="fail" if check_curated_root else "warn",
        missing_message="data/curated is missing.",
        present_message="data/curated exists and is readable.",
        require_readable=True,
        severity="error" if check_curated_root else "warning",
    )
    if not curated_ok:
        _add_check(
            checks,
            name="curated_dataset_scan",
            status="skip",
            severity="info",
            message="Skipped curated dataset checks because data/curated is missing.",
            path=curated_root.as_posix(),
        )
        return

    expected = [dataset.strip() for dataset in expect_datasets if dataset.strip()]
    dataset_order = _stable_dataset_order(expected)

    for dataset_name in dataset_order:
        dataset_root = curated_root / dataset_name
        expected_dataset = dataset_name in expected
        check_name = f"dataset_{dataset_name}_present"

        if not dataset_root.exists() or not dataset_root.is_dir():
            _add_check(
                checks,
                name=check_name,
                status="fail" if expected_dataset else "warn",
                severity="error" if expected_dataset else "warning",
                message=(
                    f"Expected dataset is missing: {dataset_name}."
                    if expected_dataset
                    else f"Likely dataset directory is missing: {dataset_name}."
                ),
                path=dataset_root.as_posix(),
            )
            continue

        parquet_count = _count_parquet_files(dataset_root)
        if parquet_count > 0:
            _add_check(
                checks,
                name=check_name,
                status="pass",
                severity="info",
                message=f"Found {parquet_count} parquet file(s) for {dataset_name}.",
                path=dataset_root.as_posix(),
                file_count=parquet_count,
            )
        else:
            _add_check(
                checks,
                name=check_name,
                status="fail" if expected_dataset else "warn",
                severity="error" if expected_dataset else "warning",
                message=(
                    f"Expected dataset exists but has no parquet files: {dataset_name}."
                    if expected_dataset
                    else f"Dataset directory exists but has no parquet files: {dataset_name}."
                ),
                path=dataset_root.as_posix(),
                file_count=0,
            )


def _check_research_root(
    checks: list[dict[str, Any]],
    root: Path,
    *,
    check_research_root: bool,
) -> None:
    _check_directory(
        checks,
        name="research_root_exists",
        path=root / "data" / "research",
        missing_status="fail" if check_research_root else "warn",
        missing_message="data/research is missing.",
        present_message="data/research exists and is readable.",
        require_readable=True,
        severity="error" if check_research_root else "warning",
    )


def _check_notebooks_root(
    checks: list[dict[str, Any]],
    root: Path,
    *,
    check_notebooks: bool,
) -> None:
    notebooks_root = root / "notebooks"
    if not check_notebooks:
        _add_check(
            checks,
            name="notebooks_root_exists",
            status="skip",
            severity="info",
            message="Notebook directory check was not requested.",
            path=notebooks_root.as_posix(),
        )
        return

    _check_directory(
        checks,
        name="notebooks_root_exists",
        path=notebooks_root,
        missing_status="fail",
        missing_message="notebooks directory is missing.",
        present_message="notebooks directory exists and is readable.",
        require_readable=True,
        severity="error",
    )


def _check_archive_candidates(checks: list[dict[str, Any]], archive_root: Path) -> None:
    candidate_packs = []
    for child in sorted(path for path in archive_root.iterdir() if path.is_dir()):
        if (child / "manifest.json").is_file() and (child / "shards").is_dir():
            candidate_packs.append(child)

    if candidate_packs:
        _add_check(
            checks,
            name="archive_pack_candidates",
            status="pass",
            severity="info",
            message=(
                f"Archive root contains {len(candidate_packs)} candidate backup pack directory(ies)."
            ),
            path=archive_root.as_posix(),
            candidate_count=len(candidate_packs),
            candidates=[candidate.name for candidate in candidate_packs],
        )
        return

    _add_check(
        checks,
        name="archive_pack_candidates",
        status="warn",
        severity="warning",
        message="Archive root exists but no candidate backup packs were found.",
        path=archive_root.as_posix(),
        candidate_count=0,
    )


def _check_secret_presence(
    checks: list[dict[str, Any]],
    root: Path,
    *,
    require_secrets: bool,
) -> None:
    dotenv_path = root / ".env"
    _add_check(
        checks,
        name="dotenv_file_present",
        status="pass" if dotenv_path.is_file() else "warn",
        severity="info" if dotenv_path.is_file() else "warning",
        message=(
            ".env file is present in the workspace root."
            if dotenv_path.is_file()
            else ".env file is not present in the workspace root."
        ),
        path=dotenv_path.as_posix(),
    )

    for env_name in SECRET_ENV_VARS:
        raw_value = os.environ.get(env_name)
        is_set = raw_value is not None and raw_value.strip() != ""
        status = "pass" if is_set else ("fail" if require_secrets else "warn")
        severity = "info" if is_set else ("error" if require_secrets else "warning")

        _add_check(
            checks,
            name=f"secret_{env_name}",
            status=status,
            severity=severity,
            message=(
                f"{env_name} is SET."
                if is_set
                else (
                    f"{env_name} is NOT SET. Live Alpaca ingestion will not work until configured."
                )
            ),
            value="SET" if is_set else "NOT SET",
        )


def _check_restore_root(
    checks: list[dict[str, Any]], workspace_root: Path, restore_root: Path | str
) -> None:
    restore_runtime_root = _resolve_runtime_path(workspace_root, restore_root)
    parent = restore_runtime_root.parent

    if not parent.exists() or not parent.is_dir():
        _add_check(
            checks,
            name="restore_root_parent_exists",
            status="fail",
            severity="error",
            message="Restore root parent directory is missing.",
            path=parent.as_posix(),
        )
        return

    _add_check(
        checks,
        name="restore_root_parent_exists",
        status="pass",
        severity="info",
        message="Restore root parent directory exists.",
        path=parent.as_posix(),
    )

    if not restore_runtime_root.exists():
        _add_check(
            checks,
            name="restore_root_state",
            status="pass",
            severity="info",
            message="Restore root does not exist yet and can be created by restore commands.",
            path=restore_runtime_root.as_posix(),
        )
        return

    if not restore_runtime_root.is_dir():
        _add_check(
            checks,
            name="restore_root_state",
            status="fail",
            severity="error",
            message="Restore root exists but is not a directory.",
            path=restore_runtime_root.as_posix(),
        )
        return

    is_empty = not any(restore_runtime_root.iterdir())
    if is_empty:
        _add_check(
            checks,
            name="restore_root_state",
            status="pass",
            severity="info",
            message="Restore root exists and is empty.",
            path=restore_runtime_root.as_posix(),
        )
        return

    _add_check(
        checks,
        name="restore_root_state",
        status="warn",
        severity="warning",
        message=(
            "Restore root is non-empty. restore --overwrite-policy fail would fail if target files exist."
        ),
        path=restore_runtime_root.as_posix(),
    )


def _stable_dataset_order(expected: list[str]) -> list[str]:
    ordered: list[str] = []
    for dataset in LIKELY_DATASETS:
        if dataset not in ordered:
            ordered.append(dataset)

    for dataset in sorted(set(expected)):
        if dataset not in ordered:
            ordered.append(dataset)
    return ordered


def _resolve_runtime_path(workspace_root: Path, path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    return candidate.resolve(strict=False)


def _check_directory(
    checks: list[dict[str, Any]],
    *,
    name: str,
    path: Path,
    missing_status: str,
    missing_message: str,
    present_message: str,
    require_readable: bool,
    severity: str,
) -> bool:
    if not path.exists():
        _add_check(
            checks,
            name=name,
            status=missing_status,
            severity="error" if missing_status == "fail" else severity,
            message=missing_message,
            path=path.as_posix(),
        )
        return False

    if not path.is_dir():
        _add_check(
            checks,
            name=name,
            status="fail",
            severity="error",
            message="Path exists but is not a directory.",
            path=path.as_posix(),
        )
        return False

    if require_readable and not os.access(path, os.R_OK):
        _add_check(
            checks,
            name=name,
            status="fail",
            severity="error",
            message="Directory exists but is not readable.",
            path=path.as_posix(),
        )
        return False

    _add_check(
        checks,
        name=name,
        status="pass",
        severity="info",
        message=present_message,
        path=path.as_posix(),
    )
    return True


def _count_parquet_files(root: Path) -> int:
    count = 0
    for path in sorted(root.rglob("*.parquet")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        count += 1
    return count


def _add_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    status: str,
    severity: str,
    message: str,
    **extra: Any,
) -> None:
    if status not in _STATUS_ORDER:
        raise ValueError(f"Unsupported check status: {status}")

    check: dict[str, Any] = {
        "name": name,
        "status": status,
        "severity": severity,
        "message": message,
    }
    for key in sorted(extra):
        value = extra[key]
        if value is None:
            continue
        check[key] = value
    checks.append(check)


def _build_summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    summary = {status: 0 for status in _STATUS_ORDER}
    for check in checks:
        summary[check["status"]] += 1
    return summary


def _overall_status_from_summary(summary: dict[str, int]) -> str:
    if summary["fail"] > 0:
        return "fail"
    if summary["warn"] > 0:
        return "warn"
    return "pass"
