from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    DividendResearchMartResult,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT

UNSAFE_RESEARCH_ROOT_MESSAGE = (
    "Dividend research mart output must be a derived research path and must not overlap "
    "with curated/canonical dividend snapshot paths."
)


def build_dividend_research_mart(
    snapshot_root: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    research_root: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
) -> dict[str, Any]:
    """Build the derived dividend research mart from an existing curated snapshot."""
    _validate_research_root(snapshot_root=snapshot_root, research_root=research_root)
    result = write_dividend_research_mart_from_snapshot(
        snapshot_root=snapshot_root,
        research_root=research_root,
    )
    return _summary_from_result(result, snapshot_root=snapshot_root, research_root=research_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the derived dividend research mart from a curated dividend snapshot."
    )
    parser.add_argument(
        "--snapshot-root",
        default=str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT),
        help="Input root for the curated dividend corporate-actions snapshot",
    )
    parser.add_argument(
        "--research-root",
        default=str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT),
        help="Output root for the derived dividend research mart",
    )
    parser.add_argument(
        "--summary-output",
        help="Optional path to write the same deterministic JSON summary printed to stdout",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = build_dividend_research_mart(
        snapshot_root=args.snapshot_root,
        research_root=args.research_root,
    )
    summary_json = _format_summary_json(summary)
    if args.summary_output:
        summary_output_path = Path(args.summary_output)
        summary_output_path.parent.mkdir(parents=True, exist_ok=True)
        summary_output_path.write_text(summary_json, encoding="utf-8")
    print(summary_json, end="")
    return 0


def _validate_research_root(snapshot_root: Path | str, research_root: Path | str) -> None:
    snapshot_path = _resolve_path(snapshot_root)
    research_path = _resolve_path(research_root)

    if (
        research_path == snapshot_path
        or _is_relative_to(research_path, snapshot_path)
        or _is_relative_to(snapshot_path, research_path)
    ):
        raise ValueError(UNSAFE_RESEARCH_ROOT_MESSAGE)

    parts = [part.lower() for part in research_path.parts]
    if _contains_curated_data_path(parts) or "canonical" in parts:
        raise ValueError(UNSAFE_RESEARCH_ROOT_MESSAGE)


def _summary_from_result(
    result: DividendResearchMartResult,
    snapshot_root: Path | str,
    research_root: Path | str,
) -> dict[str, Any]:
    metadata = result.metadata
    return {
        "snapshot_root": str(snapshot_root),
        "research_root": str(research_root),
        "input_record_count": result.input_record_count,
        "written_record_count": result.written_record_count,
        "invalid_partition_record_count": result.invalid_partition_record_count,
        "metadata_path": str(result.metadata_path),
        "event_anchor": metadata["event_anchor"],
        "symbol_count": metadata["symbol_count"],
        "year_count": metadata["year_count"],
        "symbols": metadata["symbols"],
        "years": metadata["years"],
    }


def _format_summary_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _resolve_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _contains_curated_data_path(parts: Sequence[str]) -> bool:
    return any(left == "data" and right == "curated" for left, right in zip(parts, parts[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
