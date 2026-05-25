# Notebook & Pip-Install Guide

This guide is for users who install `fintech-market-ingestion` via `pip` and
want to run backfill commands from JupyterLab, a notebook, or a clean project
folder — without checking out the full repository.

---

## 1. Install the Package

```bash
pip install fintech-market-ingestion
```

For the latest development version from the repository:

```bash
pip install git+https://github.com/christophermoverton/fintech-market-ingestion.git
```

---

## 2. Bootstrap a Local Workspace

After installing, create a local workspace with sample config files and the
standard directory layout:

```bash
fintech-init-project --root .
```

This creates the following **local** directories and files in the current
directory (`.`):

```
configs/
configs/tickers_sample.txt   ← sample symbol list (10 symbols)
data/
data/curated/                ← Parquet output root
reports/                     ← failure reports (CSV)
artifacts/                   ← QA run artifacts
.env.example                 ← credential template
```

To also create a `notebooks/` directory:

```bash
fintech-init-project --root . --notebooks
```

To also create a portable project-session manifest for notebook/cloud resume
workflows:

```bash
fintech-init-project --root . --notebooks --with-session --session-name demo
```

Session-aware bootstrap writes a metadata-only manifest under:

```text
artifacts/sessions/<session_id>/session_manifest.json
```

It does not copy curated data, run save/restore behavior, execute persistence
adapters, require Google Drive, or require Google credentials. The local
workspace remains the primary runtime view.

**These files are local and user-owned.** They are not part of the installed
package and will not be overwritten on package updates. Some backfill CLIs use
local workspace-relative default paths (for example, default `--symbols` and
`--out` locations), and those paths are always resolved relative to your
current working directory. Run commands from the workspace root created by
`fintech-init-project`, or pass explicit `--symbols` / `--out` paths.

If you want to regenerate the sample files (e.g., after deleting them):

```bash
fintech-init-project --root . --force
```

`--force` only overwrites the two generated sample files
(`configs/tickers_sample.txt` and `.env.example`). It does not delete any data
you have written to `data/`, `reports/`, or `artifacts/`.

---

## 3. Configure Alpaca Credentials

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
ALPACA_API_KEY_ID=your_api_key_id_here
ALPACA_API_SECRET_KEY=your_secret_key_here
ALPACA_FEED=iex
```

`iex` is the free-tier data feed. It covers US equities with a 15-minute
delay. Use `sip` for real-time consolidated tape (requires a paid Alpaca
subscription).

The commands below automatically load `.env` from the current working
directory via `python-dotenv`.

---

## 4. Edit Your Symbol List

`configs/tickers_sample.txt` contains 10 symbols by default. Edit it to use
the symbols you need:

```
# configs/tickers_sample.txt
AAPL
MSFT
NVDA
AMZN
GOOGL
```

Lines that start with `#` are treated as comments and ignored.

---

## 5. Daily Backfill

### Minimal Example — Q1 2025, sample symbol list

A good first run to verify connectivity and credentials before a larger job:

```bash
fintech-backfill-daily \
  --symbols configs/tickers_sample.txt \
  --start 2025-01-01 \
  --end 2025-04-01 \
  --out data/curated/bars_daily \
  --feed iex \
  --window month
```

Parquet output is written to:

```
data/curated/bars_daily/symbol=AAPL/date=2025-01-02/part-0.parquet
data/curated/bars_daily/symbol=MSFT/date=2025-01-02/part-0.parquet
...
```

### Full 50-Symbol Workflow

Replace `configs/tickers_sample.txt` with your own larger list, or copy
`configs/tickers_50.txt` from the repository:

```bash
fintech-backfill-daily \
  --symbols configs/tickers_50.txt \
  --start 2024-01-01 \
  --end 2025-01-01 \
  --out data/curated/bars_daily \
  --feed iex \
  --window month
```

Module invocation (also supported):

```bash
python -m src.ingestion.backfill_daily \
  --symbols configs/tickers_50.txt \
  --start 2024-01-01 \
  --end 2025-01-01 \
  --out data/curated/bars_daily \
  --feed iex \
  --window month
```

---

## 6. 1-Minute Backfill

### Smoke Test — 1 Day, Small Symbol List

Use this to validate your setup with minimal API cost:

```bash
fintech-backfill-1m \
  --symbols configs/tickers_sample.txt \
  --start 2025-01-02 \
  --end 2025-01-03 \
  --out data/curated/bars_1m \
  --feed iex \
  --sleep-ms 200 \
  --no-progress
```

