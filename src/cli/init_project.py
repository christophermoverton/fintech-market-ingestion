"""fintech-init-project: Bootstrap a local workspace for fintech-market-ingestion.

Creates local workspace directories and sample config files in the target root
(current directory by default). Does not write into the installed package or
mutate any package-internal directories.

Usage:
    fintech-init-project [--root PATH] [--notebooks] [--force]
    fintech-init-project [--root PATH] [--notebooks] [--with-session] [--session-name NAME]
    python -m src.cli.init_project [--root PATH] [--notebooks] [--with-session] [--session-name NAME] [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.sessions import (
    create_project_session_manifest,
    session_manifest_path,
    write_project_session_manifest_for_workspace,
)

TICKERS_SAMPLE_CONTENT = """\
# Sample ticker list for fintech-market-ingestion.
# One symbol per line. Lines starting with # are ignored.
AAPL
MSFT
NVDA
AMZN
GOOGL
META
TSLA
JPM
V
MA
"""

ENV_EXAMPLE_CONTENT = """\
# Alpaca API credentials - copy this file to .env and fill in your keys.
# Do NOT commit .env to version control.
ALPACA_API_KEY_ID=your_api_key_id_here
ALPACA_API_SECRET_KEY=your_secret_key_here
# Optional: override the data feed. Default is iex (free tier).
ALPACA_FEED=iex
# Optional: override the Alpaca market data base URL. If unset, the client default is used.
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
"""

CREATED = "created"
SKIPPED = "skipped (already exists)"
FORCED = "overwritten (--force)"
DEFAULT_SESSION_NAME = "default"


def _create_dirs(root: Path, include_notebooks: bool) -> list[tuple[str, str]]:
    dirs = [
        root / "configs",
        root / "data" / "curated",
        root / "reports",
        root / "artifacts",
    ]
    if include_notebooks:
        dirs.append(root / "notebooks")

    results: list[tuple[str, str]] = []
    for d in dirs:
        existed = d.exists()
        d.mkdir(parents=True, exist_ok=True)
        rel = str(d.relative_to(root))
        results.append((rel + "/", SKIPPED if existed else CREATED))
    return results


def _write_file(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return SKIPPED
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    return FORCED if (existed and force) else CREATED


def _create_session_manifest(root: Path, session_name: str) -> tuple[str, str]:
    manifest = create_project_session_manifest(session_name=session_name)
    manifest_path = session_manifest_path(root, manifest.session_id)
    status = SKIPPED if manifest_path.exists() else CREATED
    if status == CREATED:
        write_project_session_manifest_for_workspace(root, manifest)
    return (str(manifest_path.relative_to(root)), status)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="fintech-init-project",
        description=(
            "Bootstrap a local fintech-market-ingestion workspace. "
            "Creates local directories and sample config files without touching "
            "the installed package."
        ),
    )
    ap.add_argument(
        "--root",
        default=".",
        help="Target workspace root directory (default: current working directory).",
    )
    ap.add_argument(
        "--notebooks",
        action="store_true",
        default=False,
        help="Also create a notebooks/ directory.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite generated sample files (tickers_sample.txt, .env.example) if they exist.",
    )
    ap.add_argument(
        "--with-session",
        action="store_true",
        default=False,
        help=(
            "Also create a metadata-only project-session manifest under "
            "artifacts/sessions/<session_id>/."
        ),
    )
    ap.add_argument(
        "--session-name",
        default=None,
        help=(
            "Project session name to record when --with-session is used "
            f"(default: {DEFAULT_SESSION_NAME})."
        ),
    )
    args = ap.parse_args(argv)

    root = Path(args.root).expanduser().resolve(strict=False)

    print(f"Initializing workspace at: {root}")
    print()

    summary: list[tuple[str, str]] = []

    # Create directories
    summary.extend(_create_dirs(root, args.notebooks))

    # Write sample files
    tickers_path = root / "configs" / "tickers_sample.txt"
    tickers_status = _write_file(tickers_path, TICKERS_SAMPLE_CONTENT, args.force)
    summary.append((str(tickers_path.relative_to(root)), tickers_status))

    env_example_path = root / ".env.example"
    env_status = _write_file(env_example_path, ENV_EXAMPLE_CONTENT, args.force)
    summary.append((str(env_example_path.relative_to(root)), env_status))

    if args.with_session:
        session_name = args.session_name or DEFAULT_SESSION_NAME
        summary.append(_create_session_manifest(root, session_name))

    # Print summary
    max_path_len = max(len(p) for p, _ in summary)
    for path_str, status in summary:
        print(f"  {path_str:<{max_path_len}}  {status}")

    print()
    print("Done. Next steps:")
    print("  1. Copy .env.example to .env and fill in your Alpaca API credentials.")
    print("  2. Edit configs/tickers_sample.txt with your desired symbols.")
    print("  3. Run a backfill:")
    print()
    print("     fintech-backfill-daily \\")
    print("       --symbols configs/tickers_sample.txt \\")
    print("       --start 2025-01-01 \\")
    print("       --end 2025-04-01 \\")
    print("       --out data/curated/bars_daily \\")
    print("       --feed iex \\")
    print("       --window month")
    print()
    print("     fintech-backfill-1m \\")
    print("       --symbols configs/tickers_sample.txt \\")
    print("       --start 2025-01-02 \\")
    print("       --end 2025-01-03 \\")
    print("       --out data/curated/bars_1m \\")
    print("       --feed iex \\")
    print("       --sleep-ms 200 \\")
    print("       --no-progress")

    if args.with_session:
        print()
        print("Project session:")
        print("  A metadata-only session manifest was written under artifacts/sessions/.")
        print("  Re-running --with-session creates a new timestamped session manifest.")
        print("  Session initialization does not copy curated data or run persistence sync.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
