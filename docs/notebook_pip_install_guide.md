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

## 2. Define a Colab Data-Session Profile

In Colab, define one small profile cell before running project setup, restore,
backfill, QA, or handoff cells. The profile is runtime configuration only: it
does not create files, mutate `.env`, update `os.environ`, mount Google Drive,
restore archives, write curated data, or create project-session metadata.

```python
from pathlib import Path

FINTECH_ROOT = Path("/content/fintech-market-ingestion-demo").resolve()
CURATED_ROOT = FINTECH_ROOT / "data" / "curated"
RESEARCH_ROOT = FINTECH_ROOT / "data" / "research"
ARTIFACTS_ROOT = FINTECH_ROOT / "artifacts"
REPORTS_ROOT = FINTECH_ROOT / "reports"

DRIVE_ROOT = Path("/content/drive/MyDrive/fintech-market-ingestion").resolve()
SESSION_EXPORT_ROOT = DRIVE_ROOT / "sessions" / "colab-demo"
BACKUP_PACK_ROOT = DRIVE_ROOT / "backups"
BACKUP_PACK_ID = "backup_example"
BACKUP_PACK_DIR = BACKUP_PACK_ROOT / BACKUP_PACK_ID

START = "2024-10-01"
END = "2025-04-15"
TIMEFRAME = "1Day"
SYMBOLS = ["AAPL", "MSFT"]

SYMBOLS_PATH = FINTECH_ROOT / "configs" / "profile_symbols.txt"
QA_TIMEFRAME = "1D" if TIMEFRAME == "1Day" else "1Min"
STRATLAKE_MARKETLAKE_ROOT = CURATED_ROOT
```

Use `/content/...` for the local runtime workspace and
`/content/drive/MyDrive/...` for already-mounted Drive persistence. Local
partitioned Parquet under `CURATED_ROOT` remains the canonical working data.
Mounted Drive paths are persistence or archive locations only, and archive
backup packs remain derived, non-canonical transfer artifacts.

`CURATED_ROOT` is the local root StratLake should consume as `MARKETLAKE_ROOT`
or `--marketlake-root` after restore or ingestion has populated the local
dataset.

---

## 3. Bootstrap a Local Workspace

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

For a fresh Colab runtime, use the profile root and request the Colab-ready
workspace shape in one initialization command:

```python
!fintech-init-project \
  --root "{FINTECH_ROOT}" \
  --colab-profile \
  --with-session \
  --session-name colab-market-data
```

That creates:

```text
configs/
data/curated/
data/research/
artifacts/
reports/
notebooks/
.env.example
configs/tickers_sample.txt
```

`--colab-profile` only creates local runtime directories and generated sample
files. It does not run ingestion, QA, save, restore, archive backup, persistence
adapters, Google Drive mounting, Google APIs, OAuth, network calls, or
credential handling.

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
workspace remains the primary runtime view. Re-running `--with-session` creates
a new timestamped session manifest by default, and existing session manifests
are not overwritten. Automatic session reuse/restore within
`fintech-init-project --with-session` is deferred to later project-session
work; explicit `fintech-save-session` and `fintech-restore-session` commands
are available separately.

For mounted-path Google Drive persistence boundaries, see
[google_drive_persistence.md](google_drive_persistence.md). The adapter expects
Drive to already be mounted and does not use Google APIs or authenticate.
Explicit save/restore commands are available once you have a session ID:

```python
!fintech-init-project \
  --root "{FINTECH_ROOT}" \
  --colab-profile \
  --with-session \
  --session-name colab-market-data

!fintech-save-session \
  --root "{FINTECH_ROOT}" \
  --session-id "<session_id>" \
  --policy artifacts_and_reports \
  --adapter google-drive \
  --destination "{SESSION_EXPORT_ROOT}" \
  --dry-run

!fintech-restore-session \
  --root "{FINTECH_ROOT / 'restore_dry_run_check'}" \
  --adapter google-drive \
  --source "{SESSION_EXPORT_ROOT}" \
  --dry-run
```

