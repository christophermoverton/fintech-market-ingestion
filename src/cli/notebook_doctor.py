"""fintech-notebook-doctor: read-only readiness checks for notebook sessions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.notebook_doctor import (
    build_notebook_doctor_report,
    dumps_notebook_doctor_report_json,
    render_notebook_doctor_report_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fintech-notebook-doctor",
        description=(
            "Run read-only notebook readiness checks for local workspace roots, "
            "curated datasets, optional Drive/archive paths, and optional credential presence."
        ),
    )
    parser.add_argument("--root", default=".", help="Workspace root.")
    parser.add_argument(
        "--drive-root",
        default=None,
        help="Optional mounted Google Drive root path to validate.",
    )
    parser.add_argument(
        "--archive-root",
        default=None,
        help="Optional archive backup root path to validate.",
    )
    parser.add_argument(
        "--check-archive-root",
        action="store_true",
        default=False,
        help="Enable archive root checks. If --archive-root is omitted, infer backups/ path.",
    )
    parser.add_argument(
        "--check-curated-root",
        action="store_true",
        default=False,
        help="Require data/curated to exist; missing curated root becomes a failure.",
    )
    parser.add_argument(
        "--check-research-root",
        action="store_true",
        default=False,
        help="Require data/research to exist; missing research root becomes a failure.",
    )
    parser.add_argument(
        "--check-notebooks",
        action="store_true",
        default=False,
        help="Require notebooks/ to exist.",
    )
    parser.add_argument(
        "--expect-dataset",
        action="append",
        default=[],
        help=(
            "Expected dataset name under data/curated (for example: bars_daily, bars_1m). "
            "May be repeated. Missing expected datasets fail."
        ),
    )
    parser.add_argument(
        "--check-secrets",
        action="store_true",
        default=False,
        help="Check SET/NOT SET presence of expected Alpaca environment variables.",
    )
    parser.add_argument(
        "--require-secrets",
        action="store_true",
        default=False,
        help="Treat missing expected secrets as failures instead of warnings.",
    )
    parser.add_argument(
        "--restore-root",
        default=None,
        help="Optional restore target root to inspect for empty/non-empty restore safety.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit deterministic JSON only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    workspace_root = Path(args.root).expanduser().resolve(strict=False)

    try:
        report = build_notebook_doctor_report(
            root=workspace_root,
            drive_root=args.drive_root,
            archive_root=args.archive_root,
            check_archive_root=args.check_archive_root,
            check_curated_root=args.check_curated_root,
            check_research_root=args.check_research_root,
            check_notebooks=args.check_notebooks,
            check_secrets=args.check_secrets,
            require_secrets=args.require_secrets,
            expect_datasets=tuple(args.expect_dataset),
            restore_root=args.restore_root,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(dumps_notebook_doctor_report_json(report), end="")
    else:
        print(render_notebook_doctor_report_text(report), end="")

    return 1 if report["overall_status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
