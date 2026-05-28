"""fintech-stratlake-handoff-report: summarize local curated data for StratLake handoff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.handoff.stratlake_handoff import (
    DEFAULT_OUTPUT_PATH,
    build_stratlake_handoff_report,
    write_stratlake_handoff_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fintech-stratlake-handoff-report",
        description=(
            "Generate a deterministic local handoff report for StratLake MARKETLAKE_ROOT. "
            "The report is derived and non-canonical."
        ),
    )
    parser.add_argument("--root", default=".", help="Workspace root.")
    parser.add_argument(
        "--curated-root",
        default="data/curated",
        help="Curated dataset root. Relative paths resolve from --root.",
    )
    parser.add_argument(
        "--qa-root",
        default="artifacts/qa",
        help="QA artifacts root. Relative paths resolve from --root.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON report path.",
    )
    parser.add_argument(
        "--include-row-counts",
        action="store_true",
        default=False,
        help="Optionally compute row counts from parquet files (can be expensive).",
    )
    parser.add_argument(
        "--generated-at-utc",
        default=None,
        help="Optional fixed UTC timestamp for deterministic report generation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve(strict=False)
    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (root / output_path).resolve(strict=False)

    try:
        report = build_stratlake_handoff_report(
            root=root,
            curated_root=args.curated_root,
            qa_root=args.qa_root,
            include_row_counts=args.include_row_counts,
            generated_at_utc=args.generated_at_utc,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    write_stratlake_handoff_report(report, output_path=output_path)

    print("StratLake handoff report:")
    print(f"  schema_version: {report['schema_version']}")
    print(f"  report_type: {report['report_type']}")
    print(f"  curated_root: {report['curated_root']}")
    print(f"  stratlake_marketlake_root: {report['stratlake_marketlake_root']}")
    print(
        "  available_datasets: "
        + (", ".join(report["available_datasets"]) if report["available_datasets"] else "(none)")
    )
    print(f"  qa_status: {report['qa']['status']}")
    print(f"  output_path: {output_path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