`--sleep-ms 200` inserts a 200 ms pause between API calls to stay well within
Alpaca rate limits. `--no-progress` suppresses the progress bar, which is
cleaner in notebook output.

Parquet output is written to:

```
data/curated/bars_1m/symbol=AAPL/date=2025-01-02/part-0.parquet
...
```

Module invocation (also supported):

```bash
python -m src.ingestion.backfill_1m \
  --symbols configs/tickers_sample.txt \
  --start 2025-01-02 \
  --end 2025-01-03 \
  --out data/curated/bars_1m \
  --feed iex \
  --sleep-ms 200 \
  --no-progress
```

---

## 7. DuckDB Spot-Check

After a successful backfill, verify the output with DuckDB:

```python
import duckdb

conn = duckdb.connect()

# Daily bars — Q1 2025
df = conn.execute("""
    SELECT symbol, COUNT(*) AS rows, MIN(ts_utc) AS first_bar, MAX(ts_utc) AS last_bar
    FROM read_parquet('data/curated/bars_daily/**/*.parquet', hive_partitioning=true)
    WHERE ts_utc >= TIMESTAMP '2025-01-01'
      AND ts_utc < TIMESTAMP '2025-04-01'
    GROUP BY symbol
    ORDER BY symbol
""").df()

print(df)
```

```python
# 1-minute bars — AAPL on 2025-01-02
df_1m = conn.execute("""
    SELECT *
    FROM read_parquet('data/curated/bars_1m/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL'
      AND date = '2025-01-02'
    ORDER BY ts_utc
    LIMIT 10
""").df()

print(df_1m)
```

---

## 8. Workspace Layout Reference

The table below summarises which files belong to the installed package and
which are local to your workspace:

| Path | Owner | Notes |
| --- | --- | --- |
| `configs/` | **Local workspace** | Created by `fintech-init-project` |
| `configs/tickers_sample.txt` | **Local workspace** | Editable symbol list |
| `data/` | **Local workspace** | Parquet datasets |
| `reports/` | **Local workspace** | Failure CSV files |
| `artifacts/` | **Local workspace** | QA run artifacts |
| `notebooks/` | **Local workspace** | Optional; created with `--notebooks` |
| `.env` | **Local workspace** | Credentials — never commit |
| `.env.example` | **Local workspace** | Credential template |
| Installed scripts | **Package** | `fintech-backfill-daily`, etc. |
| `src/` | **Package** | Python modules |

---

## 9. Troubleshooting

### Wrong working directory

The backfill commands resolve `configs/`, `data/`, `reports/`, etc. relative
to the **current working directory**, not to the installed package. Run
commands from the directory where you ran `fintech-init-project`.

In a notebook, set the working directory explicitly:

```python
import os
os.chdir("/path/to/your/workspace")
```

### Missing Alpaca credentials

If you see an `AuthenticationError` or `401` response, your `.env` file is
either missing, in the wrong directory, or contains incorrect keys.

Check that `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` are set:

```python
import os
from dotenv import load_dotenv
load_dotenv()
print(os.environ.get("ALPACA_API_KEY_ID", "NOT SET"))
```

### Missing symbols file

If the command exits with `FileNotFoundError: configs/tickers_sample.txt`, run
`fintech-init-project --root .` first, or pass an explicit `--symbols` path
that exists.

### Package installed in a different Jupyter kernel

If `fintech-backfill-daily` is not found in a notebook shell cell, the active
Jupyter kernel may be using a different Python environment than the one where
you installed the package. Install into the kernel's environment:

```bash
# From inside the notebook
import sys
!{sys.executable} -m pip install fintech-market-ingestion
```

Then restart the kernel.

### Empty API results

If the command completes but writes no Parquet files, check:

- The date range includes market trading days (not just weekends/holidays).
- The symbols in your file are valid US equity tickers on Alpaca.
- Your Alpaca account has data access for the selected feed (`iex` or `sip`).
- The Alpaca API status page at <https://status.alpaca.markets/> for outages.

---

## 10. Available Console Scripts

| Command | Description |
|---------|-------------|
| `fintech-init-project` | Bootstrap a local workspace |
| `fintech-backfill-daily` | Backfill daily OHLCV bars |
| `fintech-backfill-1m` | Backfill 1-minute OHLCV bars |
| `fintech-ingest-corporate-actions` | Ingest dividend / corporate-action events |
| `fintech-build-dividend-research-mart` | Build derived dividend research mart |
| `fintech-validate-dividend-research-mart` | Validate dividend research mart (read-only) |
| `fintech-join-dividend-event-windows` | Join dividend events to bar data |

All commands also support the `python -m src.<module>` invocation for
repository-root workflows.
