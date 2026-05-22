"""fintech-init-project: Bootstrap a local workspace for fintech-market-ingestion.

Creates local workspace directories and sample config files in the target root
(current directory by default). Does not write into the installed package or
mutate any package-internal directories.

Usage:
    fintech-init-project [--root PATH] [--notebooks] [--force]
    python -m src.cli.init_project [--root PATH] [--notebooks] [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here
# Optional: override the data feed. Default is iex (free tier).
ALPACA_DATA_FEED=iex
"""

CREATED = "created"
SKIPPED = "skipped (already exists)"
FORCED = "overwritten (--force)"


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
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
