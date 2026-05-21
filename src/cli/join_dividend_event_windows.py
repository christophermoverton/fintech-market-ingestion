from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional, Sequence

import pandas as pd

from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    read_dividend_research_mart,
)
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    read_dividend_corporate_actions,
)
from src.ingestion.dividend_event_window import (
    join_dividend_events_to_bars_result,
    write_dividend_event_window_output,
)
from src.ingestion.dividend_research_semantics import DEFAULT_DIVIDEND_EVENT_ANCHOR

SUPPORTED_DIVIDEND_SOURCES = frozenset({"snapshot", "research-mart"})
SUPPORTED_DATA_FORMATS = frozenset({"csv", "parquet"})
UNSAFE_OUTPUT_PATH_MESSAGE = (
    "Dividend event-window output must be a derived research path and must not overlap "
    "with curated/canonical paths or input artifact roots, including bar, snapshot, and "
    "research-mart paths."
)


def join_dividend_event_windows(
    *,
    dividend_source: str,
    bars_path: Path | str,
    snapshot_root: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    research_root: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    bars_format: Optional[str] = None,
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    symbol: Optional[str] = None,
    bar_date_field: Optional[str] = None,
    bar_timeframe: str = "1D",
    output_path: Optional[Path | str] = None,
    output_root: Optional[Path | str] = None,
    output_format: Optional[str] = None,
) -> dict[str, Any]:
    """Join local dividend events to local bars with event-window semantics."""
    _validate_dividend_source(dividend_source)
    if output_path is not None and output_root is not None:
        raise ValueError("--output-path and --output-root cannot be used together")
    if output_format is not None and output_path is None:
        raise ValueError("--output-format requires --output-path")
    if output_path is not None:
        validate_output_path(
            output_path=output_path,
            bars_path=bars_path,
            snapshot_root=snapshot_root,
            research_root=research_root,
        )
    if output_root is not None:
        validate_output_path(
            output_path=output_root,
            bars_path=bars_path,
            snapshot_root=snapshot_root,
            research_root=research_root,
        )

    dividends = _load_dividends(
        dividend_source=dividend_source,
        snapshot_root=snapshot_root,
        research_root=research_root,
    )
    bars = load_bars(bars_path, bars_format=bars_format)
    result = join_dividend_events_to_bars_result(
        dividends,
        bars,
        event_date_field=event_date_field,
        pre_window_days=pre_window_days,
        post_window_days=post_window_days,
        symbol=symbol,
        bar_date_field=bar_date_field,
        bar_timeframe=bar_timeframe,
    )

    resolved_output_format = None
    output_result = None
    if output_path is not None:
        resolved_output_format = infer_output_format(output_path, output_format)
        write_joined_output(result.frame, output_path, output_format=resolved_output_format)
    if output_root is not None:
        output_result = write_dividend_event_window_output(
            result,
            output_root=output_root,
            source_dividend_path=_source_dividend_path(
                dividend_source=dividend_source,
                snapshot_root=snapshot_root,
                research_root=research_root,
            ),
            source_bar_path=bars_path,
            event_anchor=event_date_field,
            pre_window_days=pre_window_days,
            post_window_days=post_window_days,
            bar_timeframe=bar_timeframe,
            symbol_filter=symbol,
        )
        resolved_output_format = "parquet"

    summary: dict[str, Any] = {
        "dividend_source": dividend_source,
        "snapshot_root": str(snapshot_root) if dividend_source == "snapshot" else None,
        "research_root": str(research_root) if dividend_source == "research-mart" else None,
        "bars_path": str(bars_path),
        "output_path": str(output_path) if output_path is not None else None,
        "output_root": str(output_root) if output_root is not None else None,
        "output_format": resolved_output_format,
        "metadata_path": str(output_result.metadata_path) if output_result is not None else None,
        "data_path": str(output_result.data_path) if output_result is not None else None,
        "dataset_role": output_result.metadata["dataset_role"]
        if output_result is not None
        else None,
        "event_date_field": event_date_field,
        "pre_window_days": pre_window_days,
        "post_window_days": post_window_days,
        "symbol": symbol,
        "bar_date_field": bar_date_field,
        "bar_timeframe": bar_timeframe,
        "event_count": result.event_count,
        "bar_count": result.bar_count,
        "joined_row_count": result.joined_row_count,
    }
    return summary


def load_bars(path: Path | str, bars_format: Optional[str] = None) -> pd.DataFrame:
    resolved_format = infer_input_format(path, bars_format)
    if resolved_format == "parquet":
        return pd.read_parquet(path)
    if resolved_format == "csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported bars format: {resolved_format}")


def infer_input_format(path: Path | str, explicit_format: Optional[str] = None) -> str:
    return _resolve_format(path, explicit_format, label="bars")


def infer_output_format(path: Path | str, explicit_format: Optional[str] = None) -> str:
    return _resolve_format(path, explicit_format, label="output")