Restore does not overwrite existing files unless `--force` is passed. Curated
data is excluded from saves by default. Use `--dry-run` before saving to a
mounted Drive path, especially before any curated-data policy.

After initializing the workspace, switch the notebook current directory to the
profile root before running commands that rely on workspace-relative `.env`
loading or default paths:

```python
%cd {FINTECH_ROOT}
```

Live Alpaca commands load `.env` from the current working directory. In a
profile-driven Colab notebook, run credential-loaded ingestion and backfill
commands from `FINTECH_ROOT` unless you have already populated the environment
through another secure mechanism.

For a runnable local notebook-style walkthrough that uses only tiny synthetic
files:

```bash
python examples/project_session_quickstart.py --output-root artifacts/examples/project_session_quickstart
```

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

## 4. Configure Alpaca Credentials

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
directory via `python-dotenv`. In the profile-driven Colab flow above, that
means running live Alpaca commands after `%cd {FINTECH_ROOT}`.

---

## 5. Edit Your Symbol List

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

In a profile-driven notebook, create the symbol file explicitly after
`fintech-init-project` has created `configs/`:

```python
SYMBOLS_PATH.parent.mkdir(parents=True, exist_ok=True)
SYMBOLS_PATH.write_text("\n".join(SYMBOLS) + "\n", encoding="utf-8")
```

---

## 6. Daily Backfill

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

Profile-driven Colab equivalent for `TIMEFRAME = "1Day"`:

```python
!fintech-backfill-daily \
  --symbols "{SYMBOLS_PATH}" \
  --start "{START}" \
  --end "{END}" \
  --out "{CURATED_ROOT / 'bars_daily'}" \
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

## 7. 1-Minute Backfill

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

Profile-driven Colab equivalent for `TIMEFRAME = "1Min"`:

```python
!fintech-backfill-1m \
  --symbols "{SYMBOLS_PATH}" \
  --start "{START}" \
  --end "{END}" \
  --out "{CURATED_ROOT / 'bars_1m'}" \
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

## 8. DuckDB Spot-Check

After a successful backfill, verify the output with DuckDB:

```python
import duckdb

conn = duckdb.connect()

# Daily bars — Q1 2025
df = conn.execute(f"""
    SELECT symbol, COUNT(*) AS rows, MIN(ts_utc) AS first_bar, MAX(ts_utc) AS last_bar
    FROM read_parquet('{CURATED_ROOT.as_posix()}/bars_daily/**/*.parquet', hive_partitioning=true)
    WHERE ts_utc >= TIMESTAMP '2025-01-01'
      AND ts_utc < TIMESTAMP '2025-04-01'
    GROUP BY symbol
    ORDER BY symbol
""").df()

print(df)
```

```python
# 1-minute bars — AAPL on 2025-01-02
df_1m = conn.execute(f"""
    SELECT *
    FROM read_parquet('{CURATED_ROOT.as_posix()}/bars_1m/**/*.parquet', hive_partitioning=true)
    WHERE symbol = 'AAPL'
      AND date = '2025-01-02'
    ORDER BY ts_utc
    LIMIT 10
""").df()

print(df_1m)
```

---

## 9. QA, Archive, and StratLake Handoff Examples

The framework-level QA export currently reads the standard workspace-relative
`data/curated/...` layout. In Colab, this assumes the notebook is already
running from `FINTECH_ROOT`; feed the profile values for the date window,
expected symbols file, timeframe, and artifact root:

```python
!python -m src.ingestion.qa_export \
  --timeframe "{QA_TIMEFRAME}" \
  --start "{START}" \
  --end "{END}" \
  --symbols "{SYMBOLS_PATH}" \
  --out "{ARTIFACTS_ROOT / 'qa'}"
```

Archive backup pack commands should use mounted Drive only for the pack
location and local runtime storage for the active dataset root:

