## Universe Selection Criteria

Document:
- Selection logic (liquidity + large-cap bias)
- Exclusion rules
- Intended expansion strategy


## 📡 Alpaca Market Data Client

The project includes a reusable Alpaca historical market data client:

```
src/ingestion/alpaca_client.py
```

### Features

* Auth via `.env`
* Supports:

  * `symbol`
  * `start`
  * `end`
  * `timeframe` (`1Day`, `1Min`)
  * `feed` (default: `iex`)
* Handles pagination automatically
* Implements exponential backoff for:

  * HTTP 429 (rate limit)
  * HTTP 5xx (server errors)
  * network timeouts
* Returns results as a pandas DataFrame

### Example Usage

```python
from src.ingestion.alpaca_client import AlpacaMarketDataClient

client = AlpacaMarketDataClient.from_env()

df = client.fetch_bars(
    symbol="AAPL",
    start="2025-01-01T00:00:00Z",
    end="2025-02-01T00:00:00Z",
    timeframe="1Day"
)

print(df.head())
```

---

## Architectural diagram


```
Alpaca API
     ↓
Alpaca Client (retry + pagination)
     ↓
Normalization Layer
     ↓
Partitioned Parquet
     ↓
DuckDB Analytics
```


## Current Capabilities

###  Alpaca Historical Market Data Client

* Auth via `.env`
* Supports:

  * `symbol`
  * `start`
  * `end`
  * `timeframe` (`1Day`, `1Min`)
  * `feed` (default: `iex`)
* Handles:

  * Pagination
  * Rate limiting (HTTP 429)
  * 5xx retries with exponential backoff
* Returns pandas DataFrame

---

###  Windowed Daily Backfill Pipeline

* Iterates over 50-ticker universe
* Fetches daily bars in monthly windows
* Normalizes to canonical schema
* Enforces UTC timestamps
* Deterministic deduplication on:

  ```
  (symbol, ts_utc, timeframe)
  ```
* Writes partitioned Parquet to:

  ```
  data/curated/bars_daily/symbol=XYZ/year=YYYY/
  ```
* Safe to rerun (idempotent)

---

###  Partitioned Parquet Storage

* Implemented using `pyarrow.write_to_dataset`
* Uses `delete_matching` behavior for clean partition overwrites
* DuckDB-compatible direct query over glob paths

---

###  DuckDB Analytics Validation

Example query:

```python
import duckdb
con = duckdb.connect()

df = con.execute("""
  SELECT symbol,
         MIN(ts_utc) AS min_ts,
         MAX(ts_utc) AS max_ts,
         COUNT(*) AS row_count
  FROM 'data/curated/bars_daily/**/*.parquet'
  GROUP BY symbol
  ORDER BY symbol
""").df()

print(df.head())
```

---

## Architecture Overview

```
Alpaca API
    ↓
AlpacaMarketDataClient
    ↓
Normalization Layer (UTC + dedupe)
    ↓
Partitioned Parquet (symbol/year)
    ↓
DuckDB Analytics
```

---

## Example Usage for backfill_daily.py for data ingestion

```python
python -m src.ingestion.backfill_daily --start 2023-01-01 --end 2026-01-01
```



# 1-Minute Historical Backfill

This project supports windowed ingestion of 1-minute OHLCV bars from Alpaca market data (IEX-compatible feed) into a curated, partitioned Parquet dataset.

The ingestion pipeline is designed for:

* Idempotent re-runs
* Restartable backfills
* Rate-limit safe API usage
* Failure isolation
* Downstream analytical compatibility (DuckDB, Pandas, backtests)

---

## Data Contract (Canonical Schema)

All 1-minute bars conform to the same schema as daily bars:

| Column    | Type            | Description                        |
| --------- | --------------- | ---------------------------------- |
| symbol    | string          | Ticker symbol                      |
| ts_utc    | timestamp (UTC) | Bar open time in UTC               |
| open      | float           | Open price                         |
| high      | float           | High price                         |
| low       | float           | Low price                          |
| close     | float           | Close price                        |
| volume    | float/int       | Trade volume                       |
| source    | string          | e.g., `alpaca_iex`                 |
| timeframe | string          | `"1Min"`                           |
| date      | string          | `YYYY-MM-DD` (derived from ts_utc) |

### Primary Key (Idempotency)

```
(symbol, ts_utc, timeframe)
```

Backfills can be safely re-run without increasing row counts.

---

## Partition Layout

Curated 1-minute bars are written to:

```
data/curated/bars_1m/
  symbol=XYZ/
    date=YYYY-MM-DD/
      part-*.parquet
```

This enables:

* Efficient symbol-level filtering
* Date pruning in DuckDB
* Incremental overwrites by partition

---

## Backfill Strategy

Backfill is **windowed by day**:

For each day in `[start, end)`:

* For each symbol:

  * Fetch 1-minute bars
  * Normalize + dedupe
  * Write to partition `symbol/date`

Benefits:

