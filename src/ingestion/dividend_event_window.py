from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    read_dividend_research_mart,
)
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    read_dividend_corporate_actions,
)
from src.ingestion.dividend_research_semantics import DEFAULT_DIVIDEND_EVENT_ANCHOR

SUPPORTED_EVENT_DATE_FIELDS = frozenset({DEFAULT_DIVIDEND_EVENT_ANCHOR})
DEFAULT_DIVIDEND_EVENT_WINDOW_OUTPUT_ROOT = Path(
    "data/research/corporate_actions/dividend_event_windows"
)
DIVIDEND_EVENT_WINDOW_DATASET_FILENAME = "event_windows.parquet"
DIVIDEND_EVENT_WINDOW_METADATA_FILENAME = "metadata.json"
DIVIDEND_EVENT_WINDOW_DATASET_ROLE = "derived_research_event_window"
UNSAFE_EVENT_WINDOW_OUTPUT_MESSAGE = (
    "Dividend event-window output must be a derived research path and must not overlap "
    "with curated/canonical input paths or dividend research mart paths."
)
KNOWN_UNSAFE_DIVIDEND_ARTIFACT_ROOTS = (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
)
DIVIDEND_CORE_FIELDS = [
    "corporate_action_id",
    "symbol",
    "corporate_action_type",
    "ex_date",
    "declaration_date",
    "record_date",
    "payable_date",
    "process_date",
    "cash_amount",
    "stock_amount",
    "currency",
    "source_payload_hash",
]
BAR_CORE_FIELDS = ["open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class DividendEventWindowConfig:
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR
    pre_window_days: int = 5
    post_window_days: int = 5
    symbol: Optional[str] = None
    bar_timeframe: str = "1D"


@dataclass(frozen=True)
class DividendEventWindowResult:
    frame: pd.DataFrame
    event_count: int
    bar_count: int
    joined_row_count: int


@dataclass(frozen=True)
class DividendEventWindowOutputResult:
    root_dir: Path
    data_path: Path
    metadata_path: Path
    row_count: int
    metadata: dict[str, Any]


def join_dividend_events_to_bars(
    dividends: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    symbol: Optional[str] = None,
    bar_date_field: Optional[str] = None,
    bar_timeframe: str = "1D",
) -> pd.DataFrame:
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
    return result.frame


def join_dividend_events_to_bars_result(
    dividends: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    symbol: Optional[str] = None,
    bar_date_field: Optional[str] = None,
    bar_timeframe: str = "1D",
) -> DividendEventWindowResult:
    _validate_config(
        event_date_field=event_date_field,
        pre_window_days=pre_window_days,
        post_window_days=post_window_days,
    )
    if not isinstance(dividends, pd.DataFrame):
        raise ValueError("dividends must be a pandas DataFrame")
    if not isinstance(bars, pd.DataFrame):
        raise ValueError("bars must be a pandas DataFrame")

    dividends_df = _prepare_dividends(
        dividends,
        event_date_field=event_date_field,
        symbol=symbol,
    )
    bars_df = _prepare_bars(
        bars,
        bar_date_field=bar_date_field,
        symbol=symbol,
    )

    if dividends_df.empty or bars_df.empty:
        return DividendEventWindowResult(
            frame=_empty_output_frame(),
            event_count=len(dividends_df),
            bar_count=len(bars_df),
            joined_row_count=0,
        )

    merged = dividends_df.merge(
        bars_df,
        how="inner",
        left_on="event_symbol",
        right_on="bar_symbol",
    )
    if merged.empty:
        return DividendEventWindowResult(
            frame=_empty_output_frame(),
            event_count=len(dividends_df),
            bar_count=len(bars_df),
            joined_row_count=0,
        )

    merged["window_start"] = merged["event_date"] - pd.to_timedelta(pre_window_days, unit="D")
    merged["window_end"] = merged["event_date"] + pd.to_timedelta(post_window_days, unit="D")
    in_window = (merged["bar_date"] >= merged["window_start"]) & (
        merged["bar_date"] <= merged["window_end"]
    )
    joined = merged.loc[in_window].copy()
    if joined.empty:
        return DividendEventWindowResult(
            frame=_empty_output_frame(),
            event_count=len(dividends_df),
            bar_count=len(bars_df),
            joined_row_count=0,
        )

    joined["event_day_offset"] = (joined["bar_date"] - joined["event_date"]).dt.days.astype(int)
    joined["event_date_field"] = event_date_field
    joined["bar_timeframe"] = bar_timeframe
    ordered = joined.sort_values(
        by=[
            "event_symbol",
            "event_date",
            "event_corporate_action_id",
            "bar_date",
            "bar_ts",
        ],
        na_position="last",
    ).reset_index(drop=True)
    output = ordered[_output_columns()]
    return DividendEventWindowResult(
        frame=output,
        event_count=len(dividends_df),
        bar_count=len(bars_df),
        joined_row_count=len(output),
    )


def join_dividend_snapshot_to_bars(
    snapshot_root: Path | str,
    bars: pd.DataFrame,
    *,
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    symbol: Optional[str] = None,
    bar_date_field: Optional[str] = None,
    bar_timeframe: str = "1D",
) -> pd.DataFrame:
    dividends = read_dividend_corporate_actions(snapshot_root)
    return join_dividend_events_to_bars(
        dividends,
        bars,
        event_date_field=event_date_field,
        pre_window_days=pre_window_days,
        post_window_days=post_window_days,
        symbol=symbol,
        bar_date_field=bar_date_field,
        bar_timeframe=bar_timeframe,
    )


def join_dividend_research_mart_to_bars(
    research_root: Path | str,
    bars: pd.DataFrame,
    *,
    event_date_field: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    symbol: Optional[str] = None,
    bar_date_field: Optional[str] = None,
    bar_timeframe: str = "1D",
) -> pd.DataFrame:
    dividends = read_dividend_research_mart(research_root)
    return join_dividend_events_to_bars(
        dividends,
        bars,
        event_date_field=event_date_field,
        pre_window_days=pre_window_days,
        post_window_days=post_window_days,
        symbol=symbol,
        bar_date_field=bar_date_field,
        bar_timeframe=bar_timeframe,
    )


def write_dividend_event_window_output(
    result: DividendEventWindowResult | pd.DataFrame,
    output_root: Path | str = DEFAULT_DIVIDEND_EVENT_WINDOW_OUTPUT_ROOT,
    *,
    source_dividend_path: Optional[Path | str] = None,
    source_bar_path: Optional[Path | str] = None,
    event_anchor: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
    pre_window_days: int = 5,
    post_window_days: int = 5,
    bar_timeframe: str = "1D",
    symbol_filter: Optional[str] = None,
    event_count: Optional[int] = None,
    bar_count: Optional[int] = None,
) -> DividendEventWindowOutputResult:
    """Write derived dividend event-window rows with deterministic metadata."""
    if event_anchor != DEFAULT_DIVIDEND_EVENT_ANCHOR:
        raise ValueError(f"Unsupported event_anchor: {event_anchor}. Supported: ex_date")

    frame, resolved_event_count, resolved_bar_count, joined_row_count = _coerce_output_result(
        result=result,
        event_count=event_count,
        bar_count=bar_count,
    )
    root = Path(output_root)
    _validate_event_window_output_root(
        output_root=root,
        source_dividend_path=source_dividend_path,
        source_bar_path=source_bar_path,
    )

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    ordered = _order_event_window_output_frame(frame)
    data_path = root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME
    metadata_path = root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME
    ordered.to_parquet(data_path, index=False)

    metadata = {
        "dataset": "corporate_actions_dividend_event_windows",
        "dataset_role": DIVIDEND_EVENT_WINDOW_DATASET_ROLE,
        "path": _relative_path_if_possible(root),
        "format": "parquet",
        "data_file": DIVIDEND_EVENT_WINDOW_DATASET_FILENAME,
        "metadata_file": DIVIDEND_EVENT_WINDOW_METADATA_FILENAME,
        "source_dividend_path": _relative_path_if_possible(source_dividend_path),
        "source_bar_path": _relative_path_if_possible(source_bar_path),
        "event_anchor": event_anchor,
        "pre_window_days": pre_window_days,
        "post_window_days": post_window_days,
        "bar_timeframe": bar_timeframe,
        "symbol_filter": symbol_filter,
        "event_count": resolved_event_count,
        "bar_count": resolved_bar_count,
        "joined_row_count": joined_row_count,
        "row_count": len(ordered),
        "schema_fields": ordered.columns.tolist(),
        "created_by": "write_dividend_event_window_output",
    }
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )

    return DividendEventWindowOutputResult(
        root_dir=root,
        data_path=data_path,
        metadata_path=metadata_path,
        row_count=len(ordered),
        metadata=metadata,
    )


