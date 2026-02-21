from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import pandas as pd

#-----------------------------
# Config
#----------------------------- 

CURATED_PATHS = {
    "1D": "data/curated/bars_daily/**/*.parquet",
    "1Min": "data/curated/bars_1m/**/*.parquet",
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

PRIMARY_KEY = ["symbol", "ts_utc", "timeframe"]

@dataclass(frozen=True)
class QAConfig:
    timeframe: str
    parquet_glob: str
    reports_dir: Path
    sample_n: int = 50
    strict: bool = False
    max_ohlc_violations: int = 0

# -----------------------------
# Helpers
#-----------------------------

def ensure_reports_dir() -> Path:
    p = Path("reports")
    p.mkdir(parents=True, exist_ok=True)
    return p

def _connect_duckdb() -> duckdb.DuckDBPyConnection:
    """Creates and returns a DuckDB connection."""
    con = duckdb.connect(database=":memory:")
    # Good defaults for Parquet scanning  + performance
    con.execute("PRAGMA threads=4;")
    con.execute("PRAGMA enable_object_cache=true;")
    return con

def _parquet_exists(glob_pattern: str) -> bool:
    """duckdb read_parquet will throw if no files match, 
    so do a quick filesystem glob check first."""
    return len(list(Path(".").glob(glob_pattern))) > 0

def _require_columns_present(df_cols: List[str]) -> List[str]:
    missing = [c for c in CANONICAL_COLS if c not in df_cols]
    return missing

def _write_csv(df: pd.DataFrame, path: Path) -> None:
    """Writes a DataFrame to CSV"""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    
#-----------------------------
# Core QA Queries
#-----------------------------

def compute_summary(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> pd.DataFrame:
    """Computes summary statistics for the bars data."""
    query = f"""
    SELECT 
        symbol,
        timeframe,
        MIN(ts_utc) AS min_ts,
        MAX(ts_utc) AS max_ts,
        COUNT(*) AS row_count,
    FROM read_parquet('{cfg.parquet_glob}')
    GROUP BY symbol, timeframe
    ORDER BY symbol, timeframe
    """
    df = con.execute(query).fetchdf()
    df["last_updated"] = datetime.now(timezone.utc).isoformat()
    return df

def compute_duplicates(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> Tuple[pd.DataFrame, pd.DataFrame, int]:
    """Returns:
       - duplicates_detail: rows with duplicate primary keys (symbol, ts_utc, timeframe) and their counts
       - duplicates_by_symbol: count of duplicates aggregated by symbol
       - total_duplicate_keys: number of duplicate keys (distinct key with count > 1)
    """
    query = f"""
    SELECT 
        symbol,
        ts_utc,
        timeframe,
        COUNT(*) AS key_count
    FROM read_parquet('{cfg.parquet_glob}')
    GROUP BY symbol, ts_utc, timeframe
    HAVING COUNT(*) > 1
    ORDER BY key_count DESC, symbol, ts_utc
    """
    detail = con.execute(query).fetchdf()
    
    if detail.empty:
        by_symbol = pd.DataFrame(columns=["symbol", "duplicate_keys","duplicate_rows"])
        return detail, by_symbol, 0
    
    #duplicate_keys = number of duplicated keys per symbol
    #duplicate_rows = total "extra" rows (sum(key_count -1)) per symbol
    by_symbol = (
        detail.assign(extra_rows=lambda x: x["key_count"] - 1)
        .groupby("symbol")
        .agg(
            duplicate_keys=("key_count", "size"),
            duplicate_rows=("extra_rows", "sum")
        )
        .sort_values(["duplicate_keys", "duplicate_rows"], ascending=False)
    )
    
    total_duplicate_keys = int(len(detail))
    return detail, by_symbol, total_duplicate_keys
    
def compute_ohlc_violations(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> Tuple[pd.DataFrame, pd.Dataframe, int]:
    """Returns:
       - violations_summary: counts by (rule, symbol)
       - violations_samples: sample rows for each rule (top N per rule)
       - total_violations: total number of rows that violate any OHLC rule
    """
    #Build rules as expressions that yield boolean in DuckDB
    rules ={
        "high_lt_max_open_close":"high < GREATEST(open, close)",
        "low_gt_min_open_close":"low > LEAST(open, close)",
        "nonpositive_price": "open <= 0 OR high <= 0 OR low <= 0 OR close <= 0",
        "negative_volume": "volume < 0",
        "null_required": "(symbol IS NULL OR ts_utc IS NULL OR timeframe IS NULL OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL or volume IS NULL)"
    }
    
    # Summary counts by rule and symbol
    union_parts = []
    for rule_name, rule_expr in rules.items():
        part = f"""
        SELECT 
            '{rule_name}' AS rule,
            symbol,
            COUNT(*) AS violation_count
        FROM read_parquet('{cfg.parquet_glob}')
        WHERE {rule_expr}
        GROUP BY 1,2
        """
        union_parts.append(part)
    
    summary_q = " UNION ALL ".join(union_parts)
    violations_summary = con.execute(summary_q).fetchdf()
    violations_summary = violations_summary[violations_summary["violation_count"] > 0].copy()
    
    #Total violating rows (any rule)
    any_rule_expr = " OR ".join([f"({expr})" for expr in rules.values()])
    total_q = f"""
    SELECT COUNT(*) AS n
    FROM read_parquet('{cfg.parquet_glob}')
    WHERE {any_rule_expr}
    """
    total_violations = int(con.execute(total_q).fetchone()[0])
    
    # Samples: take top N violating rows per rule  (simple LIMIT per rule)
    samples_frames: List[pd.DataFrame] = []
    for rule_name, rule_expr in rules.items():
        sample_q = f"""
        SELECT 
            '{rule_name}' AS rule,
            symbol,
            ts_utc,
            timeframe,
            open,
            high,
            low,
            close,
            volume,
            source
        FROM read_parquet('{cfg.parquet_glob}')
        WHERE {rule_expr}
        LIMIT {int(cfg.sample_n)}
        """
        sample_df = con.execute(sample_q).fetchdf()
        if not sample_df.empty:
            samples_frames.append(sample_df)
    
    violations_samples = pd.concat(samples_frames, ignore_index=True) if samples_frames else pd.DataFrame()

    return violations_summary, violations_samples, total_violations

def compute_timestamp_check(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> pd.DataFrame:
    """Timestamp issues check:
        - ts_utc non-null handledd in OHLC rules (null_required)
        - out-of-order per symbol: ts_utc < lag(ts_utc)
    """
    
    query = f"""
    WITH ordered AS (
        SELECT 
            symbol,
            ts_utc,
            timeframe,
            LAG(ts_utc) OVER (PARTITION BY symbol ORDER BY ts_utc) AS prev_ts
        FROM read_parquet('{cfg.parquet_glob}')
        WHERE ts_utc IS NOT NULL AND symbol IS NOT NULL AND timeframe IS NOT NULL
    )
    SELECT 
        symbol,
        timeframe,
        SUM(CASE WHEN prev_ts IS NOT NULL AND ts_utc < prev_ts THEN 1 ELSE 0 END) AS out_of_order_count
    FROM ordered
    GROUP BY 1,2
    ORDER BY out_of_order_count DESC, symbol
    """
    df = con.execute(query).fetchdf()
    return df

#-----------------------------
# Gap / Coverage Checks (pandas)
#-----------------------------

def compute_gaps_daily(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> pd.DataFrame:
    """Daily gaps approximation:
       -- For each symbole, compute business-day expected range between min/max
       -- gap_count = expected_business_days - actual_days
    """
    # Pull distinct symbol + date (derived from ts_utc)
    
    query = f"""
    SELECT 
        symbol,
        Date(ts_utc) AS d
    FROM read_parquet('{cfg.parquet_glob}')
    WHERE symbol IS NOT NULL AND ts_utc IS NOT NULL
    GROUP BY 1,2
    ORDER BY 1,2
    """
    df = con.execute(query).fetchdf()
    if df.empty:
        return pd.DataFrame(columns=["symbol", "min_date", "max_date", "actual_days", "expected_bdays", "missing_days"])
    
    out_rows = []
    for sym, g in df.groupby("symbol"):
        dates = pd.to_datetime(g["d"]).sort_values()
        min_date = dates.min()
        max_date = dates.max()
        actual = int(dates.nunique())
        expected = len(pd.bdate_range(start=min_date, end=max_date))
        missing = max(0, expected - actual)
        out_rows.append({
            "symbol": sym,
            "min_date": min_date.date().isoformat(),
            "max_date": max_date.date().isoformat(),
            "actual_days": actual,
            "expected_bdays": expected,
            "missing_days": missing,
        })
        
    return pd.DataFrame(out_rows).sort_values(["missing_days","symbol"], ascending=[False,False])   

def compute_gaps_1m(con: duckdb.DuckDBPyConnection, cfg: QAConfig) -> pd.DataFrame: 
    """
    1-minute gaps approximation:
    For each symbol/day, expected minutes ~ 390 (regular session).
    missing_minutes = max(0, 390 - row_count)

    Note: this is intentionally an approximation (no early close /halt handling yet).
    Later refinement can use a trading calendar + session schedules.
    """
    
    q = f"""
    SELECT
        symbol,
        Date(ts_utc) AS d,
        COUNT(*) AS rows
    FROM read_parquet('{cfg.parquet_glob}')
    WHERE symbol IS NOT NULL AND ts_utc IS NOT NULL
    GROUP BY 1,2
    ORDER BY 1,2
    """
    
    df = con.execute(q).fetchdf()
    if df.empty:
        return pd.DataFrame(columns=["symbol", "date", "rows", "expected_minutes", "missing_minutes"])
    
    expected = 390
    df = df.rename(columns={"d":"date"})
    df["expected_minutes"] = expected
    df["missing_minutes"] = (expected - df["rows"]).clip(lower=0)
    return df.sort_values(["missing_minutes","symbol","date"], ascending=[False,True,True])

#-----------------------------
# Runner / Report Writer
#-----------------------------

def run_qa(cfg: QAConfig) -> int:
    """
    Returns process exit code:
    0 = succcess
    1 = strict failure (duplicates or too many OHLC violations)
    """
    
    reports = cfg.reports_dir
    runtime = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    if not _parquet_exists(cfg.parquet_glob):
        # No curated data yet for this dataset
        summary = pd.DataFrame([{
            "symbol": None,
            "timeframe": cfg.timeframe,
            "min_ts": None,
            "max_ts": None,
            "row_count": 0,
            "duplicate_count": 0,
            "ohlc_violation_count": 0,
            "gap_count": 0,
            "last_updated": runtime,
            "notes": f"No Parquet files matched: {cfg.parquet_glob}",
        }])
        _write_csv(summary, reports / "qa_summary.csv")
        return 0
    
    con = _connect_duckdb()
    
    # 0) Basic schema presence check
    # DuckDB can describe a parquet scan via a 0-row select
    cols = con.execute(f"SELECT * FROM read_parquet('{cfg.parquet_glob}') LIMIT 0").df().columns.tolist()
    missing_cols = _require_columns_present(cols)
    
    # 1) Summary base
    summary = compute_summary(con, cfg)
    
    # 2) Duplicates (hard fail in strict)
    dup_detail, dup_by_symbol, total_dup_keys = compute_duplicates(con, cfg)
    
    # Add dup counts into summary
    if not dup_by_symbol.empty:
        summary = summary.merge(dup_by_symbol[["symbol","duplicate_keys","duplicate_rows"]], on="symbol", how="left")
        summary["duplicate_keys"] = summary["duplicate_keys"].fillna(0).astype(int)
        summary["duplicate_rows"] = summary["duplicate_rows"].fillna(0).astype(int)
    else:
        summary["duplicate_keys"] = 0
        summary["duplicate_rows"] = 0
        
    # 3) OHLC integrity
    ohlc_summary, ohlc_samples, total_ohlc_violations = compute_ohlc_violations(con, cfg)
    
    # add ohlc violations per symbol (any rule)
    if not ohlc_summary.empty:
        ohlc_by_symbol = (
            ohlc_summary.groupby("symbol", as_index=False)["violation_count"]
                        .sum()
                        .rename(columns={"violation_count": "ohlc_violation_count"})
        )
        summary = summary.merge(ohlc_by_symbol, on="symbol", how="left")
        summary["ohlc_violation_count"] = summary["ohlc_violation_count"].fillna(0).astype(int)
    else:
        summary["ohlc_violation_count"] = 0
    
    # 4) Timestamp check
    ts_check = compute_timestamp_check(con, cfg)
    summary = summary.merge(ts_check, on=["symbol","timeframe"], how="left")
    summary["out_of_order_count"] = summary["out_of_order_count"].fillna(0).astype(int)
    
    # 5) Gaps / coverage 
    if cfg.timeframe == "1D":
        gaps_daily = compute_gaps_daily(con, cfg)
        _write_csv(gaps_daily, reports / "qa_gaps_daily.csv")
        gap_map = gaps_daily.set_index("symbol")["missing_days"].to_dict()
        summary["gap_count"] = summary["symbol"].map(gap_map).fillna(0).astype(int)
    else:
        gaps_1m = compute_gaps_1m(con, cfg)
        _write_csv(gaps_1m, reports / "qa_gaps_1m.csv")
        # Summarize missing minutes per symbol
        gap_by_symbol = gaps_1m.groupby("symbol", as_index=False)["missing_minutes"].sum()
        gap_map = gap_by_symbol.set_index("symbol")["missing_minutes"].to_dict()
        summary["gap_count"] = summary["symbol"].map(gap_map).fillna(0).astype(int)
        
    # Add notes
    notes = []
    if missing_cols:
        notes.append(f"Missing canonical columns: {missing_cols}")
    summary["notes"] = "; ".join(notes) if notes else ""
    
    # 7) Write qa_summary.csv always (consolidated)
    # Ensure required fields exist even if merges didn't add them
    for col in ["duplicate_keys", "ohlc_violation_count", "gap_count", "out_of_order_count"]:
        if col not in summary.columns:
            summary[col] = 0
    
    # Keep compact column order    
    keep_cols = [
        "symbol", "timeframe", "min_ts", "max_ts", "row_count",
        "duplicate_keys", "ohlc_violation_count", "gap_count", "out_of_order_count",
        "last_updated", "notes"
    ]
    for c in keep_cols:
        if c not in summary.columns:
            summary[c] = None
    summary = summary[keep_cols].sort_values(["timeframe", "symbol"], ascending=[True, True])
    
    _write_csv(summary, reports / "qa_summary.csv")
    
    # 8) Conditional reports 
    if not dup_detail.empty:
        _write_csv(dup_detail, reports / "qa_duplicates.csv")
    
    if not ohlc_summary.empty:
        _write_csv(ohlc_summary.sort_values(["violation_count"], ascending=False), reports / "qa_ohlc_violations.csv")
        if not ohlc_samples.empty:
            _write_csv(ohlc_samples, reports / "qa_ohlc_violations_samples.csv")
            
    # 9) Strict mode enforcement
    # Spec: strict fails if duplicates exist OR ohlc violations exceed threshold
    if cfg.strict:
        fail_reasons = []
        if total_dup_keys > 0:
            fail_reasons.append(f"duplicate_keys={total_dup_keys}")
        if total_ohlc_violations > cfg.max_ohlc_violations:
            fail_reasons.append(f"ohlc_violations={total_ohlc_violations} > {cfg.max_ohlc_violations}")
        if missing_cols:
            fail_reasons.append("missing_canonical_columns")

        if fail_reasons:
            # Print a concise summary for CI logs
            print(f"QA STRICT MODE: FAIL ({cfg.timeframe}) :: " + ", ".join(fail_reasons))
            print(f"See reports/qa_summary.csv and conditional reports for details.")
            return 1

    print(f"QA OK ({cfg.timeframe}) :: wrote reports to {reports.resolve()}")
    return 0

# -----------------------------
# CLI
# -----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Run QA checks for curated market data (daily + 1-minute bars).")
    ap.add_argument("--timeframe", choices=["1D", "1Min", "all"], default="all",
                    help="Which dataset to validate.")
    ap.add_argument("--strict", action="store_true",
                    help="Fail (exit non-zero) on duplicates or OHLC violations above threshold.")
    ap.add_argument("--max-ohlc-violations", type=int, default=0,
                    help="Strict mode threshold: fail if total OHLC violations exceed this count (default: 0).")
    ap.add_argument("--sample-n", type=int, default=50,
                    help="Sample size for violation rows written to reports (default: 50).")

    args = ap.parse_args()
    reports_dir = ensure_reports_dir()

    exit_code = 0

    def _run(tf: str) -> int:
        cfg = QAConfig(
            timeframe=tf,
            parquet_glob=CURATED_PATHS[tf],
            reports_dir=reports_dir,
            sample_n=args.sample_n,
            strict=args.strict,
            max_ohlc_violations=args.max_ohlc_violations,
        )
        return run_qa(cfg)

    if args.timeframe == "all":
        # run both; if either fails strict, return 1
        rc1 = _run("1D")
        rc2 = _run("1Min")
        exit_code = 1 if (rc1 != 0 or rc2 != 0) else 0
    else:
        exit_code = _run(args.timeframe)

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()