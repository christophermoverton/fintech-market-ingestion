# FinTech Market Ingestion: Alpaca → Parquet → DuckDB + QA Observability

A production-style market data ingestion and validation framework for historical OHLCV bars (Daily + 1-Minute) using Alpaca market data. The pipeline writes curated, partitioned Parquet datasets and provides a structured QA layer with artifact-based observability and optional strict enforcement suitable for CI gating and trading research workflows.

For cross-platform contributor setup and validation, see [docs/cross_platform_contributor_validation.md](docs/cross_platform_contributor_validation.md). For setup, packaging, linting, build validation, and future publishing boundaries, see [docs/packaging_pypi_readiness.md](docs/packaging_pypi_readiness.md). For the focused M5 release checklist, see [docs/m5_release_readiness.md](docs/m5_release_readiness.md). For the focused M4 validation checklist, see [docs/m4_release_readiness.md](docs/m4_release_readiness.md).

---

## Architecture Overview

```
Alpaca API
    ↓
Alpaca Client (retry + pagination)
    ↓
Normalization Layer (UTC + dedupe)
    ↓
Partitioned Parquet (symbol/year or symbol/date)
    ↓
DuckDB Analytics + QA Observability
```

---

## Current Capabilities

###  Alpaca Historical Market Data Client

* Auth via `.env`
* Supports: `symbol`, `start`, `end`, `timeframe` (`1Day`, `1Min`), `feed` (default: `iex`)
* Automatic pagination
* Exponential backoff for:

  * HTTP 429 (rate limiting)
  * HTTP 5xx (server errors)
  * network timeouts
* Returns results as a pandas DataFrame

###  Windowed Daily Backfill Pipeline

* Iterates over a 50-ticker universe
* Fetches daily bars in monthly windows
* Normalizes into a canonical schema (UTC enforced)
* Deterministic dedupe on primary key:

  ```
  (symbol, ts_utc, timeframe)
  ```
* Writes partitioned Parquet:

  ```
  data/curated/bars_daily/symbol=XYZ/year=YYYY/
  ```
* Safe to re-run (idempotent)

###  Windowed 1-Minute Backfill Pipeline

* Day-windowed ingestion for intraday OHLCV bars
* Failure isolation per (symbol, date)
* Restartable + rate-limit safe
* Writes partitioned Parquet:

  ```
  data/curated/bars_1m/symbol=XYZ/date=YYYY-MM-DD/
  ```

###  Partitioned Parquet Storage

* Implemented via `pyarrow.write_to_dataset`
* Uses `delete_matching` to safely overwrite partitions
* DuckDB-compatible queries over glob paths

###  QA Layer + Artifact-Based Observability (M2)

* Duplicate primary key detection
* OHLC integrity checks
* Timestamp sanity / ordering checks
* Gap detection (daily + intraday)
* Coverage metrics (calendar-aware)
* Deterministic artifacts per QA run:

  ```
  artifacts/qa/<run_id>/
    qa_summary_by_symbol.csv
    qa_summary_global.csv
    qa_coverage_by_symbol.csv
  ```
* Optional strict enforcement mode (CI-friendly)

### Corporate Actions Dividend Ingestion (M3)

M3 adds a separate Alpaca corporate-actions ingestion path for dividend events. Corporate actions are event-based issuer/security records, not OHLCV bars, trades, or quotes.

Supported dividend event types:

```text
cash_dividend
stock_dividend
```

The corporate-actions client supports both flat Alpaca responses and nested
dividend groups under `corporate_actions.cash_dividends` and
`corporate_actions.stock_dividends`. Top-level `cash_dividends` and
`stock_dividends` groups are also accepted. Missing Alpaca currency on
cash-dividend rows defaults the normalized `currency` field to `USD`, with the
defaulting count recorded in dividend metadata.

Patch release `0.5.1` includes this nested Alpaca dividend response support,
the explicit cash-dividend missing-currency policy, metadata counters for
nested responses and currency defaulting, and preserved flat/list response
compatibility.

Live CLI usage:

```bash
fintech-ingest-corporate-actions \
  --symbols AAPL MSFT SPY \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --types cash_dividend stock_dividend \
  --output-root data/curated/corporate_actions/dividends
```

The existing module invocation remains supported:

```bash
python -m src.cli.ingest_corporate_actions \
  --symbols AAPL MSFT SPY \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --types cash_dividend stock_dividend \
  --output-root data/curated/corporate_actions/dividends
```

Expected outputs:

