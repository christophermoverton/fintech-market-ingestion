from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd
from tqdm import tqdm

from src.ingestion.alpaca_client import AlpacaMarketDataClient
from src.ingestion.normalize import normalize_bars
from src.ingestion.storage import ParquetWriteConfig, write_partitioned_parquet
from src.utils.logging import get_logger

log = get_logger("backfill_1m")

def read_symbols(path: Path) -> List[str]:
    """Reads a list of symbols from a text file, one symbol per line."""
    syms = []
    for line in path.read_text().splitlines():
        sym = line.strip().upper()
        if sym and not sym.startswith("#"):  # skip empty lines and comments
            syms.append(sym)
    return syms

def daterange_days(start: pd.Timestamp, end: pd.Timestamp) -> List[pd.Timestamp]:
    """Generates a list of daily timestamps from start to end (exclusive)."""
    start_day = start.normalize()
    end_day = end.normalize()
    days  = []
    cur = start_day
    while cur < end_day:
        if cur.weekday() < 5:  # Skip weekends
            days.append(cur)
        cur += pd.Timedelta(days=1)
    return days

def ensure_reports_dir() -> Path:
    """Ensures the reports directory exists and returns its path."""
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir

def append_failures_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Appends rows of failure data to a CSV file, creating it with headers if it doesn't exist."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False)
    
def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill 1-minute bars for a list of symbols from Alpaca API and store as partitioned Parquet files.")
    ap.add_argument("--symbols", default=  "configs/tickers_50.txt", help="Path to ticker list file")
    ap.add_argument("--start",  required=True, help="Start date (inclusive) in YYYY-MM-DD format")
    ap.add_argument("--end",    required=True, help="End date (exclusive) in YYYY-MM-DD format")
    ap.add_argument("--out", default= "data/curated/bars_1m", help="Curated output root")
    ap.add_argument("--source", default="alpaca_iex", help="Source tag stored in data")
    ap.add_argument("--feed", default=None, help="Override feed (default uses env ALPACA_FEED or 'iex')")
    ap.add_argument("--max-symbols", type=int, default=None, help="Limit the number of symbols to process (for testing)")
    ap.add_argument("--sleep-ms", type=int, default=0, help="Sleep time in milliseconds between API calls (default: 0ms)")
    ap.add_argument("--no-progress", action="store_true", help="Disable progress bar")
    args = ap.parse_args()  
    
    symbols = read_symbols(Path(args.symbols))
    if args.max_symbols is not None:
        symbols = symbols[:args.max_symbols]
    
    client = AlpacaMarketDataClient.from_env()
    out_root = Path(args.out)
    writer_cfg = ParquetWriteConfig(root_dir=out_root, existing_data_behavior="delete_matching")
    
    #Use UTC timestamps (RFC3339)
    start_ts = pd.to_datetime(args.start, utc=True)
    end_ts = pd.to_datetime(args.end, utc=True) 
    days = daterange_days(start_ts, end_ts)
    
    report_dir = ensure_reports_dir()
    failures_path = report_dir / f"backfill_1m_failures_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    
    log.info(f"Symbols: {len(symbols)} | Range: {start_ts} -> {end_ts} | Days: {len(days)}")
    started_all = datetime.now(timezone.utc)
    
    day_iter = days if args.no_progress else tqdm(days, desc="Days", unit="day")
    
    for day_start in day_iter:
        day_end = day_start + pd.Timedelta(days=1)
        day_str = str(day_start.date())
        started_day = datetime.now(timezone.utc)    
        
        if not args.no_progress:
            log.info(f"=== Day {day_str} ===")
        
        failures: List[Dict[str, Any]] = [] 
        sym_iter = symbols if args.no_progress else tqdm(symbols, desc=f"Symbols ({day_str})", leave=False, unit="sym")
        
        for sym in sym_iter:
            try:
                df = client.fetch_bars(
                    symbol=sym,
                    start=day_start.isoformat(),
                    end=day_end.isoformat(),
                    timeframe="1Min",
                    feed=args.feed,
                )
                if df.empty:
                    log.warning(f"No data for {sym} on {day_str}")
                    continue
                
                norm = normalize_bars(df, symbol=sym, source=args.source, timeframe="1Min")
                
                # For 1-minute storage we partition by symbol/date.
                # normalize_bars already creates "date" helper from ts_utc.
                if not norm.empty:
                    write_partitioned_parquet(norm, 
                                              writer_cfg, 
                                              partition_cols=["symbol", "date"]
                                              )
                
                    
            except Exception as e:
                log.error(f"Error processing {sym} on {day_str}: {e}")
                failures.append(
                    {
                        "symbol": sym, 
                        "date": day_str, 
                        "error": str(e)[:500],
                     }
                    )
            
            if args.sleep_ms and args.sleep_ms > 0:
                import time
                
                time.sleep(args.sleep_ms / 1000.0)
                
        append_failures_csv(failures_path, failures)
        
        elapsed_day = datetime.now(timezone.utc) - started_day
        if args.no_progress:
            log.info(f"Day {day_str} done. Failures: {len(failures)} | Elapsed: {elapsed_day}")
            
    elapsed_all = datetime.now(timezone.utc) - started_all
    log.info(f"Done. Days processed: {len(days)} | Symbols: {len(symbols)} | Elapsed: {elapsed_all}")
    log.info(f"Failures log(if any): {failures_path.resolve()}")
    
if __name__ == "__main__":
    main()
    
   