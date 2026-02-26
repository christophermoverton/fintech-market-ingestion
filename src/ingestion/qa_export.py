from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import duckdb
import pandas as pd

CURATED_PATHS = {
    "1D" : "data/curated/bars_daily/**/*.parquet",
    "1Min" : "data/curated/bars_1m/**/*.parquet",
}

CANONICAL_COLS = [
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

@dataclass(frozen=True)
class Thresholds:
    min_coverage_pct: float = 0.995
    max_duplicate_rows: int = 0
    max_duplicate_keys: int = 0   # NEW: strict integrity threshold
    max_ohlc_violations: int = 0
    max_gap_count_per_symbol: int = 0
    
@dataclass(frozen=True)
class ExportConfig:
    dataset_name: str
    bar_interval: str
    parquet_glob: str
    start_ts: Optional[pd.Timestamp] = None
    end_ts: Optional[pd.Timestamp] = None
    symbols_expected: Optional[List[str]] = None
    calendar: str = "XNYS" # calendar is (pandas_market_calendars), fallback to weekday
    thresholds: Thresholds = Thresholds()
    sample_n:  int = 0 # reserved
    out_root: Path = Path("artifacts/qa")
    run_id: Optional[str] = None # if None -> generated deterministically from config window
    
# -----------------------
# Utilities
# -----------------------

def _connect_duckdb() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    con.execute("PRAGMA threads=4;")
    con.execute("PRAGMA enable_object_cache=true;")
    return con


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _read_symbols_file(path: Optional[str]) -> Optional[List[str]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")
    out: List[str] = []
    for line in p.read_text().splitlines():
        sym = line.strip().upper()
        if sym and not sym.startswith("#"):
            out.append(sym)
    return out


def _format_ts(ts: Optional[pd.Timestamp]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()


def _make_run_id(cfg: ExportConfig) -> str:
    # Deterministic run id based on dataset + window + calendar
    # Example: qa_bars_1m_2025-11-01_2025-12-01_XNYS
    s = cfg.start_ts.normalize().date().isoformat() if cfg.start_ts is not None else "ALL"
    e = cfg.end_ts.normalize().date().isoformat() if cfg.end_ts is not None else "ALL"
    return f"qa_{cfg.dataset_name}_{cfg.bar_interval}_{s}_{e}_{cfg.calendar}"


def _where_time_filter(cfg: ExportConfig) -> str:
    # DuckDB will compare timestamps correctly if ts_utc is timestamp type
    clauses = []
    if cfg.start_ts is not None:
        clauses.append(f"ts_utc >= TIMESTAMP '{cfg.start_ts.tz_convert('UTC').strftime('%Y-%m-%d %H:%M:%S')}'")
    if cfg.end_ts is not None:
        clauses.append(f"ts_utc < TIMESTAMP '{cfg.end_ts.tz_convert('UTC').strftime('%Y-%m-%d %H:%M:%S')}'")
    return ("WHERE " + " AND ".join(clauses)) if clauses else ""


# -----------------------
# Calendar expected bars
# -----------------------

def _try_get_calendar_sessions(start_ts: pd.Timestamp, end_ts: pd.Timestamp, calendar: str) -> Optional[pd.DataFrame]:
    """
    Returns a schedule DataFrame with market_open/market_close in UTC if pandas_market_calendars exists.
    """
    try:
        import pandas_market_calendars as mcal
    except Exception:
        return None

    cal = mcal.get_calendar(calendar)
    # schedule expects dates (not timestamps). Use inclusive date window.
    start_date = start_ts.tz_convert("UTC").date()
    end_date = (end_ts.tz_convert("UTC") - pd.Timedelta(seconds=1)).date()
    sched = cal.schedule(start_date=start_date, end_date=end_date)
    return sched


def expected_bars_daily(cfg: ExportConfig, symbols_present: List[str]) -> Dict[str, int]:
    """
    Expected daily bars = number of sessions in window (calendar-aware if available).
    """
    if cfg.start_ts is None or cfg.end_ts is None:
        # If no window, expected bars isn't meaningful (treat as observed)
        return {s: 0 for s in symbols_present}

    sched = _try_get_calendar_sessions(cfg.start_ts, cfg.end_ts, cfg.calendar)
    if sched is not None:
        expected = int(len(sched))
    else:
        # fallback: business days approximation
        expected = int(len(pd.bdate_range(cfg.start_ts.normalize(), cfg.end_ts.normalize() - pd.Timedelta(days=1))))

    return {s: expected for s in symbols_present}


def expected_bars_1min(cfg: ExportConfig, symbols_present: List[str]) -> Dict[str, int]:
    """
    Expected 1-min bars = sum over sessions of minutes between open/close (calendar-aware).
    Falls back to 390 * business_days if no calendar package installed.
    """
    if cfg.start_ts is None or cfg.end_ts is None:
        return {s: 0 for s in symbols_present}

    sched = _try_get_calendar_sessions(cfg.start_ts, cfg.end_ts, cfg.calendar)
    if sched is not None and not sched.empty:
        # sched columns typically include market_open and market_close in UTC
        minutes = ((sched["market_close"] - sched["market_open"]).dt.total_seconds() // 60).astype(int)
        expected = int(minutes.sum())
    else:
        # fallback: 390 per weekday (approx)
        bdays = int(len(pd.bdate_range(cfg.start_ts.normalize(), cfg.end_ts.normalize() - pd.Timedelta(days=1))))
        expected = 390 * bdays

    return {s: expected for s in symbols_present}


# -----------------------
# Metrics via DuckDB
# -----------------------

def compute_symbol_bounds_and_rows(con: duckdb.DuckDBPyConnection, cfg: ExportConfig) -> pd.DataFrame:
    where = _where_time_filter(cfg)
    q = f"""
    SELECT
      symbol,
      MIN(ts_utc) AS first_ts,
      MAX(ts_utc) AS last_ts,
      COUNT(*)    AS rows_observed
    FROM read_parquet('{cfg.parquet_glob}')
    {where}
    GROUP BY 1
    ORDER BY 1
    """
    return con.execute(q).df()


def compute_duplicates(con: duckdb.DuckDBPyConnection, cfg: ExportConfig) -> pd.DataFrame:
    where = _where_time_filter(cfg)
    q = f"""
    WITH keys AS (
      SELECT symbol, ts_utc, timeframe, COUNT(*) AS c
      FROM read_parquet('{cfg.parquet_glob}')
      {where}
      GROUP BY 1,2,3
    )
    SELECT
      symbol,
      SUM(CASE WHEN c > 1 THEN 1 ELSE 0 END) AS duplicate_keys,
      SUM(CASE WHEN c > 1 THEN (c - 1) ELSE 0 END) AS duplicate_rows
    FROM keys
    GROUP BY 1
    ORDER BY duplicate_rows DESC, duplicate_keys DESC, symbol
    """
    return con.execute(q).df()


def compute_ohlc_violations(con: duckdb.DuckDBPyConnection, cfg: ExportConfig) -> pd.DataFrame:
    where = _where_time_filter(cfg)
    q = f"""
    SELECT
      symbol,
      COUNT(*) AS ohlc_violation_count
    FROM read_parquet('{cfg.parquet_glob}')
    {where}
    AND (
      high < GREATEST(open, close)
      OR low > LEAST(open, close)
      OR high < low
      OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
      OR volume < 0
      OR symbol IS NULL OR ts_utc IS NULL OR timeframe IS NULL
    )
    GROUP BY 1
    ORDER BY ohlc_violation_count DESC, symbol
    """
    return con.execute(q).df()


def compute_gap_metrics_1min(con: duckdb.DuckDBPyConnection, cfg: ExportConfig) -> pd.DataFrame:
    where = _where_time_filter(cfg)
    q = f"""
    WITH ordered AS (
      SELECT
        symbol,
        DATE(ts_utc) AS d,
        ts_utc,
        LAG(ts_utc) OVER (PARTITION BY symbol, DATE(ts_utc) ORDER BY ts_utc) AS prev_ts
      FROM read_parquet('{cfg.parquet_glob}')
      {where}
      AND symbol IS NOT NULL AND ts_utc IS NOT NULL
    ),
    diffs AS (
      SELECT
        symbol,
        d,
        CASE
          WHEN prev_ts IS NULL THEN 0
          ELSE GREATEST(DATEDIFF('minute', prev_ts, ts_utc) - 1, 0)
        END AS missing
      FROM ordered
    ),
    per_day AS (
      SELECT
        symbol,
        d,
        SUM(missing) AS gap_count,
        SUM(CASE WHEN missing > 0 THEN 1 ELSE 0 END) AS gap_segments,
        MAX(missing) AS max_gap_len
      FROM diffs
      GROUP BY 1,2
    )
    SELECT
      symbol,
      SUM(gap_count) AS gap_count,
      SUM(gap_segments) AS gap_segments,
      MAX(max_gap_len) AS max_gap_len
    FROM per_day
    GROUP BY 1
    ORDER BY gap_count DESC, symbol
    """
    return con.execute(q).df()


def compute_gap_metrics_daily(con: duckdb.DuckDBPyConnection, cfg: ExportConfig) -> pd.DataFrame:
    """
    Daily gaps based on expected sessions vs observed session dates.
    Calendar-aware if available, otherwise business-day approximation.

    Returns: per-symbol gap_count (missing sessions), segments, max_gap_len (in sessions)
    """
    if cfg.start_ts is None or cfg.end_ts is None:
        return pd.DataFrame(columns=["symbol", "gap_count", "gap_segments", "max_gap_len"])

    where = _where_time_filter(cfg)
    q = f"""
    SELECT symbol, DATE(ts_utc) AS d
    FROM read_parquet('{cfg.parquet_glob}')
    {where}
    AND symbol IS NOT NULL AND ts_utc IS NOT NULL
    GROUP BY 1,2
    ORDER BY 1,2
    """
    obs = con.execute(q).df()
    if obs.empty:
        return pd.DataFrame(columns=["symbol", "gap_count", "gap_segments", "max_gap_len"])

    sched = _try_get_calendar_sessions(cfg.start_ts, cfg.end_ts, cfg.calendar)
    if sched is not None and not sched.empty:
        expected_days = pd.to_datetime(sched.index).date
    else:
        expected_days = pd.bdate_range(cfg.start_ts.normalize(), cfg.end_ts.normalize() - pd.Timedelta(days=1)).date

    expected_list = list(expected_days)

    rows = []
    for sym, g in obs.groupby("symbol"):
        have = set(pd.to_datetime(g["d"]).dt.date.tolist())
        missing = [d for d in expected_list if d not in have]
        gap_count = len(missing)

        # segments/max_gap_len measured in consecutive missing expected sessions
        gap_segments = 0
        max_gap_len = 0
        cur = 0
        prev = None
        for d in expected_list:
            if d in have:
                if cur > 0:
                    gap_segments += 1
                    max_gap_len = max(max_gap_len, cur)
                    cur = 0
            else:
                cur += 1
        if cur > 0:
            gap_segments += 1
            max_gap_len = max(max_gap_len, cur)

        rows.append({
            "symbol": sym,
            "gap_count": gap_count,
            "gap_segments": gap_segments,
            "max_gap_len": max_gap_len,
        })

    return pd.DataFrame(rows).sort_values(["gap_count", "symbol"], ascending=[False, True])


# -----------------------
# Export builder
# -----------------------

def generate_qa_exports(cfg: ExportConfig) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    Returns (by_symbol_df, global_df, overall_status).
    Writes nothing; caller writes to artifacts.
    """
    con = _connect_duckdb()
    where = _where_time_filter(cfg)

    # Schema sanity (best-effort)
    cols = con.execute(f"SELECT * FROM read_parquet('{cfg.parquet_glob}') {where} LIMIT 0").df().columns.tolist()
    missing_cols = [c for c in CANONICAL_COLS if c not in cols]

    bounds = compute_symbol_bounds_and_rows(con, cfg)
    symbols_present = bounds["symbol"].dropna().astype(str).unique().tolist()

    # expected symbols
    expected_syms = cfg.symbols_expected or symbols_present
    expected_set = set(expected_syms)
    present_set = set(symbols_present)
    symbols_missing = sorted(list(expected_set - present_set))

    # duplicates + ohlc + gaps
    dups = compute_duplicates(con, cfg)
    ohlc = compute_ohlc_violations(con, cfg)

    if cfg.bar_interval == "1Min":
        gaps = compute_gap_metrics_1min(con, cfg)
        expected_map = expected_bars_1min(cfg, symbols_present)
    else:
        gaps = compute_gap_metrics_daily(con, cfg)
        expected_map = expected_bars_daily(cfg, symbols_present)

    # Join per-symbol
    by_sym = bounds.merge(dups, on="symbol", how="left") \
                   .merge(ohlc, on="symbol", how="left") \
                   .merge(gaps, on="symbol", how="left")

    by_sym["duplicate_rows"] = by_sym["duplicate_rows"].fillna(0).astype(int)
    by_sym["duplicate_keys"] = by_sym["duplicate_keys"].fillna(0).astype(int)
    by_sym["ohlc_violation_count"] = by_sym["ohlc_violation_count"].fillna(0).astype(int)
    by_sym["gap_count"] = by_sym["gap_count"].fillna(0).astype(int)
    by_sym["gap_segments"] = by_sym.get("gap_segments", pd.Series([0]*len(by_sym))).fillna(0).astype(int)
    by_sym["max_gap_len"] = by_sym.get("max_gap_len", pd.Series([0]*len(by_sym))).fillna(0).astype(int)

    by_sym["expected_bars"] = by_sym["symbol"].map(expected_map).fillna(0).astype(int)
    by_sym["coverage_pct"] = by_sym.apply(
        lambda r: (float(r["rows_observed"]) / float(r["expected_bars"])) if r["expected_bars"] > 0 else 0.0,
        axis=1
    )

    # Notes
    note = []
    if missing_cols:
        note.append(f"Missing canonical cols: {missing_cols}")
    if cfg.symbols_expected is None:
        note.append("symbols_expected not provided (derived from data)")
    if cfg.start_ts is None or cfg.end_ts is None:
        note.append("start/end window not provided (expected_bars may be 0)")
    if _try_get_calendar_sessions(cfg.start_ts, cfg.end_ts, cfg.calendar) is None and cfg.start_ts is not None and cfg.end_ts is not None:
        note.append("calendar fallback used (install pandas_market_calendars for session-aware expected bars)")
    by_sym["notes"] = "; ".join(note) if note else ""

    # Add required export columns and stable order
    run_id = cfg.run_id or _make_run_id(cfg)
    start_s = _format_ts(cfg.start_ts)
    end_s = _format_ts(cfg.end_ts)

    by_sym_export = pd.DataFrame({
        "run_id": run_id,
        "dataset_name": cfg.dataset_name,
        "bar_interval": cfg.bar_interval,
        "symbol": by_sym["symbol"],
        "start_ts": start_s,
        "end_ts": end_s,
        "rows_observed": by_sym["rows_observed"],
        "expected_bars": by_sym["expected_bars"],
        "coverage_pct": by_sym["coverage_pct"],
        "duplicate_rows": by_sym["duplicate_rows"],
        "duplicate_keys": by_sym["duplicate_keys"],
        "gap_count": by_sym["gap_count"],
        "gap_segments": by_sym["gap_segments"],
        "max_gap_len": by_sym["max_gap_len"],
        "ohlc_violation_count": by_sym["ohlc_violation_count"],
        "first_ts": by_sym["first_ts"],
        "last_ts": by_sym["last_ts"],
        "notes": by_sym["notes"],
    }).sort_values(["symbol"])

    # Global metrics
    total_rows = int(by_sym["rows_observed"].sum()) if not by_sym.empty else 0
    unique_rows = total_rows - int(by_sym["duplicate_rows"].sum())
    duplicate_rows = int(by_sym["duplicate_rows"].sum())
    total_duplicate_keys = int(by_sym["duplicate_keys"].sum()) if "duplicate_keys" in by_sym else 0

    total_gap_count = int(by_sym["gap_count"].sum()) if "gap_count" in by_sym else 0
    total_ohlc_violations = int(by_sym["ohlc_violation_count"].sum()) if "ohlc_violation_count" in by_sym else 0

    # Status evaluation
    thr = cfg.thresholds
    below_cov = by_sym_export["coverage_pct"] < thr.min_coverage_pct if len(by_sym_export) else pd.Series([], dtype=bool)
    pct_below = float(below_cov.mean()) if len(by_sym_export) else 0.0

    fail = False
    warn = False

    if duplicate_rows > thr.max_duplicate_rows:
        fail = True
    if total_ohlc_violations > thr.max_ohlc_violations:
        fail = True

    # Gap threshold is per-symbol (as defined)
    if len(by_sym_export) and (by_sym_export["gap_count"] > thr.max_gap_count_per_symbol).any():
        warn = True  # warn by default (can be promoted to fail later if you want)

    if len(by_sym_export) and (by_sym_export["coverage_pct"] < thr.min_coverage_pct).any():
        warn = True

    overall_status = "FAIL" if fail else ("WARN" if warn else "PASS")
    
    from src.qa.qa_coverage import compute_coverage_by_symbol, write_coverage_csv

    coverage_df = compute_coverage_by_symbol(
        con=con,
        parquet_glob=cfg.parquet_glob,   # e.g. data/curated/bars_daily/**/*.parquet
        run_id=run_id,
        dataset_name=cfg.dataset_name,           # "bars_daily" or "bars_1m"
        bar_interval=cfg.bar_interval,           # "1D" or "1Min"
        start_ts=cfg.start_ts,
        end_ts=cfg.end_ts,
        calendar_mode=cfg.calendar,         # "XNYS" default
        symbols_expected=cfg.symbols_expected,   # optional list
    )
    artifact_dir = cfg.out_root / run_id
    coverage_out = f"{artifact_dir}/qa_coverage_by_symbol.csv"
    write_coverage_csv(coverage_df, coverage_out)

    global_export = pd.DataFrame([{
        "run_id": run_id,
        "dataset_name": cfg.dataset_name,
        "bar_interval": cfg.bar_interval,
        "start_ts": start_s,
        "end_ts": end_s,
        "total_rows": total_rows,
        "unique_rows": unique_rows,
        "duplicate_rows": duplicate_rows,
        "total_duplicate_keys": total_duplicate_keys,
        "symbols_expected": len(expected_syms),
        "symbols_present": len(symbols_present),
        "symbols_missing": ";".join(symbols_missing),
        "total_gap_count": total_gap_count,
        "total_ohlc_violation_count": total_ohlc_violations,
        "pct_symbols_below_coverage_threshold": pct_below,
        "coverage_threshold": thr.min_coverage_pct,
        "overall_status": overall_status,
    }])

    return by_sym_export, global_export, overall_status


def write_exports(cfg: ExportConfig) -> Tuple[pd.DataFrame, pd.DataFrame, str, Path]:
    run_id = cfg.run_id or _make_run_id(cfg)
    out_dir = cfg.out_root / run_id
    by_sym, glob, status = generate_qa_exports(cfg)

    _write_csv(by_sym, out_dir / "qa_summary_by_symbol.csv")
    _write_csv(glob, out_dir / "qa_summary_global.csv")

    print(f"QA EXPORT ({cfg.dataset_name}/{cfg.bar_interval}) :: {status} :: {out_dir.resolve()}")
    return by_sym, glob, status, out_dir

        


# -----------------------
# CLI
# -----------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Generate framework-level QA summary exports (global + by symbol).")
    ap.add_argument("--timeframe", choices=["1D", "1Min", "all"], default="all")
    ap.add_argument("--start", default=None, help="Start timestamp/date (inclusive). e.g. 2025-11-01")
    ap.add_argument("--end", default=None, help="End timestamp/date (exclusive). e.g. 2025-12-01")
    ap.add_argument("--dataset-name", default=None, help="Logical dataset name (default derived from timeframe)")
    ap.add_argument("--symbols", default=None, help="Path to expected symbols list (optional)")
    ap.add_argument("--calendar", default="XNYS", help="Market calendar id (default: XNYS).")
    ap.add_argument("--out", default="artifacts/qa", help="Output root for QA artifacts.")
    ap.add_argument("--min-coverage-pct", type=float, default=0.995)
    ap.add_argument("--max-duplicate-rows", type=int, default=0)
    ap.add_argument("--max-ohlc-violations", type=int, default=0)
    ap.add_argument("--max-gap-count-per-symbol", type=int, default=0)
    ap.add_argument("--run-id", default=None, help="Optional explicit run id (otherwise deterministic).")
    ap.add_argument("--strict", action="store_true", help="Fail pipeline if QA thresholds are violated.")
    ap.add_argument("--max-duplicate-keys", type=int, default=0, help="Strict threshold for duplicate primary keys.")

    args = ap.parse_args()

    start_ts = pd.to_datetime(args.start, utc=True) if args.start else None
    end_ts = pd.to_datetime(args.end, utc=True) if args.end else None
    syms = _read_symbols_file(args.symbols)

    thr = Thresholds(
        min_coverage_pct=args.min_coverage_pct,
        max_duplicate_rows=args.max_duplicate_rows,
        max_duplicate_keys=args.max_duplicate_keys,   # NEW
        max_ohlc_violations=args.max_ohlc_violations,
        max_gap_count_per_symbol=args.max_gap_count_per_symbol,
    )

    def _cfg(tf: str) -> ExportConfig:
        dataset_name = args.dataset_name or ("bars_daily" if tf == "1D" else "bars_1m")
        return ExportConfig(
            dataset_name=dataset_name,
            bar_interval=tf,
            parquet_glob=CURATED_PATHS[tf],
            start_ts=start_ts,
            end_ts=end_ts,
            symbols_expected=syms,
            calendar=args.calendar,
            thresholds=thr,
            out_root=Path(args.out),
            run_id=args.run_id,
        )

    exit_code = 0
    from src.qa.qa_enforcer import (
        Thresholds as EnforcerThresholds,
        build_metrics_from_dataframes,
        enforce_or_exit,
    )
    
    def _enforce(by_sym: pd.DataFrame, glob: pd.DataFrame) -> None:
        metrics = build_metrics_from_dataframes(by_symbol_df=by_sym, global_df=glob)

        enforcer_thresholds = EnforcerThresholds(
            max_duplicate_keys=thr.max_duplicate_keys,
            max_ohlc_violations=thr.max_ohlc_violations,
            # Optional later:
            # min_coverage_pct=thr.min_coverage_pct,
            # max_gap_count=None,
            # allow_missing_symbols=True,
        )

        enforce_or_exit(metrics, strict=args.strict, thresholds=enforcer_thresholds)
    
    exit_code = 0  # non-strict always exits 0

    if args.timeframe == "all":
        by1, g1, s1, _ = write_exports(_cfg("1D"))
        _enforce(by1, g1)

        by2, g2, s2, _ = write_exports(_cfg("1Min"))
        _enforce(by2, g2)
    else:
        by, g, s, _ = write_exports(_cfg(args.timeframe))
        _enforce(by, g)

    raise SystemExit(0)


if __name__ == "__main__":
    main()