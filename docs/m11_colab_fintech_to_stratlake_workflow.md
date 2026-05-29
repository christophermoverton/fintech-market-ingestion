# M11 Colab Fintech To StratLake Workflow

This guide documents the fintech-side lifecycle for Colab sessions where
`fintech-market-ingestion` prepares local curated Parquet data for downstream
StratLake use.

## 1. Overview

Recommended lifecycle:

1. Start a fresh Colab runtime.
2. Install `fintech-market-ingestion`.
3. Mount Google Drive if archive/session persistence lives there.
4. Define the Colab data-session profile.
5. Initialize the local fintech workspace.
6. Run pre-restore `fintech-notebook-doctor` checks.
7. Choose a data path:
   - restore-first archive path (credential-free);
   - optional live backfill path (credentials/network required).
8. Run post-restore or post-backfill dataset doctor checks.
9. Run fintech QA over local curated data.
10. Generate the StratLake handoff report.
11. Pass local `CURATED_ROOT` (or handoff `stratlake_marketlake_root`) to
    StratLake as `MARKETLAKE_ROOT` / `--marketlake-root`.
12. End the session with either archive pack creation and/or session save.

## 2. Storage Roles And Boundaries

- Local runtime storage under `/content/fintech-market-ingestion-demo` is the
  active workspace and canonical local working dataset root.
- Mounted Google Drive under `/content/drive/MyDrive/fintech-market-ingestion`
  is persistence/archive storage only.
- Archive backup packs are derived, non-canonical transfer artifacts.
- Handoff reports are derived, non-canonical diagnostic metadata.
- Session save/restore is for lightweight continuity, not large curated-data
  transport by default.

Fintech owns ingestion, local curated Parquet, archive backup/restore, QA,
doctor diagnostics, and handoff metadata. StratLake owns downstream feature and
research workflows.

## 3. Define The Colab Data-Session Profile

```python
from pathlib import Path

FINTECH_ROOT = Path("/content/fintech-market-ingestion-demo").resolve()
CURATED_ROOT = FINTECH_ROOT / "data" / "curated"
ARTIFACTS_ROOT = FINTECH_ROOT / "artifacts"
REPORTS_ROOT = FINTECH_ROOT / "reports"

DRIVE_ROOT = Path("/content/drive/MyDrive/fintech-market-ingestion").resolve()
BACKUP_PACK_ROOT = DRIVE_ROOT / "backups"
BACKUP_PACK_ID = "backup_example"
BACKUP_PACK_DIR = BACKUP_PACK_ROOT / BACKUP_PACK_ID

SYMBOLS_PATH = FINTECH_ROOT / "configs" / "tickers_sample.txt"
START = "2025-01-01"
END = "2025-02-01"
TIMEFRAME = "1D"
```

## 4. Install Package And Mount Drive

Install package:

```python
%pip install fintech-market-ingestion
```

Mount Drive only when needed for persistence/archive paths. This is notebook
setup, not package behavior:

```python
from google.colab import drive

drive.mount("/content/drive")
```

## 5. Initialize The Fintech Local Workspace

```python
!fintech-init-project \
  --root "{FINTECH_ROOT}" \
  --colab-profile \
  --with-session \
  --session-name colab-market-data

%cd {FINTECH_ROOT}
```

Initialization creates local directories and generated sample files only. It
does not run ingestion, restore, archive, QA, Drive operations, network calls,
or credential logic.

## 6. Pre-Restore Notebook Doctor

Run readiness checks before restore/backfill:

```python
!fintech-notebook-doctor \
  --root "{FINTECH_ROOT}" \
  --drive-root "{DRIVE_ROOT}" \
  --archive-root "{BACKUP_PACK_ROOT}" \
  --check-archive-root \
  --check-secrets \
  --restore-root "{CURATED_ROOT}"
```

Notes:

- Pre-restore checks should usually not include `--expect-dataset` unless an
  intentional fail is desired.
- Secret checks report `SET` / `NOT SET` only and never print secret values.
- Missing secrets are warnings unless `--require-secrets` is provided.
- Doctor is read-only and does not mount Drive, validate archive checksums,
  restore files, run ingestion, or run QA.

## 7. Choose Data Path

### 7a. Restore-First Archive Path

Validate and inspect pack first:

```python
!fintech-backup-data validate \
  --backup-pack-dir "{BACKUP_PACK_DIR}"

!fintech-backup-data inspect \
  --backup-pack-dir "{BACKUP_PACK_DIR}"
```

