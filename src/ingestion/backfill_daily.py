from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from src.ingestion.alpaca_client import AlpacaMarketDataClient
from src.ingestion.normalize import normalize_bars  
from src.ingestion.storage import ParquetWriteConfig, write_partitioned_parquet
from src.utils.logging import get_logger

log = get_logger("backfill_daily")

def read_symbols(path: Path) -> List[str]:
    """Reads a list of symbols from a text file, one symbol per line."""
    syms = []
    for line in path.read_text().splitlines():
        sym = line.strip().upper()
        if sym and not sym.startswith("#"):  # skip empty lines and comments
            syms.append(sym)
    return syms

def month_windows(start: pd.Timestamp, end: pd.Timestamp) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """Generates a list of (start, end) tuples for each month in the given date range."""
    windows = []
    current_start = start
    
    while current_start < end:
        next_month = (current_start + pd.offsets.MonthBegin(1)).normalize()
        if next_month <= current_start:
            next_month = current_start + pd.Timedelta(days=31)
            
        windows.append((current_start, min(next_month,end)))
        current_start = next_month
    
    return windows



def main():
    ap = argparse.ArgumentParser(description="Backfill daily bars for a list of symbols from Alpaca API and store as partitioned Parquet files.")
    ap.add_argument("--symbols", default=  "configs/tickers_50.txt", help="Path to ticker list file")
    ap.add_argument("--start",  required=True, help="Start date (inclusive) in YYYY-MM-DD format")
    ap.add_argument("--end",    required=True, help="End date (exclusive) in YYYY-MM-DD format")
    ap.add_argument("--out", default= "data/curated/bars_daily", help="Curated output root")
    ap.add_argument("--source", default="alpaca_iex", help="Source tag stored in data")
    ap.add_argument("--feed", default=None, help="Override feed (default uses env ALPACA_FEED or 'iex')")
    ap.add_argument("--window", choices=["month","year"], default="month", help="Window size for API requests (default: month)")
    args = ap.parse_args()
    
    symbols = read_symbols(Path(args.symbols))
    client = AlpacaMarketDataClient.from_env()
    out_root = Path(args.out)
    
    #Use UTC timestamps (RFC3339)
    start_ts = pd.to_datetime(args.start, utc=True)
    end_ts = pd.to_datetime(args.end, utc=True)
    
    if args.window == "year":
        windows = []
        cur = start_ts
        while cur < end_ts:
            nxt = (cur + pd.offsets.YearBegin(1)).normalize()   
            if nxt <= cur:
                nxt = cur + pd.Timedelta(days=366)
            windows.append((cur, min(nxt,end_ts)))
            cur = nxt
    else:   
        windows = month_windows(start_ts, end_ts)
    
    log.info(f"Symbols: {len(symbols)} | Range: {start_ts.date()} -> {end_ts.date()} | Windows: {len(windows)}")
    
    writer_cfg = ParquetWriteConfig(root_dir=out_root)
    
    total_rows = 0
    started = datetime.now(timezone.utc)
    for sym in symbols:
        sym_rows = 0
        log.info(f"==={sym}===")
        
        for (wo, w1) in windows:
            df = client.fetch_bars(
                symbol=sym,
                start=wo.isoformat().replace("+00:00", "Z"),
                end=w1.isoformat().replace("+00:00", "Z"),
                timeframe="1Day",
                feed=args.feed,
            )
            
            norm = normalize_bars(df, symbol=sym, source=args.source, timeframe="1D")
            
            if norm.empty:
                log.info(f"  {wo.date()} -> {w1.date()}: no data")
                continue
            
            write_partitioned_parquet(norm, 
                                      writer_cfg, 
                                      partition_cols=["symbol", "year"]
                                      )
            sym_rows += len(norm)
            
        total_rows += sym_rows
        log.info(f"{sym}: wrote {sym_rows} rows")
    
    elapsed = datetime.now(timezone.utc) - started
    log.info(f"Done. Total rows: {total_rows} | Elapsed: {elapsed}")

if __name__ == "__main__":
    main()