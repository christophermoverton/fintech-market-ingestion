from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.cli.init_project import main as init_project_main  # noqa: E402
from src.cli.restore_session import main as restore_session_main  # noqa: E402
from src.cli.save_session import main as save_session_main  # noqa: E402
from src.sessions import load_manifest  # noqa: E402

DEFAULT_OUTPUT_ROOT = Path("artifacts/examples/project_session_quickstart")


def run_quickstart(
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    *,
    google_drive_root: Path | str | None = None,
    write_google_drive: bool = False,
) -> dict[str, Any]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)

    # %% 1. Initialize a notebook-friendly workspace and session.
    init_rc = init_project_main(
        [
            "--root",
            str(root),
            "--notebooks",
            "--with-session",
            "--session-name",
            "quickstart",
        ]
    )
    if init_rc != 0:
        raise RuntimeError(f"fintech-init-project failed with exit code {init_rc}")

    session_manifest_path = _latest_session_manifest(root)
    session_manifest = load_manifest(session_manifest_path)
    session_id = session_manifest.session_id

    # %% 2. Write tiny deterministic local outputs.
    _write_text(root / "configs" / "quickstart_symbols.txt", "AAPL\nMSFT\n")
    _write_text(root / "reports" / "quickstart_summary.txt", "quickstart summary\n")
    _write_json(
        root / "artifacts" / "quickstart" / "metrics.json",
        {"example": "project_session_quickstart", "row_count": 2},
    )
    _write_text(
        root / "data" / "research" / "quickstart_summary.csv",
        "symbol,rows\nAAPL,1\nMSFT,1\n",
    )

    # %% 3. Save locally with a conservative policy.
    local_export_root = root / "artifacts" / "session_exports" / session_id
    save_rc = save_session_main(
        [
            "--root",
            str(root),
            "--session-id",
            session_id,
            "--policy",
            "artifacts_and_reports",
            "--adapter",
            "local",
            "--destination",
            str(local_export_root),
            "--exclude",
            "artifacts/session_exports",
            "data/curated",
        ]
    )
    if save_rc != 0:
        raise RuntimeError(f"fintech-save-session failed with exit code {save_rc}")

    # %% 4. Restore dry-run into a fresh check root.
    restore_check_root = root / "restore_dry_run_check"
    restore_rc = restore_session_main(
        [
            "--root",
            str(restore_check_root),
            "--adapter",
            "local",
            "--source",
            str(local_export_root),
            "--dry-run",
        ]
    )
    if restore_rc != 0:
        raise RuntimeError(f"fintech-restore-session dry-run failed with exit code {restore_rc}")

    # %% 5. Optional mounted-path Google Drive dry-run or explicit write.
    google_drive_status = "not_requested"
    google_drive_manifest_exists = False
    if google_drive_root is not None:
        google_drive_args = [
            "--root",
            str(root),
            "--session-id",
            session_id,
            "--policy",
            "artifacts_and_reports",
            "--adapter",
            "google-drive",
            "--destination",
            str(google_drive_root),
            "--exclude",
            "artifacts/session_exports",
            "data/curated",
        ]
        if write_google_drive:
            google_drive_args.append("--create-destination")
            google_drive_status = "written"
        else:
            google_drive_args.append("--dry-run")
            google_drive_status = "dry_run"
        google_rc = save_session_main(google_drive_args)
        if google_rc != 0:
            raise RuntimeError(f"google-drive save flow failed with exit code {google_rc}")
        google_drive_manifest_exists = (
            Path(google_drive_root) / "session_save_manifest.json"
        ).exists()

    summary = {
        "workspace_root": _path_text(root),
        "session_id": session_id,
        "session_manifest_path": _path_text(session_manifest_path),
        "local_export_root": _path_text(local_export_root),
        "local_save_manifest_path": _path_text(local_export_root / "session_save_manifest.json"),
        "restore_dry_run_root": _path_text(restore_check_root),
        "restore_dry_run_wrote_files": restore_check_root.exists(),
        "google_drive_root": None if google_drive_root is None else _path_text(google_drive_root),
        "google_drive_status": google_drive_status,
        "google_drive_manifest_exists": google_drive_manifest_exists,
        "canonical_boundary": (
            "Persisted copies are transport/export artifacts, not canonical data."
        ),
    }
    summary_path = root / "artifacts" / "quickstart" / "project_session_summary.json"
    _write_json(summary_path, summary)
    summary["summary_path"] = _path_text(summary_path)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a CI-safe notebook-style portable project-session quickstart."
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Output root for all generated quickstart files.",
    )
    parser.add_argument(
        "--google-drive-root",
        default=None,
        help="Optional already-mounted Google Drive filesystem path.",
    )
    parser.add_argument(
        "--write-google-drive",
        action="store_true",
        default=False,
        help="Actually write to --google-drive-root. Without this flag, Drive flow is dry-run.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_quickstart(
        args.output_root,
        google_drive_root=args.google_drive_root,
        write_google_drive=args.write_google_drive,
    )
    print(_format_json(summary), end="")
    return 0


def _latest_session_manifest(root: Path) -> Path:
    manifests = sorted(
        (root / "artifacts" / "sessions").glob("*/session_manifest.json"),
        key=lambda path: (path.stat().st_mtime_ns, path.as_posix()),
    )
    if not manifests:
        raise FileNotFoundError("No session manifest was created under artifacts/sessions")
    return manifests[-1]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_json(payload), encoding="utf-8")


def _format_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _path_text(path: Path | str) -> str:
    return str(Path(path)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