Restore to local runtime curated root:

```python
!fintech-backup-data restore \
  --backup-pack-dir "{BACKUP_PACK_DIR}" \
  --restore-root "{CURATED_ROOT}" \
  --overwrite-policy fail
```

After restore, local partitioned Parquet under `CURATED_ROOT` is canonical
working data.

### 7b. Optional Live Backfill Path

Optional path for live data ingestion. Requires Alpaca credentials and network
access. Restore-first remains the credential-free path.

```python
!fintech-backfill-daily \
  --symbols "{SYMBOLS_PATH}" \
  --start "{START}" \
  --end "{END}" \
  --out "{CURATED_ROOT / 'bars_daily'}" \
  --window month
```

Optional 1-minute path:

```python
!fintech-backfill-1m \
  --symbols "{SYMBOLS_PATH}" \
  --start "{START}" \
  --end "{END}" \
  --out "{CURATED_ROOT / 'bars_1m'}" \
  --no-progress
```

## 8. Post-Restore Or Post-Backfill Dataset Doctor

Use expected datasets when they should now exist:

```python
!fintech-notebook-doctor \
  --root "{FINTECH_ROOT}" \
  --check-curated-root \
  --expect-dataset bars_daily \
  --expect-dataset bars_1m
```

Missing expected datasets intentionally return `fail`.

Deterministic JSON variant:

```python
!fintech-notebook-doctor \
  --root "{FINTECH_ROOT}" \
  --check-curated-root \
  --expect-dataset bars_daily \
  --json
```

## 9. Run Fintech QA On Local Curated Data

```python
!python -m src.ingestion.qa_export \
  --timeframe "{TIMEFRAME}" \
  --start "{START}" \
  --end "{END}" \
  --symbols "{SYMBOLS_PATH}" \
  --out "{ARTIFACTS_ROOT / 'qa'}"
```

QA writes artifacts under `ARTIFACTS_ROOT` and does not mutate curated Parquet.
For expanded QA examples, see
[colab_archive_backup_restore.md](colab_archive_backup_restore.md).

## 10. Generate StratLake Handoff Report

```python
!fintech-stratlake-handoff-report \
  --root "{FINTECH_ROOT}" \
  --curated-root "{CURATED_ROOT}" \
  --qa-root "{ARTIFACTS_ROOT / 'qa'}" \
  --output "{ARTIFACTS_ROOT / 'handoff' / 'stratlake_marketlake_handoff.json'}"
```

Inspect report:

```python
import json

handoff_path = ARTIFACTS_ROOT / "handoff" / "stratlake_marketlake_handoff.json"
handoff = json.loads(handoff_path.read_text())
handoff["stratlake_marketlake_root"]
```

Notes:

- Handoff report is derived and non-canonical.
- Default `generated_at_utc` is `null` unless explicitly provided.
- QA run selection is deterministic lexical ordering when QA artifacts exist.
- StratLake must still validate requested universe/date/timeframe.

## 11. Use Local Curated Root In StratLake

Use local `CURATED_ROOT`, or `stratlake_marketlake_root` from the handoff
report, as StratLake `MARKETLAKE_ROOT` / `--marketlake-root`.

Do not point StratLake at the Drive backup-pack directory. Downstream
StratLake notebook/session initialization, feature construction, and research
validation are outside this fintech guide.

## 12. End-Of-Session Choices

Use session save/restore for configs, reports, lightweight artifacts, and
notebook continuity.

Dry-run save example:

```python
!fintech-save-session \
  --root "{FINTECH_ROOT}" \
  --session-id "<session_id>" \
  --policy artifacts_and_reports \
  --adapter google-drive \
  --destination "{DRIVE_ROOT / 'sessions' / 'colab-market-data'}" \
  --dry-run
```

Use archive backup packs for large curated datasets and restore-to-local-first
workflows:

```python
!fintech-backup-data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --backup-id backup_after_session \
  --shard-size-mb 512
```

## 13. Troubleshooting

- Doctor pre-restore fails on expected datasets:
  remove `--expect-dataset` until after restore/backfill.
- Restore fails with overwrite policy `fail`:
  verify restore target emptiness with `--restore-root` doctor check.
- QA finds low coverage or missing symbols:
  confirm restored/backfilled dataset roots and requested date window.
- Handoff report has `qa.status = unknown`:
  check QA output root and run-id artifact presence under `artifacts/qa`.

## 14. M11 Readiness Checklist

See [m11_release_readiness.md](m11_release_readiness.md).
