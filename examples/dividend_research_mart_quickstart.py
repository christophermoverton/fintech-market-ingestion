from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.corporate_actions_normalization import (  # noqa: E402
    normalize_corporate_action_payload,
)
from src.ingestion.corporate_actions_research_mart import (  # noqa: E402
    inspect_dividend_research_mart,
    read_dividend_research_mart,
    validate_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (  # noqa: E402
    write_dividend_corporate_actions,
)
from src.ingestion.dividend_event_window import (  # noqa: E402
    join_dividend_events_to_bars_result,
    write_dividend_event_window_output,
)

DEFAULT_QUICKSTART_OUTPUT_ROOT = Path("artifacts/examples/dividend_research_mart_quickstart")


def run_quickstart(
    output_root: Path | str = DEFAULT_QUICKSTART_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Run a CI-safe synthetic dividend research mart workflow."""
    root = Path(output_root)
    snapshot_root = root / "data" / "curated" / "corporate_actions" / "dividends"
    research_root = root / "data" / "research" / "corporate_actions" / "dividends"
    bars_path = root / "data" / "local" / "daily_bars.parquet"
    event_window_output_root = (
        root / "data" / "research" / "corporate_actions" / "dividend_event_windows" / "quickstart"
    )
    summary_path = root / "summary.json"

    # %% 1. Create synthetic dividend snapshot
    dividend_records = [
        normalize_corporate_action_payload(payload, source="synthetic_quickstart")
        for payload in _synthetic_dividend_payloads()
    ]
    snapshot_result = write_dividend_corporate_actions(
        dividend_records,
        root_dir=snapshot_root,
        ingest_start_date="2024-01-01",
        ingest_end_date="2024-12-31",
        source="synthetic_quickstart",
        action_types=["cash_dividend", "stock_dividend"],
    )

    # %% 2. Build derived research mart
    mart_result = write_dividend_research_mart_from_snapshot(
        snapshot_root=snapshot_root,
        research_root=research_root,
    )
    mart_frame = read_dividend_research_mart(research_root)

    # %% 3. Inspect and validate mart
    inspection = inspect_dividend_research_mart(research_root)
    validation = validate_dividend_research_mart(research_root)

    # %% 4. Create synthetic daily bars
    bars = _synthetic_daily_bars()
    bars_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(bars_path, index=False)

    # %% 5. Join dividend event windows
    event_window_result = join_dividend_events_to_bars_result(
        mart_frame,
        bars,
        pre_window_days=1,
        post_window_days=1,
        bar_timeframe="1D",
    )

    # %% 6. Write derived event-window output
    event_output = write_dividend_event_window_output(
        event_window_result,
        output_root=event_window_output_root,
        source_dividend_path=research_root,
        source_bar_path=bars_path,
        pre_window_days=1,
        post_window_days=1,
        bar_timeframe="1D",
    )

    # %% 7. Print deterministic summary
    summary = {
        "output_root": _path_text(root),
        "snapshot_root": _path_text(snapshot_root),
        "research_root": _path_text(research_root),
        "bars_path": _path_text(bars_path),
        "event_window_output_root": _path_text(event_window_output_root),
        "event_window_data_path": _path_text(event_output.data_path),
        "event_window_metadata_path": _path_text(event_output.metadata_path),
        "dividend_record_count": snapshot_result.written_record_count,
        "research_mart_row_count": mart_result.written_record_count,
        "validation_valid": validation.valid,
        "validation_error_count": len(validation.errors),
        "event_count": event_window_result.event_count,
        "bar_count": event_window_result.bar_count,
        "joined_row_count": event_window_result.joined_row_count,
        "symbols": inspection.symbols,
        "years": inspection.years,
        "preview_rows": _preview_rows(event_window_result.frame),
    }
    summary_json = _format_summary_json(summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(summary_json, encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a CI-safe notebook-style dividend research mart quickstart "
            "with synthetic local data."
        )
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_QUICKSTART_OUTPUT_ROOT),
        help="Output root for all generated quickstart artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_quickstart(args.output_root)
    print(_format_summary_json(summary), end="")
    return 0


def _synthetic_dividend_payloads() -> list[dict[str, Any]]:
    return [
        {
            "id": "quickstart-cash-dividend-aapl-2024-02",
            "symbol": "AAPL",
            "type": "cash_dividend",
            "process_date": "2024-02-15",
            "declaration_date": "2024-02-01",
            "ex_date": "2024-02-09",
            "record_date": "2024-02-12",
            "payable_date": "2024-02-29",
            "cash_amount": "0.24",
            "stock_amount": None,
            "currency": "USD",
        },
        {
            "id": "quickstart-stock-dividend-msft-2024-03",
            "symbol": "MSFT",
            "type": "stock_dividend",
            "process_date": "2024-03-15",
            "declaration_date": "2024-03-01",
            "ex_date": "2024-03-08",
            "record_date": "2024-03-11",
            "payable_date": "2024-03-29",
            "cash_amount": None,
            "stock_amount": "0.05",
            "currency": None,
        },
    ]


def _synthetic_daily_bars() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol, base_date, base_price in [
        ("AAPL", pd.Timestamp("2024-02-09"), 185.0),
        ("MSFT", pd.Timestamp("2024-03-08"), 410.0),
    ]:
        for offset in [-1, 0, 1]:
            bar_date = base_date + pd.Timedelta(days=offset)
            open_price = base_price + offset
            rows.append(
                {
                    "symbol": symbol,
                    "ts_utc": bar_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "open": open_price,
                    "high": open_price + 1.25,
                    "low": open_price - 1.0,
                    "close": open_price + 0.5,
                    "volume": 1_000_000 + (offset + 1) * 10_000,
                    "timeframe": "1D",
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "ts_utc"]).reset_index(drop=True)


def _preview_rows(frame: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    records = frame.head(limit).to_dict(orient="records")
    return [
        {str(key): _jsonable_value(value) for key, value in record.items()} for record in records
    ]


def _jsonable_value(value: Any) -> Any:
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _format_summary_json(summary: dict[str, Any]) -> str:
    return (
        json.dumps(
            summary,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    )


def _path_text(path: Path | str) -> str:
    return str(Path(path)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