* Reduced failure blast radius
* Restartable per-day
* API rate-limit safe
* Operationally observable

---

## CLI Usage

Backfill 3 months of data:

```
python -m src.ingestion.backfill_1m \
  --start 2024-01-01 \
  --end 2024-04-01
```

Optional flags:

```
--symbols configs/tickers_50.txt
--max-symbols 5
--sleep-ms 100
--no-progress
```

---

## Failure Logging

Failed (symbol, date) requests are written to:

```
reports/backfill_1m_failures_YYYYMMDD_HHMMSS.csv
```

Backfill continues even if individual symbol/day requests fail.

---

## Smoke Tests

Basic operational validation is included:

### 1. Short Window Test

```
smoke_test_backfill_1min_3d5sym.py
```

Backfills 3 days across 5 symbols.

---

### 2. Full Universe Test

```
smoke_test_backfill_1min_3m50sym.py
```

Backfills 3 months across the 50-ticker universe.

---

### 3. DuckDB Validation

```
smoke_test_duckdb_1m_query.py
```

Verifies:

* Row counts per symbol
* Max timestamp per symbol
* Sample intraday return calculations
* Partition integrity

---

## Idempotency Guarantee

Re-running the same date range:

* Does not increase row counts
* Does not create duplicate primary keys
* Overwrites matching partitions safely

---

## Operational Notes

* Market-closed days (weekends/holidays) may produce zero bars.
* These are expected and do not represent ingestion failure.
* Future QA layer will formalize calendar-aware coverage metrics and strict enforcement.

---

> ## Data Quality & Validation (QA Layer)

---

# Data Quality & Validation (QA Layer)

This repository includes a QA module that validates curated market data (daily and 1-minute bars) after any backfill or ingestion run.

The QA layer ensures:

* Primary key uniqueness
* OHLC integrity
* Timestamp ordering
* Coverage gap detection
* Repeatable, exportable reporting
* Optional strict enforcement mode

---

## Supported Datasets

| Timeframe  | Path                                   |
| ---------- | -------------------------------------- |
| Daily (1D) | `data/curated/bars_daily/**/*.parquet` |
| 1-Minute   | `data/curated/bars_1m/**/*.parquet`    |

Canonical schema expected:

```
symbol, ts_utc, open, high, low, close, volume, source, timeframe
```

Primary key:

```
(symbol, ts_utc, timeframe)
```

---

## QA Checks Implemented

###  Duplicate Detection (Primary Key Integrity)

Detects duplicate rows on:

```
(symbol, ts_utc, timeframe)
```

* Reports duplicates per symbol
* Writes detailed duplicate file if found
* Fails in `--strict` mode

---

###  OHLC Integrity Rules

Validates:

* `high >= max(open, close)`
* `low <= min(open, close)`
* `high >= low`
* `open, high, low, close > 0`
* `volume >= 0`
* Required fields non-null

Reports:

* Violations by rule + symbol
* Sample offending rows (configurable size)

---

###  Timestamp Sanity

* Ensures `ts_utc` is non-null
* Detects out-of-order timestamps per symbol
* Counts ordering violations

---

###  Coverage / Gap Detection

#### Daily (1D)

* Business-day approximation between min/max date
* Reports missing business days per symbol

#### 1-Minute (1Min)

* Approximate expected = 390 minutes per regular session
* Computes missing minutes per symbol/day
* Aggregates total missing minutes per symbol

> Note: 1-minute gap detection uses a 390-minute session approximation.
> Early closes and holidays may increase gap counts.
> Calendar-aware refinement is planned.

---

## CLI Usage

Run QA for daily data:

```bash
python -m src.ingestion.quality --timeframe 1D
```

Run QA for 1-minute data:

```bash
python -m src.ingestion.quality --timeframe 1Min
```

Run QA for both datasets:

```bash
python -m src.ingestion.quality --timeframe all
```

Enable strict enforcement:

```bash
python -m src.ingestion.quality --timeframe all --strict
```

Options:

```
--sample-n 50
--max-ohlc-violations 0
```

---

## Reports Generated

Always:

```
reports/qa_summary.csv
```

Conditional:

```
reports/qa_duplicates.csv
reports/qa_ohlc_violations.csv
reports/qa_ohlc_violations_samples.csv
reports/qa_gaps_daily.csv
reports/qa_gaps_1m.csv
```

The QA summary includes:

* symbol
* timeframe
* min_ts / max_ts
* row_count
* duplicate_keys
* ohlc_violation_count
* gap_count
* out_of_order_count
* last_updated

---

## Strict Mode Behavior

When `--strict` is enabled:

The process exits non-zero if:

* Duplicate primary keys exist
* OHLC violations exceed threshold
* Canonical schema columns are missing

This enables:

* CI enforcement
* Automated gating before backtests
* Safe production deployment

---

## Architecture Notes

* Uses DuckDB to query Parquet directly (fast, memory-efficient)
* Pandas used only for formatting and report export
* Designed to be idempotent and repeatable

---