```python
!fintech-backup-data validate \
  --backup-pack-dir "{BACKUP_PACK_DIR}"

!fintech-backup-data restore \
  --backup-pack-dir "{BACKUP_PACK_DIR}" \
  --restore-root "{CURATED_ROOT}" \
  --overwrite-policy fail

!fintech-backup-data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --backup-id "backup_after_session" \
  --shard-size-mb 512
```

For the full restore-first Colab sequence, including Drive mount setup,
validate/inspect-before-restore guidance, overwrite policy choices, and archive
packs versus project-session save/restore, see
[colab_archive_backup_restore.md](colab_archive_backup_restore.md).

For StratLake Trade Engine handoff, declare the local curated root rather than
the Drive backup folder:

```python
print(f"MARKETLAKE_ROOT={STRATLAKE_MARKETLAKE_ROOT}")
```

```text
CURATED_ROOT is the local root StratLake should consume as MARKETLAKE_ROOT or --marketlake-root.
```

Generate a deterministic local handoff summary after restore or backfill:

```python
!python -m src.cli.stratlake_handoff_report \
  --root "{FINTECH_ROOT}" \
  --curated-root "{CURATED_ROOT}" \
  --qa-root "{ARTIFACTS_ROOT / 'qa'}" \
  --output "{ARTIFACTS_ROOT / 'handoff' / 'stratlake_marketlake_handoff.json'}"
```

Installed console script (equivalent):

```python
!fintech-stratlake-handoff-report \
  --root "{FINTECH_ROOT}" \
  --curated-root "{CURATED_ROOT}" \
  --qa-root "{ARTIFACTS_ROOT / 'qa'}" \
  --output "{ARTIFACTS_ROOT / 'handoff' / 'stratlake_marketlake_handoff.json'}"
```

The report is derived and non-canonical. It does not run ingestion, QA,
restore, archive pack creation, network calls, or StratLake workflows.

Live Alpaca backfills require credentials and network access. Drive save,
restore, and archive steps require an already-mounted Drive path. Defining the
profile itself is CI-safe and has no side effects.

---

## 10. Workspace Layout Reference

The table below summarises which files belong to the installed package and
which are local to your workspace:

| Path | Owner | Notes |
| --- | --- | --- |
| `configs/` | **Local workspace** | Created by `fintech-init-project` |
| `configs/tickers_sample.txt` | **Local workspace** | Editable symbol list |
| `data/` | **Local workspace** | Parquet datasets |
| `data/research/` | **Local workspace** | Derived research outputs; created with `--colab-profile` or by research workflows |
| `reports/` | **Local workspace** | Failure CSV files |
| `artifacts/` | **Local workspace** | QA run artifacts |
| `notebooks/` | **Local workspace** | Optional; created with `--notebooks` or `--colab-profile` |
| `.env` | **Local workspace** | Credentials — never commit |
| `.env.example` | **Local workspace** | Credential template |
| Installed scripts | **Package** | `fintech-backfill-daily`, etc. |
| `src/` | **Package** | Python modules |

---

## 11. Troubleshooting

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
print("ALPACA_API_KEY_ID:", "SET" if os.environ.get("ALPACA_API_KEY_ID") else "NOT SET")
print(
    "ALPACA_API_SECRET_KEY:",
    "SET" if os.environ.get("ALPACA_API_SECRET_KEY") else "NOT SET",
)
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

## 12. Available Console Scripts

| Command | Description |
|---------|-------------|
| `fintech-init-project` | Bootstrap a local workspace |
| `fintech-save-session` | Save selected session files to a persistence target |
| `fintech-restore-session` | Restore selected files from a persistence target |
| `fintech-backfill-daily` | Backfill daily OHLCV bars |
| `fintech-backfill-1m` | Backfill 1-minute OHLCV bars |
| `fintech-ingest-corporate-actions` | Ingest dividend / corporate-action events |
| `fintech-build-dividend-research-mart` | Build derived dividend research mart |
| `fintech-validate-dividend-research-mart` | Validate dividend research mart (read-only) |
| `fintech-join-dividend-event-windows` | Join dividend events to bar data |

All commands also support the `python -m src.<module>` invocation for
repository-root workflows.
