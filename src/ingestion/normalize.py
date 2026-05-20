from __future__ import annotations

import pandas as pd

CANON_COLS = [
    "symbol",
    "ts_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "timeframe",
]


def _to_utc(ts: pd.Series) -> pd.Series:
    """Converts a timestamp series to UTC timezone."""
    out = pd.to_datetime(ts, utc=True, errors="coerce")
    if out.isna().any():
        raise ValueError(
            f"Some timestamps could not be parsed. Check the input data: {out.isna().sum()} invalid timestamps."
        )
    return out


def normalize_bars(df: pd.DataFrame, symbol: str, source: str, timeframe: str) -> pd.DataFrame:
    """Normalizes raw bar data from various sources into a canonical format.

    Args:
        df: Input DataFrame with raw bar data. Expected to have columns like timestamp, open, high, low, close, volume.
        source: The data source (e.g., "alpaca", "polygon") to help with any source-specific transformations.
        timeframe: The timeframe of the bars (e.g., "1Day", "1Min").

    Returns:
        A normalized DataFrame with standardized column names and formats.
    """
    if df.empty:
        return pd.DataFrame(columns=CANON_COLS + ["year", "date"])

    # Ensure required columns are present
    required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required_cols.issubset(df.columns):
        missing = required_cols - set(df.columns)
        raise ValueError(f"Missing required columns in input data: {missing}")

    out = df.copy()
    out["symbol"] = symbol
    out["source"] = source
    out["timeframe"] = timeframe

    # Convert timestamp to UTC datetime
    out["ts_utc"] = _to_utc(out["timestamp"])
    out = out.drop(columns=["timestamp"])
    # enfore numeric types for price/volume columns
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype(int)

    # drop obviously bad rows
    out = out.dropna(subset=["ts_utc", "open", "high", "low", "close"])

    # idempotent ordering + deterministic deduplication
    out = out.sort_values(["symbol", "ts_utc"])
    out = out.drop_duplicates(subset=["symbol", "ts_utc", "timeframe"], keep="last").reset_index(
        drop=True
    )

    # partition helpers
    out["year"] = out["ts_utc"].dt.year.astype(int)
    out["date"] = out["ts_utc"].dt.date.astype(str)

    # Keep only canonical columns
    out = out[CANON_COLS + ["year", "date"]]
    return out