def write_joined_output(
    frame: pd.DataFrame,
    output_path: Path | str,
    *,
    output_format: str,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "parquet":
        frame.to_parquet(path, index=False)
        return
    if output_format == "csv":
        frame.to_csv(path, index=False)
        return
    raise ValueError(f"Unsupported output format: {output_format}")


def validate_output_path(
    *,
    output_path: Path | str,
    bars_path: Path | str,
    snapshot_root: Optional[Path | str] = None,
    research_root: Optional[Path | str] = None,
) -> None:
    resolved_output_path = _resolve_path(output_path)
    parts = [part.lower() for part in resolved_output_path.parts]
    if _contains_curated_data_path(parts) or "canonical" in parts:
        raise ValueError(UNSAFE_OUTPUT_PATH_MESSAGE)

    for input_path in [bars_path, snapshot_root, research_root]:
        if input_path is not None and _paths_overlap(
            resolved_output_path, _resolve_path(input_path)
        ):
            raise ValueError(UNSAFE_OUTPUT_PATH_MESSAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Join local dividend events to local bars using event-window semantics."
    )
    parser.add_argument(
        "--dividend-source",
        choices=sorted(SUPPORTED_DIVIDEND_SOURCES),
        required=True,
        help="Dividend source to join: curated snapshot or derived research mart",
    )
    parser.add_argument(
        "--snapshot-root",
        default=str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT),
        help="Input root for the curated dividend corporate-actions snapshot",
    )
    parser.add_argument(
        "--research-root",
        default=str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT),
        help="Input root for the derived dividend research mart",
    )
    parser.add_argument("--bars-path", required=True, help="Local bars input path")
    parser.add_argument(
        "--bars-format",
        choices=sorted(SUPPORTED_DATA_FORMATS),
        help="Optional local bars input format; inferred from suffix when omitted",
    )
    parser.add_argument(
        "--event-date-field",
        default=DEFAULT_DIVIDEND_EVENT_ANCHOR,
        help="Dividend event date field; currently supports ex_date",
    )
    parser.add_argument("--pre-window-days", type=int, default=5)
    parser.add_argument("--post-window-days", type=int, default=5)
    parser.add_argument("--symbol", help="Optional symbol filter applied to events and bars")
    parser.add_argument("--bar-date-field", help="Optional bars date/timestamp field")
    parser.add_argument("--bar-timeframe", default="1D")
    parser.add_argument("--output-path", help="Optional derived output path for joined rows")
    parser.add_argument(
        "--output-root",
        help=(
            "Optional derived event-window output root for event_windows.parquet and metadata.json"
        ),
    )
    parser.add_argument(
        "--output-format",
        choices=sorted(SUPPORTED_DATA_FORMATS),
        help="Optional output format; inferred from suffix when omitted",
    )
    parser.add_argument(
        "--summary-output",
        help="Optional path to write the same deterministic JSON summary printed to stdout",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    summary = join_dividend_event_windows(
        dividend_source=args.dividend_source,
        snapshot_root=args.snapshot_root,
        research_root=args.research_root,
        bars_path=args.bars_path,
        bars_format=args.bars_format,
        event_date_field=args.event_date_field,
        pre_window_days=args.pre_window_days,
        post_window_days=args.post_window_days,
        symbol=args.symbol,
        bar_date_field=args.bar_date_field,
        bar_timeframe=args.bar_timeframe,
        output_path=args.output_path,
        output_root=args.output_root,
        output_format=args.output_format,
    )
    summary_json = format_summary_json(summary)
    if args.summary_output:
        summary_output_path = Path(args.summary_output)
        summary_output_path.parent.mkdir(parents=True, exist_ok=True)
        summary_output_path.write_text(summary_json, encoding="utf-8")
    print(summary_json, end="")
    return 0


def format_summary_json(summary: dict[str, Any]) -> str:
    return json.dumps(summary, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _load_dividends(
    *,
    dividend_source: str,
    snapshot_root: Path | str,
    research_root: Path | str,
) -> pd.DataFrame:
    if dividend_source == "snapshot":
        return read_dividend_corporate_actions(snapshot_root)
    if dividend_source == "research-mart":
        return read_dividend_research_mart(research_root)
    raise ValueError(f"Unsupported dividend_source: {dividend_source}")


def _source_dividend_path(
    *,
    dividend_source: str,
    snapshot_root: Path | str,
    research_root: Path | str,
) -> Path | str:
    if dividend_source == "snapshot":
        return snapshot_root
    if dividend_source == "research-mart":
        return research_root
    raise ValueError(f"Unsupported dividend_source: {dividend_source}")


def _validate_dividend_source(dividend_source: str) -> None:
    if dividend_source not in SUPPORTED_DIVIDEND_SOURCES:
        supported = ", ".join(sorted(SUPPORTED_DIVIDEND_SOURCES))
        raise ValueError(f"Unsupported dividend_source: {dividend_source}. Supported: {supported}")


def _resolve_format(path: Path | str, explicit_format: Optional[str], *, label: str) -> str:
    if explicit_format is not None:
        normalized = explicit_format.strip().lower()
        if normalized in SUPPORTED_DATA_FORMATS:
            return normalized
        supported = ", ".join(sorted(SUPPORTED_DATA_FORMATS))
        raise ValueError(f"Unsupported {label} format: {explicit_format}. Supported: {supported}")

    suffix = Path(path).suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return "parquet"
    if suffix == ".csv":
        return "csv"
    raise ValueError(
        f"Could not infer {label} format from suffix {suffix!r}. "
        "Use .parquet, .pq, .csv, or pass an explicit format."
    )


def _resolve_path(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or _is_relative_to(left, right) or _is_relative_to(right, left)


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
