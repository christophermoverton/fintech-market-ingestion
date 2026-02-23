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


# QA Summary Export (Framework-Level Observability)

The repository includes a framework-level QA export that produces structured dataset health reports per run.

Exports are written to:

```
artifacts/qa/<run_id>/
  qa_summary_by_symbol.csv
  qa_summary_global.csv
```

These reports provide deterministic, reproducible observability across daily and 1-minute datasets.

---

## Gap Detection (Updated – Session-Aware Logic)

### 1-Minute Bars

Gap metrics are computed using timestamp deltas within each `(symbol, session_date)`:

* `gap_count` → total missing minutes implied by consecutive bars
* `gap_segments` → number of contiguous missing-minute sequences
* `max_gap_len` → largest missing-minute streak

This logic:

* Partitions by `(symbol, date)`
* Computes minute differences between consecutive bars
* Prevents overnight and weekend closures from being counted as gaps

This replaces the earlier 390-minute-per-day approximation and eliminates artificial inflation from session boundaries.

---

## Coverage Metrics

Coverage is calculated as:

```
coverage_pct = rows_observed / expected_bars
```

Where:

* Daily expected bars = trading sessions in window
* 1-Min expected bars = session minutes (calendar-aware if available)
* Falls back to business-day approximations if no calendar library is installed

### Important Note on IEX Feed

For 1-minute data using the Alpaca IEX feed:

* Not every minute may contain a trade
* Missing bars may reflect feed scope rather than structural corruption

Coverage thresholds should be tuned accordingly for intraday datasets.

---

## Global Summary Report

`qa_summary_global.csv` includes:

* total_rows
* unique_rows
* duplicate_rows
* total_gap_count
* total_ohlc_violation_count
* pct_symbols_below_coverage_threshold
* overall_status (PASS / WARN / FAIL)

Status evaluation:

* **FAIL** → duplicates or OHLC violations exceed thresholds
* **WARN** → coverage or gap thresholds exceeded
* **PASS** → all checks within limits

---

## Deterministic Artifact Design

Each QA run produces a deterministic artifact directory:

```
artifacts/qa/<run_id>/
```

Run IDs are derived from:

```
dataset_name + interval + start_ts + end_ts + calendar
```

This ensures:

* Reproducibility
* Auditability
* CI compatibility
* Historical comparability

---

## Why This Matters

Backtests are only as reliable as the bars beneath them.

The QA Summary Export now provides:

* Structural integrity validation
* Session-aware intraday gap detection
* Calendar-aware coverage metrics
* Deterministic PASS/WARN/FAIL evaluation
* Audit-grade artifact output

This moves the project from simple validation to a structured data observability framework.

---

## Optional Enhancement (Future Work)

* Fully session-aware expected-minute index comparison
* Extended-hours handling
* Per-run historical QA trend table
* Machine-readable JSON summary export
* CI auto-fail based on `qa_summary_global.csv`

---

# M2 – Data Quality & Observability

This milestone upgrades the ingestion pipeline from passive QA reporting to **production-grade guardrail enforcement** suitable for trading systems and CI environments.

The QA framework now consists of three distinct layers:

```
QA Architecture

qa_export.py      → Computes metrics and writes QA artifacts
qa_enforcer.py    → Enforces strict integrity thresholds
CLI (--strict)    → Enables pipeline-failing guardrails
```

---

## Strict QA Mode (Guardrail Enforcement)

The pipeline supports a `--strict` mode that converts QA from observational reporting into enforceable production safeguards.

When enabled:

* Duplicate primary keys cause pipeline failure
* OHLC violations cause pipeline failure
* Exit code = 1 (CI-compatible)
* Failure summary printed with top offending symbols
* QA artifacts are still written for debugging

---

### Why Strict Mode Matters (Trading Context)

In algorithmic trading systems:

* Duplicate bars distort indicators (EMA, RSI, VWAP, etc.)
* OHLC violations corrupt backtests
* Silent data drift can invalidate signal research
* Integrity failures must never reach modeling or execution layers

Strict mode guarantees:

> No corrupted bars reach downstream signal generation.

---

## CLI Usage

### Observability Mode (Default)

Exports QA artifacts but never fails the pipeline.

```bash
python -m src.ingestion.qa_export \
  --timeframe all \
  --start 2025-11-01 \
  --end 2025-12-01
```

---

### Strict Enforcement Mode

Fails the pipeline if integrity thresholds are exceeded.

```bash
python -m src.ingestion.qa_export \
  --timeframe all \
  --start 2025-11-01 \
  --end 2025-12-01 \
  --strict \
  --max-duplicate-keys 0 \
  --max-ohlc-violations 0
```

Exit Codes:

| Mode | Condition                               | Exit Code |
| ---- | --------------------------------------- | --------- |
| PASS | Within thresholds                       | 0         |
| WARN | Non-strict integrity or coverage issues | 0         |
| FAIL | Strict integrity violation              | 1         |

---

## QA Artifacts

QA outputs are written to:

```
artifacts/qa/<run_id>/
```

Examples:

```
qa_bars_daily_1D_2025-11-01_2025-12-01_XNYS/
qa_bars_1m_1Min_2025-11-01_2025-12-01_XNYS/
```

Each run directory contains:

* `qa_summary_by_symbol.csv`
* `qa_summary_global.csv`

---

## Enforced Integrity Rules (Strict Mode)

Primary enforcement checks:

* **Duplicate primary keys**
  `(symbol, ts_utc, timeframe)`
  Zero tolerance by default.

* **OHLC violations**
  Invalid price relationships or corrupted fields.

Optional (configurable in future extensions):

* Coverage thresholds
* Gap thresholds
* Missing symbol enforcement

---

## Clean Separation of Responsibilities

| Module           | Responsibility                            |
| ---------------- | ----------------------------------------- |
| `qa_export.py`   | Computes QA metrics and exports artifacts |
| `qa_enforcer.py` | Applies strict threshold policy           |
| CLI `--strict`   | Enables guardrail enforcement             |
| Exit Code        | Controlled only by enforcer               |

This separation ensures:

* Testable enforcement logic
* Reusable QA artifacts
* CI-ready behavior
* Clear architectural boundaries

---

## CI Integration Example

```yaml
- name: Strict QA
  run: |
    python -m src.ingestion.qa_export \
      --timeframe all \
      --start 2025-11-01 \
      --end 2025-12-01 \
      --strict \
      --max-duplicate-keys 0 \
      --max-ohlc-violations 0
```

If integrity is violated, the CI job fails automatically.

---

## M2 Status

* Deterministic primary key enforcement
* OHLC integrity validation
* Calendar-aware coverage metrics
* Gap detection (1D and 1Min)
* Strict guardrail mode
* CI-compatible exit codes
* Artifact-based observability

This milestone transitions the pipeline from QA reporting to production-grade enforcement suitable for research and trading workflows.

---