```text
data/curated/corporate_actions/dividends/dividends.parquet
data/curated/corporate_actions/dividends/metadata.json
```

Derived research mart output is also available for symbol and year analysis:

```text
data/research/corporate_actions/dividends/
```

Build the derived mart from an existing curated dividend snapshot with:

```bash
python -m src.cli.build_dividend_research_mart \
  --snapshot-root data/curated/corporate_actions/dividends \
  --research-root data/research/corporate_actions/dividends
```

Installed console script:

```bash
fintech-build-dividend-research-mart \
  --snapshot-root data/curated/corporate_actions/dividends \
  --research-root data/research/corporate_actions/dividends
```

Validate and inspect the derived mart without mutating it:

```bash
python -m src.cli.validate_dividend_research_mart \
  --research-root data/research/corporate_actions/dividends
```

Installed console script:

```bash
fintech-validate-dividend-research-mart \
  --research-root data/research/corporate_actions/dividends
```

The validation command is read-only and reports validation status in its JSON
`valid` field.

Join local dividend events to local bar data as a derived research output:

```bash
python -m src.cli.join_dividend_event_windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-path data/research/corporate_actions/dividend_event_windows/event_windows.parquet
```

Installed console script:

```bash
fintech-join-dividend-event-windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-path data/research/corporate_actions/dividend_event_windows/event_windows.parquet
```

The join command is local, credential-free, and does not mutate canonical
dividend snapshots, research marts, or bar inputs.

The deterministic curated snapshot remains the canonical ingestion output.

For the full schema, metadata contract, CLI arguments, and a CI-safe sample-data example, see `docs/corporate_actions_dividends.md`.

Dividend records are event evidence. See `docs/corporate_actions_dividends.md` for point-in-time research semantics and adjusted-return boundaries.

Derived dividend-to-bars event-window joins are available for research workflows via `src.ingestion.dividend_event_window`.

---

## Packaging and Developer Setup

The preferred contributor workflow is editable install with the development dependency group:

```bash
python -m pip install -e ".[dev]"
```

That setup supports the installed console script and the existing module invocation:

```bash
fintech-ingest-corporate-actions --help
python -m src.cli.ingest_corporate_actions --help
```

Run the cross-platform validation wrapper before opening a pull request:

```bash
python scripts/validate.py
```

The wrapper includes repository hygiene checks for LF line endings, generated
outputs accidentally tracked by Git, local absolute paths, and credential files.
You can run those checks directly with:

```bash
python scripts/check_repo_hygiene.py
```

To smoke-test the built wheel locally without publishing:

```bash
python -m build
python scripts/smoke_test_wheel.py
```

For a full cross-platform contributor workflow, see [docs/cross_platform_contributor_validation.md](docs/cross_platform_contributor_validation.md). For a packaging and PyPI-readiness walkthrough, including validation commands, build inspection, and cleanup, see [docs/packaging_pypi_readiness.md](docs/packaging_pypi_readiness.md). The M5 release-readiness checklist lives in [docs/m5_release_readiness.md](docs/m5_release_readiness.md), and the M4 deterministic release-readiness checklist lives in [docs/m4_release_readiness.md](docs/m4_release_readiness.md).

If you need a frozen environment for reproduction, `requirements.txt` is available as an optional path, but it is not the preferred development workflow for contributors.

---

# QA Export CLI Usage

The repository includes a framework-level QA export command that computes integrity metrics and writes deterministic artifacts per run.

Artifacts are written to:

```
artifacts/qa/<run_id>/
  qa_summary_by_symbol.csv
  qa_summary_global.csv
  qa_coverage_by_symbol.csv
```

---

## Observability Mode (Default)

Exports QA metrics but does **not** fail the pipeline.

```bash
python -m src.ingestion.qa_export \
  --timeframe all \
  --start 2025-11-01 \
  --end 2025-12-01
```

You may also run for a single timeframe:

### Daily Only

```bash
python -m src.ingestion.qa_export \
  --timeframe 1D \
  --start 2025-11-01 \
  --end 2025-12-01
```

### 1-Minute Only

```bash
python -m src.ingestion.qa_export \
  --timeframe 1Min \
  --start 2025-11-01 \
  --end 2025-12-01
```

---

## Strict Enforcement Mode (CI / Guardrail Mode)

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

### Exit Codes

| Condition                               | Exit Code |
| --------------------------------------- | --------- |
| PASS (within thresholds)                | 0         |
| WARN (coverage/gap thresholds exceeded) | 0         |
| FAIL (strict integrity violation)       | 1         |

Strict mode ensures:

