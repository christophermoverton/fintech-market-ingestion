from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    validate_dividend_research_mart,
)


def validate_research_mart(
    research_root: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
) -> dict[str, Any]:
    """Validate and inspect the derived dividend research mart."""
    return validate_dividend_research_mart(research_root).as_dict()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and inspect the derived dividend research mart."
    )
    parser.add_argument(
        "--research-root",
        default=str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT),
        help="Root for the derived dividend research mart",
    )
    parser.add_argument(
        "--summary-output",
        help="Optional path to write the same deterministic JSON summary printed to stdout",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = validate_research_mart(research_root=args.research_root)
    summary_json = _format_summary_json(summary)
    if args.summary_output:
        summary_output_path = Path(args.summary_output)
        summary_output_path.parent.mkdir(parents=True, exist_ok=True)
        summary_output_path.write_text(summary_json, encoding="utf-8")
    print(summary_json, end="")
    return 0


def _format_summary_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