def read_dividend_event_window_output(
    output_root: Path | str = DEFAULT_DIVIDEND_EVENT_WINDOW_OUTPUT_ROOT,
) -> pd.DataFrame:
    root = Path(output_root)
    if not root.exists():
        raise FileNotFoundError(f"Dividend event-window output root does not exist: {root}")

    data_path = root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME
    if not data_path.exists():
        raise FileNotFoundError(f"Dividend event-window data file does not exist: {data_path}")

    return _order_event_window_output_frame(pd.read_parquet(data_path))


def _validate_config(event_date_field: str, pre_window_days: int, post_window_days: int) -> None:
    if event_date_field not in SUPPORTED_EVENT_DATE_FIELDS:
        supported = ", ".join(sorted(SUPPORTED_EVENT_DATE_FIELDS))
        raise ValueError(
            f"Unsupported event_date_field: {event_date_field}. Supported: {supported}"
        )
    if pre_window_days < 0:
        raise ValueError("pre_window_days must be >= 0")
    if post_window_days < 0:
        raise ValueError("post_window_days must be >= 0")


def _prepare_dividends(
    dividends: pd.DataFrame,
    *,
    event_date_field: str,
    symbol: Optional[str],
) -> pd.DataFrame:
    if "symbol" not in dividends.columns:
        raise ValueError("dividends is missing required column: symbol")
    if event_date_field not in dividends.columns:
        raise ValueError(f"dividends is missing required column: {event_date_field}")

    prepared = dividends.copy(deep=True)
    prepared["symbol"] = prepared["symbol"].map(_normalize_symbol)
    if prepared["symbol"].isna().any():
        raise ValueError("dividends contains missing symbol values")

    event_dates = _parse_date_series(prepared[event_date_field], field_name=event_date_field)
    prepared["event_date"] = event_dates
    prepared = prepared.dropna(subset=["event_date"])
    if prepared.empty:
        return _empty_dividends_frame()

    if symbol is not None:
        requested_symbol = _normalize_symbol(symbol)
        prepared = prepared.loc[prepared["symbol"] == requested_symbol].copy()

    renamed = pd.DataFrame()
    renamed["event_corporate_action_id"] = prepared.get("corporate_action_id")
    renamed["event_symbol"] = prepared["symbol"]
    renamed["event_corporate_action_type"] = prepared.get("corporate_action_type")
    renamed["event_ex_date"] = prepared.get("ex_date")
    renamed["event_declaration_date"] = prepared.get("declaration_date")
    renamed["event_record_date"] = prepared.get("record_date")
    renamed["event_payable_date"] = prepared.get("payable_date")
    renamed["event_process_date"] = prepared.get("process_date")
    renamed["event_cash_amount"] = prepared.get("cash_amount")
    renamed["event_stock_amount"] = prepared.get("stock_amount")
    renamed["event_currency"] = prepared.get("currency")
    renamed["event_source_payload_hash"] = prepared.get("source_payload_hash")
    renamed["event_date"] = prepared["event_date"]
    return renamed


