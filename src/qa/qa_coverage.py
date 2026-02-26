from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import pandas as pd
import duckdb 

COVERAGE_COLUMNS = [
    "run_id",
    "dataset_name",
    "bar_interval",
    "calendar_mode",
    "start_ts",
    "end_ts",
    "symbol",
    "min_ts",
    "max_ts",
    "rows_total",
    "expected_days",
    "observed_days",
    "missing_day_count",
    "coverage_days_pct",
    "notes",
]

def _to_date_utc(ts: str | datetime) -> date:
    """
    Convert ISO8601 or datetime to a UTC date.
    Handles naive and tz-aware datetimes safely.
    """
    if isinstance(ts, datetime):
        dt = pd.to_datetime(ts, utc=True)
    else:
        dt = pd.to_datetime(ts, utc=True)

    return dt.date()

def generate_expected_days(
    start_ts: str | datetime,
    end_ts: str | datetime,
    calendar_mode: str,
) -> tuple[list[date], str]:
    """
    Returns (expected_days_listt, notes).
    expected days arre inclusive of start_date and end_date.
    """
    start_d = _to_date_utc(start_ts)
    end_d = _to_date_utc(end_ts)

    if end_d < start_d:
        return ([],"end_date < start_date")
    
    mode = calendar_mode.upper().strip()
    notes = ""
    
    if mode in ("ALL_DAYS", "ALL"):
        days = []
        d = start_d
        while d <= end_d:
            days.append(d)
            d += timedelta(days=1)
        return (days, notes)
    
    # Exchange calendar mode (e.g., XNYS)
    try: 
        import pandas_market_calendars as mcal
        cal = mcal.get_calendar(mode)
        #sessions in_range expects dates; inclusive range
        sched = cal.schedule(start_date=start_d, end_date=end_d)
        #schedule index is session dates
        days = [d.date() if hasattr(d, "date") else d for d in sched.index]
        return (days, notes)
    except Exception as e:
        #graceful fallback
        fallback_days,_ = generate_expected_days(start_ts, end_ts, "WEEKDAY")
        notes = f"calendar_mode={mode} unavailable; fell back to WEEKDAY ({type(e).__name__})"
        return (fallback_days, notes)
        
def compute_coverage_by_symbol(
    con: duckdb.DuckDBPyConnection,
    parquet_glob: str,
    run_id: str,
    dataset_name: str,
    bar_interval: str,
    start_ts: str,
    end_ts: str,
    calendar_mode: str = "XYNS",
    symbols_expected: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Compute per-symbol coverage from Parquet directly via DuckDB.

    Observed days are distinct DATE(ts_utc) per symbol within [start_ts, end_ts].
    """
    expected_days_list, cal_notes = generate_expected_days(start_ts, end_ts, calendar_mode)
    expected_days = len(expected_days_list)
    print("start_ts:", start_ts)
    print("end_ts:", end_ts)
    print("parquet_glob:", parquet_glob)
    
    #Core aggregation from parquet
    #Note: we filter by slice bounds to ensure partial window works.
    agg = con.execute(
        f"""
            WITH base AS (
            SELECT
                symbol,
                ts_utc,
                CAST(ts_utc AS DATE) AS d
            FROM read_parquet('{parquet_glob}')
            WHERE CAST(ts_utc AS DATE) >= CAST(? AS DATE)
                AND CAST(ts_utc AS DATE) <= CAST(? AS DATE)
            ),
            per_symbol AS (
            SELECT
                symbol,
                MIN(ts_utc) AS min_ts,
                MAX(ts_utc) AS max_ts,
                COUNT(*) AS rows_total,
                COUNT(DISTINCT d) AS observed_days
            FROM base
            GROUP BY symbol
            )
            SELECT * FROM per_symbol
            ORDER BY symbol;
        """,
        [start_ts, end_ts]
    ).df()
  
    #Ensure expected symbol universe coverage, including symbols with no rows
    if symbols_expected is not None:
        expected_df = pd.DataFrame({"symbol": symbols_expected})
        out = expected_df.merge(agg, on="symbol", how="left")
    else:
        out = agg.copy()
        if "symbol" not in out.columns:
            out = pd.DataFrame({"symbol": []})
    
    #Fill nulls for no-row symbols
    out["rows_total"] = out["rows_total"].fillna(0).astype("int64")
    out["observed_days"] = out["observed_days"].fillna(0).astype("int64")
    #min_ts/max_ts can remain NaT for empty
    #missing days logic
    out["expected_days"] = expected_days
    out["missing_day_count"] = (expected_days - out["observed_days"]).clip(lower=0).astype("int64")
    out["coverage_days_pct"] = out.apply(
        lambda r: (r["observed_days"] / r["expected_days"] ) if r["expected_days"] > 0 else None, 
        axis=1
    )
    
    #Notes per-row: flag empty symbols, and include calendar fallback note (once)
    
    def _row_note(r) -> str:
        parts = []
        if r["rows_total"] == 0:
            parts.append( "NO_ROWS")
        if cal_notes:
            parts.append(cal_notes)
        return "; ".join(parts)
    
    out["notes"] = out.apply(_row_note, axis=1)
    
    #Add metadata columns
    out.insert(0, "end_ts", end_ts)
    out.insert(0, "start_ts", start_ts)
    out.insert(0, "calendar_mode", calendar_mode)
    out.insert(0, "bar_interval", bar_interval)
    out.insert(0, "dataset_name", dataset_name)
    out.insert(0, "run_id", run_id)
    
    #Column order + types
    out = out.rename(columns={"symbol": "symbol"})
    out = out[COVERAGE_COLUMNS]
    
    return out

def write_coverage_csv(df: pd.DataFrame, output_path: str) -> None:
    df.to_csv(output_path, index=False)