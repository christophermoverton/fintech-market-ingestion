from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from src.ingestion.alpaca_corporate_actions_client import (
    SUPPORTED_DIVIDEND_ACTION_TYPES,
    AlpacaCorporateActionsClient,
)
from src.ingestion.corporate_actions_normalization import normalize_corporate_action_records
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    DividendCorporateActionsWriteResult,
    write_dividend_corporate_actions,
)

DEFAULT_LIMIT = 1000
UNSAFE_OUTPUT_PATH_PARTS = frozenset({"bars", "bars_daily", "bars_1m", "trades", "quotes"})


@dataclass(frozen=True)
class DividendCorporateActionsIngestionResult:
    requested_symbols: list[str]
    start: str
    end: str
    action_types: list[str]
    fetched_record_count: int
    normalized_record_count: int
    written_record_count: int
    duplicate_record_count: int
    data_path: Path
    metadata_path: Path
    storage: DividendCorporateActionsWriteResult

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_symbols": self.requested_symbols,
            "start": self.start,
            "end": self.end,
            "action_types": self.action_types,
            "fetched_record_count": self.fetched_record_count,
            "normalized_record_count": self.normalized_record_count,
            "written_record_count": self.written_record_count,
            "duplicate_record_count": self.duplicate_record_count,
            "data_path": str(self.data_path),
            "metadata_path": str(self.metadata_path),
        }


def ingest_dividend_corporate_actions(
    symbols: Sequence[str],
    start: str,
    end: str,
    types: Optional[Sequence[str]] = None,
    output_root: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    sort: str = "asc",
    limit: int = DEFAULT_LIMIT,
    client: Optional[AlpacaCorporateActionsClient] = None,
) -> DividendCorporateActionsIngestionResult:
    """Fetch, normalize, and persist Alpaca dividend corporate actions."""
    requested_symbols = _normalize_symbols(symbols)
    requested_types = list(types) if types is not None else sorted(SUPPORTED_DIVIDEND_ACTION_TYPES)
    _validate_symbols(requested_symbols)
    _validate_required_value(start, "start")
    _validate_required_value(end, "end")
    _validate_action_types(requested_types)
    _validate_output_root(output_root)

    ca_client = client or AlpacaCorporateActionsClient.from_env()
    fetched_records = ca_client.fetch_corporate_actions(
        symbols=requested_symbols,
        start=start,
        end=end,
        types=requested_types,
        limit=limit,
        sort=sort,
    )
    normalized_records = normalize_corporate_action_records(fetched_records)
    storage_result = write_dividend_corporate_actions(
        normalized_records,
        root_dir=output_root,
        ingest_start_date=start,
        ingest_end_date=end,
        source="alpaca",
        action_types=requested_types,
    )

    return DividendCorporateActionsIngestionResult(
        requested_symbols=requested_symbols,
        start=start,
        end=end,
        action_types=requested_types,
        fetched_record_count=len(fetched_records),
        normalized_record_count=len(normalized_records),
        written_record_count=storage_result.written_record_count,
        duplicate_record_count=storage_result.duplicate_record_count,
        data_path=storage_result.data_path,
        metadata_path=storage_result.metadata_path,
        storage=storage_result,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest Alpaca dividend corporate actions into the curated corporate-actions dataset."
    )
    parser.add_argument("--symbols", nargs="+", required=True, help="One or more ticker symbols")
    parser.add_argument("--start", required=True, help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument(
        "--types",
        nargs="+",
        default=sorted(SUPPORTED_DIVIDEND_ACTION_TYPES),
        choices=sorted(SUPPORTED_DIVIDEND_ACTION_TYPES),
        help="Dividend corporate action types to request",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT),
        help="Output root for the curated dividends corporate-actions dataset",
    )
    parser.add_argument("--sort", default="asc", help="Alpaca sort order, asc or desc")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Alpaca page size limit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    result = ingest_dividend_corporate_actions(
        symbols=args.symbols,
        start=args.start,
        end=args.end,
        types=args.types,
        output_root=args.output_root,
        sort=args.sort,
        limit=args.limit,
    )
    print(json.dumps(result.as_dict(), sort_keys=True, indent=2))
    return 0


def _validate_output_root(output_root: Path | str) -> None:
    parts = {part.lower() for part in Path(output_root).parts}
    unsafe = sorted(parts & UNSAFE_OUTPUT_PATH_PARTS)
    if unsafe:
        raise ValueError(
            "Corporate actions output root must not point into bars/trades/quotes paths: "
            f"{', '.join(unsafe)}"
        )


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    return [symbol.strip() for symbol in symbols if symbol and symbol.strip()]


def _validate_symbols(symbols: Sequence[str]) -> None:
    if not symbols:
        raise ValueError("At least one symbol is required for dividend corporate actions ingestion")


def _validate_required_value(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} is required")


def _validate_action_types(types: Sequence[str]) -> None:
    unsupported = sorted(set(types) - SUPPORTED_DIVIDEND_ACTION_TYPES)
    if unsupported:
        supported = ", ".join(sorted(SUPPORTED_DIVIDEND_ACTION_TYPES))
        raise ValueError(
            f"Unsupported dividend corporate action type(s): {unsupported}. Supported: {supported}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