def _prepare_bars(
    bars: pd.DataFrame,
    *,
    bar_date_field: Optional[str],
    symbol: Optional[str],
) -> pd.DataFrame:
    if "symbol" not in bars.columns:
        raise ValueError("bars is missing required column: symbol")
    resolved_date_field = _resolve_bar_date_field(bars, bar_date_field)

    prepared = bars.copy(deep=True)
    prepared["symbol"] = prepared["symbol"].map(_normalize_symbol)
    if prepared["symbol"].isna().any():
        raise ValueError("bars contains missing symbol values")

    parsed_bar_ts = _parse_datetime_series(
        prepared[resolved_date_field], field_name=resolved_date_field
    )
    prepared["bar_ts"] = parsed_bar_ts
    prepared["bar_date"] = parsed_bar_ts.dt.tz_localize(None).dt.normalize()

    if symbol is not None:
        requested_symbol = _normalize_symbol(symbol)
        prepared = prepared.loc[prepared["symbol"] == requested_symbol].copy()

    renamed = pd.DataFrame()
    renamed["bar_symbol"] = prepared["symbol"]
    renamed["bar_ts"] = prepared["bar_ts"]
    renamed["bar_date"] = prepared["bar_date"]
    for field in BAR_CORE_FIELDS:
        renamed[f"bar_{field}"] = prepared[field] if field in prepared.columns else pd.NA
    return renamed