* Duplicate primary keys fail the pipeline
* OHLC violations fail the pipeline
* QA artifacts are still written for debugging
* CI jobs automatically fail when data integrity is compromised

---

## Example CI Integration

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

If integrity rules are violated, the CI job exits with code `1`.

---

## Why This Matters

In trading and backtesting systems:

* Duplicate bars distort indicators (EMA, RSI, VWAP, etc.)
* OHLC violations corrupt return calculations
* Silent ingestion errors invalidate research
* Coverage gaps can bias signal evaluation

The `qa_export` CLI formalizes dataset observability and enables production-grade guardrails before any modeling or execution layer consumes the data.

---

## Universe Selection Criteria

The project operates on a curated universe (currently 50 tickers) optimized for stable historical availability.

Document:

* Selection logic (liquidity + large-cap bias)
* Exclusion rules
* Intended expansion strategy

> Tip: include this as `docs/universe.md` so it’s easy to audit and evolve.

---

##  Alpaca Market Data Client

Reusable Alpaca historical market data client:

```
src/ingestion/alpaca_client.py
```

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

## Setup

### 1) Create + Activate Virtual Environment (Windows)

```bash
python -m venv venv
.\venv\Scripts\activate
```

### 2) Install Editable Package + Development Tools

For local development, install the project in editable mode with the optional
development dependencies:

```bash
python -m pip install -e ".[dev]"
```

This keeps the current `src.*` import layout available while preparing the
project for standard Python build tooling.

### 3) Install Frozen Environment (optional)

`requirements.txt` records a fuller pinned working environment, including
notebook and exploratory tooling. Use it when you need to reproduce that exact
environment:

```bash
python -m pip install -r requirements.txt
```

### 4) Export Dependencies (when updating your environment)

If you install new packages and want to pin exact versions:

```bash
pip freeze > requirements.txt
```

### 5) Lint and Format Checks

Ruff provides the baseline lint and formatting checks for M4 quality gates:

```bash
ruff check src tests examples
ruff format --check src tests examples
```

To apply Ruff formatting locally:

```bash
ruff format src tests examples
```

### 6) Package Build Validation

Build the source distribution and wheel locally before any release preparation:

```bash
python -m build
```

Build outputs are written under `dist/`. Inspect artifact contents before any
future TestPyPI or PyPI publishing step:

```bash
tar tf dist/*.tar.gz
python -m zipfile --list dist/*.whl
```

PowerShell inspection alternatives:

```powershell
Get-ChildItem dist\*.tar.gz | ForEach-Object { tar tf $_.FullName }
Get-ChildItem dist\*.whl | ForEach-Object { python -m zipfile --list $_.FullName }
```

The package artifacts must not include credentials, `.env`, generated datasets,
local artifacts, reports, caches, virtual environments, or build outputs.

Optional wheel smoke test:

```bash
python -m pip install dist/*.whl
python -m src.cli.ingest_corporate_actions --help
```

Clean generated build artifacts when finished:

```bash
rm -rf dist build *.egg-info
```

PowerShell equivalent:

```powershell
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force *.egg-info -ErrorAction SilentlyContinue
```

---

## Configuration (.env)

Create a `.env` file in the project root:

```bash
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_DATA_FEED=iex
```

---

## Project Layout

```
data/
  curated/
    bars_daily/
    bars_1m/

artifacts/
  qa/

reports/

src/
  ingestion/
  qa/
  utils/

notebooks/
```

---

## Daily Backfill

### CLI

```bash
python -m src.ingestion.backfill_daily --start 2023-01-01 --end 2026-01-01
```

### Storage Layout

```
data/curated/bars_daily/symbol=XYZ/year=YYYY/part-*.parquet
```

---

## 1-Minute Historical Backfill

Windowed ingestion of 1-minute OHLCV bars (IEX-compatible) into curated Parquet partitions.

Designed for:

* Idempotent re-runs
* Restartable backfills
* Rate-limit safe API usage
* Failure isolation
* DuckDB/Pandas/backtesting compatibility

### Data Contract (Canonical Schema)

| Column    | Type            | Description                      |
| --------- | --------------- | -------------------------------- |
| symbol    | string          | Ticker symbol                    |
| ts_utc    | timestamp (UTC) | Bar open time in UTC             |
| open      | float           | Open price                       |
| high      | float           | High price                       |
| low       | float           | Low price                        |
| close     | float           | Close price                      |
| volume    | float/int       | Trade volume                     |
| source    | string          | e.g., `alpaca_iex`               |
| timeframe | string          | `"1Min"`                         |
| date      | string          | `YYYY-MM-DD` derived from ts_utc |