def _resolve_bar_date_field(bars: pd.DataFrame, bar_date_field: Optional[str]) -> str:
    if bar_date_field is not None:
        if bar_date_field not in bars.columns:
            raise ValueError(f"bars is missing required column: {bar_date_field}")
        return bar_date_field

    for candidate in ["ts_utc", "timestamp", "date", "ts"]:
        if candidate in bars.columns:
            return candidate
    raise ValueError(
        "bars is missing a date/timestamp column. Provide bar_date_field or include one of: "
        "ts_utc, timestamp, date, ts"
    )


def _parse_date_series(series: pd.Series, *, field_name: str) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601")
    if parsed.isna().any():
        raise ValueError(f"Invalid date value(s) in field {field_name}: {int(parsed.isna().sum())}")
    return parsed.dt.tz_localize(None).dt.normalize()


def _parse_datetime_series(series: pd.Series, *, field_name: str) -> pd.Series:
    parsed = pd.to_datetime(series, utc=True, errors="coerce", format="ISO8601")
    if parsed.isna().any():
        raise ValueError(
            f"Invalid date/timestamp value(s) in field {field_name}: {int(parsed.isna().sum())}"
        )
    return parsed


def _normalize_symbol(value: object) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _output_columns() -> list[str]:
    return [
        "event_corporate_action_id",
        "event_symbol",
        "event_corporate_action_type",
        "event_ex_date",
        "event_declaration_date",
        "event_record_date",
        "event_payable_date",
        "event_process_date",
        "event_cash_amount",
        "event_stock_amount",
        "event_currency",
        "event_source_payload_hash",
        "event_date_field",
        "event_date",
        "event_day_offset",
        "bar_timeframe",
        "bar_symbol",
        "bar_ts",
        "bar_date",
        "bar_open",
        "bar_high",
        "bar_low",
        "bar_close",
        "bar_volume",
    ]


def _empty_output_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_output_columns())


def _empty_dividends_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        columns=[
            "event_corporate_action_id",
            "event_symbol",
            "event_corporate_action_type",
            "event_ex_date",
            "event_declaration_date",
            "event_record_date",
            "event_payable_date",
            "event_process_date",
            "event_cash_amount",
            "event_stock_amount",
            "event_currency",
            "event_source_payload_hash",
            "event_date",
        ]
    )
    return frame


def _coerce_output_result(
    *,
    result: DividendEventWindowResult | pd.DataFrame,
    event_count: Optional[int],
    bar_count: Optional[int],
) -> tuple[pd.DataFrame, Optional[int], Optional[int], int]:
    if isinstance(result, DividendEventWindowResult):
        return (
            result.frame.copy(deep=True),
            result.event_count,
            result.bar_count,
            result.joined_row_count,
        )
    if isinstance(result, pd.DataFrame):
        return result.copy(deep=True), event_count, bar_count, len(result)
    raise ValueError("result must be a DividendEventWindowResult or pandas DataFrame")


def _order_event_window_output_frame(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.copy(deep=True)
    order_columns = [
        column
        for column in [
            "event_symbol",
            "event_date",
            "event_corporate_action_id",
            "bar_date",
            "bar_ts",
        ]
        if column in ordered.columns
    ]
    if order_columns:
        ordered = ordered.sort_values(by=order_columns, na_position="last")
    return ordered.reset_index(drop=True)


def _validate_event_window_output_root(
    *,
    output_root: Path | str,
    source_dividend_path: Optional[Path | str],
    source_bar_path: Optional[Path | str],
) -> None:
    resolved_output = _resolve_path(output_root)
    parts = [part.lower() for part in resolved_output.parts]
    if _contains_curated_data_path(parts) or "canonical" in parts:
        raise ValueError(UNSAFE_EVENT_WINDOW_OUTPUT_MESSAGE)

    for known_root in KNOWN_UNSAFE_DIVIDEND_ARTIFACT_ROOTS:
        if _paths_overlap(resolved_output, _resolve_path(known_root)):
            raise ValueError(UNSAFE_EVENT_WINDOW_OUTPUT_MESSAGE)

    for input_path in [source_dividend_path, source_bar_path]:
        if input_path is not None and _paths_overlap(resolved_output, _resolve_path(input_path)):
            raise ValueError(UNSAFE_EVENT_WINDOW_OUTPUT_MESSAGE)


def _relative_path_if_possible(path: Optional[Path | str]) -> Optional[str]:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate).replace("\\", "/")

    cwd = Path.cwd()
    try:
        return str(candidate.relative_to(cwd)).replace("\\", "/")
    except ValueError:
        return str(candidate).replace("\\", "/")


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


def _contains_curated_data_path(parts: list[str]) -> bool:
    return any(left == "data" and right == "curated" for left, right in zip(parts, parts[1:]))