Primary key (idempotency):

```
(symbol, ts_utc, timeframe)
```

### Partition Layout

```
data/curated/bars_1m/
  symbol=XYZ/
    date=YYYY-MM-DD/
      part-*.parquet
```

### CLI Usage

```bash
python -m src.ingestion.backfill_1m \
  --start 2024-01-01 \
  --end 2024-04-01
```

Optional flags:

```bash
--symbols configs/tickers_50.txt
--max-symbols 5
--sleep-ms 100
--no-progress
```

### Failure Logging

Failed (symbol, date) requests are recorded:

```
reports/backfill_1m_failures_YYYYMMDD_HHMMSS.csv
```

Backfill continues even when individual symbol/day fetches fail.

---

## DuckDB Analytics Validation

Example: validate per-symbol ranges and row counts directly over Parquet:

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

## Data Quality & Validation (QA Layer)

Validates curated market data after ingestion runs (daily and 1-minute).

Ensures:

* Primary key uniqueness
* OHLC integrity
* Timestamp ordering
* Coverage / gap detection
* Repeatable reporting
* Optional strict enforcement mode

### Supported Datasets

| Timeframe  | Path                                   |
| ---------- | -------------------------------------- |
| Daily (1D) | `data/curated/bars_daily/**/*.parquet` |
| 1-Minute   | `data/curated/bars_1m/**/*.parquet`    |

Expected columns:

```
symbol, ts_utc, open, high, low, close, volume, source, timeframe
```

Primary key:

```
(symbol, ts_utc, timeframe)
```

---

## QA Checks Implemented

### Duplicate Detection

Detects duplicates on:

```
(symbol, ts_utc, timeframe)
```

* Reports per symbol
* Strict mode fails if duplicates exist

### OHLC Integrity Rules

Validates:

* `high >= max(open, close)`
* `low <= min(open, close)`
* `high >= low`
* `open, high, low, close > 0`
* `volume >= 0`
* Required fields non-null

### Timestamp Sanity

* `ts_utc` non-null
* Out-of-order detection per symbol

### Coverage / Gap Detection

#### Daily (1D)

* Calendar-aware expected sessions (XNYS default)

#### 1-Minute (1Min) — Session-Aware Gap Logic

Gap metrics computed within `(symbol, session_date)` using timestamp deltas:

* `gap_count`
* `gap_segments`
* `max_gap_len`

This prevents overnight/weekend closures from being counted as gaps.

> Note on Alpaca IEX feed: missing minute bars may reflect “no trades” rather than corruption. Tune thresholds accordingly.

---

## QA Summary Export (Framework-Level Observability)

QA exports are written to:

```
artifacts/qa/<run_id>/
  qa_summary_by_symbol.csv
  qa_summary_global.csv
  qa_coverage_by_symbol.csv
```

Global summary includes:

* total_rows / unique_rows / duplicate_rows
* total_gap_count
* total_ohlc_violation_count
* pct_symbols_below_coverage_threshold
* overall_status (PASS / WARN / FAIL)

Run IDs are deterministic from:

```
dataset_name + interval + start_ts + end_ts + calendar
```

---

## Strict QA Mode (Guardrail Enforcement)

When strict mode is enabled:

* Duplicate primary keys → FAIL (exit code 1)
* OHLC violations over threshold → FAIL (exit code 1)
* Artifacts still written for debugging
* CI-compatible gating

### CLI

```bash
python -m src.ingestion.qa_export \
  --timeframe all \
  --start 2025-11-01 \
  --end 2025-12-01 \
  --strict \
  --max-duplicate-keys 0 \
  --max-ohlc-violations 0
```

---

## Tests

Run unit tests:

```bash
pytest -q
```

Tests cover:

* Normalization logic (canonical schema + UTC + sorting)
* Duplicate key detection
* OHLC violation detection
* Strict enforcement path

---

## DuckDB Sanity Queries Notebook

Notebook:
`notebooks/01_duckdb_sanity_queries.ipynb`

Validates:

* Schema presence and timestamp parsing
* Coverage + completeness
* Duplicate primary key contract
* Basic validity constraints
* Example analytics with window functions

Exports:

```
reports/duckdb_sanity_summary.csv
```

---

## Roadmap / Future Enhancements

* Fully session-aware expected-minute index comparison
* Extended-hours handling
* Per-run historical QA trend table
* Machine-readable JSON summary export
* CI auto-fail policies based on `qa_summary_global.csv`
