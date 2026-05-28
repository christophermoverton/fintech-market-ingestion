# Colab Archive Backup And Restore Workflow

Milestone 10 archive backup packs are designed for Colab and notebook sessions
where Google Drive is useful for durable storage but slow as the active working
layer for partitioned Parquet data. A curated market dataset can contain many
small files. Copying those files one by one to or from Drive is often much
slower than transferring a smaller number of archive shards.

The restore-first Colab pattern is:

1. Start from a fresh Colab runtime and install `fintech-market-ingestion`.
2. Mount Google Drive only if the backup pack lives there.
3. Define the Colab data-session profile from
   [notebook_pip_install_guide.md](notebook_pip_install_guide.md).
4. Initialize the local runtime workspace with `fintech-init-project
   --colab-profile`.
5. Validate and inspect a backup pack on mounted Drive before restore.
6. Restore curated data into local runtime storage at `CURATED_ROOT`.
7. Run post-restore QA against local restored curated data before handoff.
8. Generate a local StratLake handoff report from restored/backfilled curated
  data.
9. Review QA and handoff artifacts and decide block-versus-warn readiness for
  downstream use.
10. Run local QA, research, analysis, or downstream handoff workflows against
  local files.
11. Optionally create a fresh backup pack back to mounted Drive when finished.

Local partitioned Parquet remains the canonical working dataset after restore.
Archive backup packs are derived, non-canonical transfer artifacts.

## Storage Roles

Use the Colab data-session profile from
[notebook_pip_install_guide.md](notebook_pip_install_guide.md) to name these
roots once. Use local runtime storage for the active project workspace:

```text
/content/fintech-market-ingestion-demo
/content/fintech-market-ingestion-demo/data/curated
```

Use mounted Google Drive as an archival checkpoint location:

```text
/content/drive/MyDrive/fintech-market-ingestion/backups
```

Do not use a Drive-mounted folder as the active Parquet working root for
performance-sensitive workflows. Restore archive packs into local runtime
storage first, then run local workflows from that restored dataset root.

The backup APIs and CLI treat Drive as an already-mounted filesystem path. They
do not mount Drive, request Google Drive API credentials, use OAuth, contact a
remote service, or run background synchronization.

## Recommended Colab Cell Sequence

This sequence assumes the Issue #83 profile cell has already defined
`FINTECH_ROOT`, `CURATED_ROOT`, `DRIVE_ROOT`, `BACKUP_PACK_ROOT`, and
`BACKUP_PACK_DIR`:

```python
from pathlib import Path

FINTECH_ROOT = Path("/content/fintech-market-ingestion-demo").resolve()
CURATED_ROOT = FINTECH_ROOT / "data" / "curated"
DRIVE_ROOT = Path("/content/drive/MyDrive/fintech-market-ingestion").resolve()
BACKUP_PACK_ROOT = DRIVE_ROOT / "backups"
BACKUP_PACK_ID = "backup_example"
BACKUP_PACK_DIR = BACKUP_PACK_ROOT / BACKUP_PACK_ID
```

### 1. Mount Drive If Needed

In Colab, mounting Drive is optional notebook setup. It is not part of the
project backup API.

```python
from google.colab import drive

drive.mount("/content/drive")
```

### 2. Initialize The Local Runtime Workspace

Initialize the local workspace under `/content/...` before restore. This
creates the expected local directories for curated data, research outputs,
artifacts, reports, configs, and notebooks. It does not run ingestion, QA, save,
restore, archive, Drive, network, or credential behavior.

```python
!fintech-init-project \
  --root "{FINTECH_ROOT}" \
  --colab-profile \
  --with-session \
  --session-name colab-market-data
```

Then use the local runtime workspace as the notebook current directory for
workspace-relative commands:

```python
%cd {FINTECH_ROOT}
```

Run a read-only notebook readiness preflight before validation and restore:

```python
!fintech-notebook-doctor \
  --root "{FINTECH_ROOT}" \
  --drive-root "{DRIVE_ROOT}" \
  --archive-root "{BACKUP_PACK_ROOT}" \
  --check-archive-root \
  --check-secrets \
  --restore-root "{CURATED_ROOT}"
```

Use `--json` for deterministic machine-readable output. The doctor is read-only:
it does not mount Drive, call Google APIs, validate archive checksums, restore
files, run validation/restore/QA/handoff, or mutate local/Drive files, session
metadata, `.env`, or environment values. Secret checks report `SET` / `NOT SET`
only.

Use dataset expectations after restore or after local backfill when datasets are
expected to exist:

```python
!fintech-notebook-doctor \
  --root "{FINTECH_ROOT}" \
  --check-curated-root \
  --expect-dataset bars_daily \
  --expect-dataset bars_1m
```

Missing expected datasets intentionally produce `fail` status.

### 3. Validate The Backup Pack On Drive

Validate before restore so missing shards, checksum mismatches, malformed ZIP
files, or unsafe member paths fail before local data is changed.

```python
!python -m src.cli.backup_data validate \
  --backup-pack-dir "{BACKUP_PACK_DIR}"
```

The installed console script is equivalent when the package is installed:

```python
!fintech-backup-data validate \
  --backup-pack-dir "{BACKUP_PACK_DIR}"
```

Validation is read-only. It checks that `manifest.json` exists and is
well-formed, that the pack identifies itself as derived/non-canonical, that
required shards exist, that shard checksums and ZIP members are safe and
consistent with the manifest, and that archive member paths cannot escape the
restore root.

### 4. Inspect Pack Contents

Inspect the pack to confirm the included datasets, shard count, byte totals,
checksum algorithm, and restore hints before writing any local curated files.

```python
!python -m src.cli.backup_data inspect \
  --backup-pack-dir "{BACKUP_PACK_DIR}"
```

The installed console script is equivalent:

```python
!fintech-backup-data inspect \
  --backup-pack-dir "{BACKUP_PACK_DIR}"
```

### 5. Restore Into Local Runtime Storage

Restore into the local dataset root that normal project commands should use.
The restore root represents the target dataset root; the restore command does
not add another `source_dataset_root` nesting layer.

```python
!python -m src.cli.backup_data restore \
  --backup-pack-dir "{BACKUP_PACK_DIR}" \
  --restore-root "{CURATED_ROOT}" \
  --overwrite-policy fail
```

The installed console script is equivalent:

```python
!fintech-backup-data restore \
  --backup-pack-dir "{BACKUP_PACK_DIR}" \
  --restore-root "{CURATED_ROOT}" \
  --overwrite-policy fail
```

Overwrite policies:

| Policy | Behavior |
| --- | --- |
| `fail` | Default and recommended for fresh Colab runtimes. Fail before final writes if any target file already exists. |
| `replace` | Replace files present in the archive and leave unrelated files alone. Use only when replacing archive-covered local files is intentional. |
| `merge` | Skip existing files only when they match the manifest checksum, and fail if an existing file differs. Use only when you understand the existing local state. |

Restore does not delete unrelated local files.

### 6. Run Post-Restore QA Before Handoff

After restore, validate local curated data before downstream analysis or
StratLake handoff. The QA command is read-only with respect to restored Parquet
files and writes diagnostics to artifact outputs only.

The current QA CLI surface is:

```python
!python -m src.ingestion.qa_export --help
```

Key arguments for post-restore validation:

- `--timeframe` with `1D`, `1Min`, or `all`
- `--start` and `--end` for the requested window
- `--symbols` for expected symbol coverage
- `--out` for artifact output root

Current behavior reads from workspace-relative curated paths:

```text
data/curated/bars_daily/**/*.parquet
data/curated/bars_1m/**/*.parquet
```

So run QA from the initialized local workspace root and keep the restore target
aligned with that workspace:

```python
%cd {FINTECH_ROOT}

assert CURATED_ROOT == FINTECH_ROOT / "data" / "curated"
```

Daily-bars QA with profile variables:

```python
QA_TIMEFRAME = "1D"

!python -m src.ingestion.qa_export \
  --timeframe "{QA_TIMEFRAME}" \
  --start "{START}" \
  --end "{END}" \
  --symbols "{SYMBOLS_PATH}" \
  --out "{ARTIFACTS_ROOT / 'qa'}"
```

1-minute QA is supported on the same surface:

```python
QA_TIMEFRAME = "1Min"

!python -m src.ingestion.qa_export \
  --timeframe "{QA_TIMEFRAME}" \
  --start "{START}" \
  --end "{END}" \
  --symbols "{SYMBOLS_PATH}" \
  --out "{ARTIFACTS_ROOT / 'qa_1m'}"
```

You can also run both in one command:

```python
!python -m src.ingestion.qa_export \
  --timeframe all \
  --start "{START}" \
  --end "{END}" \
  --symbols "{SYMBOLS_PATH}" \
  --out "{ARTIFACTS_ROOT / 'qa'}"
```

QA outputs are written under a deterministic run-id folder:

```text
artifacts/qa/<run_id>/
  qa_summary_by_symbol.csv
  qa_summary_global.csv
  qa_coverage_by_symbol.csv
```

Typical inspection flow:

```python
from pathlib import Path
import pandas as pd

qa_runs = sorted((ARTIFACTS_ROOT / "qa").glob("qa_*/"))
latest_run = qa_runs[-1]

global_df = pd.read_csv(latest_run / "qa_summary_global.csv")
by_symbol_df = pd.read_csv(latest_run / "qa_summary_by_symbol.csv")
coverage_df = pd.read_csv(latest_run / "qa_coverage_by_symbol.csv")

display(global_df)
display(by_symbol_df.head(20))
display(coverage_df.head(20))
```

Interpretation guidance before handoff:

Block downstream handoff when:

- expected dataset paths are missing under the restored curated root;
- expected symbols have zero rows in the requested date window;
- duplicate key counts are non-zero when strict uniqueness is required;
- OHLC integrity violations are non-zero;
- coverage is materially below your expected threshold;
- timestamps are malformed or outside the requested bounds.

Warn and review when:

- coverage gaps align with weekends or exchange holidays;
- a symbol has explainable partial coverage for the selected window;
- 1-minute market-calendar gaps need expected-session interpretation;
- optional datasets are absent but not required for your next workflow.

Post-restore QA is local and credential-free:

- no Alpaca credentials are needed for QA over restored files;
- no Google Drive API or OAuth is required;
- no background sync or network access is required;
- restored local curated Parquet remains canonical working data;
- QA artifacts are diagnostics only and do not mutate curated files.

Fintech QA validates source curated data quality. StratLake should still perform
its own consumer-side universe/date/timeframe validation during handoff.

### 7. Declare The Local Handoff Root

After restore, `CURATED_ROOT` is the local root for framework QA and downstream
consumers. For StratLake Trade Engine handoff, use this local root as
`MARKETLAKE_ROOT` or `--marketlake-root`. Do not point StratLake at the mounted
Drive backup pack directory.

```python
print(f"Restored local curated root: {CURATED_ROOT}")
print(f"Use as StratLake MARKETLAKE_ROOT: {CURATED_ROOT}")
```

### 8. Generate A StratLake Handoff Report

After post-restore QA, generate a deterministic local handoff summary for
StratLake consumers. The report is derived and non-canonical; local partitioned
Parquet remains canonical.

Run from the local workspace root:

```python
%cd {FINTECH_ROOT}
```

Module CLI:

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

Python API:

```python
from src.handoff import build_stratlake_handoff_report, write_stratlake_handoff_report

report = build_stratlake_handoff_report(
    root=FINTECH_ROOT,
    curated_root=CURATED_ROOT,
    qa_root=ARTIFACTS_ROOT / "qa",
)
output_path = write_stratlake_handoff_report(
    report,
    output_path=ARTIFACTS_ROOT / "handoff" / "stratlake_marketlake_handoff.json",
)
print(output_path)
print(report["stratlake_marketlake_root"])
```

The handoff report helps answer:

- which local curated root StratLake should consume;
- which datasets/timeframes/symbols/date ranges are present;
- whether QA artifacts are available and where they live.

By default, `generated_at_utc` is `null` so the report stays deterministic for
unchanged local filesystem inputs. Use `--generated-at-utc` only when a
timestamped report is intentionally desired.

When QA artifacts exist, the selected QA run is chosen by deterministic lexical
ordering of QA run directory names.

The report does not run ingestion, QA, archive pack restore/creation, Google
APIs, OAuth, or StratLake execution.

### 9. Run Local Workflows

After restore, point local QA, research, analysis, or downstream handoff
commands at the local workspace and local dataset root. Avoid using the mounted
Drive backup folder as the active dataset root.

Examples in this repository commonly read from:

```text
data/curated
data/research
artifacts
reports
```

When running in Colab, those paths should resolve under:

```text
/content/fintech-market-ingestion-demo
```

### 10. Dry-Run A New Backup Pack

At the end of a session, preview a new pack before writing archives to Drive.

```python
!python -m src.cli.backup_data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --dry-run
```

### 11. Create A Fresh Backup Pack To Drive

Create the backup pack only after local processing is complete and the local
dataset is in the state you want to checkpoint.

```python
!python -m src.cli.backup_data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --backup-id backup_after_session \
  --shard-size-mb 512
```

Optional pack metadata and notes can be repeated:

```python
!python -m src.cli.backup_data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --backup-id backup_after_session \
  --metadata environment=colab \
  --note "created after local QA checks"
```

## Python API Examples

Notebook users can call the Python APIs directly. The APIs are the primary
implementation surface; the CLI delegates to them.

```python
from src.backup import (
    create_backup_pack,
    inspect_backup_pack,
    restore_backup_pack,
    validate_backup_pack,
)

backup_pack_dir = BACKUP_PACK_DIR
restore_root = CURATED_ROOT
```

Validate and inspect before restore:

```python
validation = validate_backup_pack(backup_pack_dir)
print(validation.is_valid)
print(validation.errors)

inspection = inspect_backup_pack(backup_pack_dir)
print(inspection.included_datasets)
print(inspection.restore_target_hint)
```

Restore into local runtime storage:

```python
restore_result = restore_backup_pack(
    backup_pack_dir=backup_pack_dir,
    restore_root=restore_root,
    overwrite_policy="fail",
)
print(restore_result.restored_file_count)
```

Create a new backup pack after local processing:

```python
pack_result = create_backup_pack(
    workspace_root=FINTECH_ROOT,
    source_dataset_root=CURATED_ROOT,
    backup_root=BACKUP_PACK_ROOT,
    backup_id="backup_after_session",
    shard_size_mb=512,
)
print(pack_result.manifest_path)
```

Preview without writing:

```python
plan = create_backup_pack(
    workspace_root=FINTECH_ROOT,
    source_dataset_root=CURATED_ROOT,
    backup_root=BACKUP_PACK_ROOT,
    dry_run=True,
)
print(plan.dry_run)
print(plan.shard_paths)
```

## API Pull Versus Archive Restore

Use an API pull when:

- the data window is small;
- the data is not already archived;
- fresh market data is required;
- credentials, connectivity, and rate limits are acceptable.

Use archive restore when:

- the dataset has already been curated and checkpointed;
- many partitioned Parquet files would be slow to copy individually;
- the goal is to resume a notebook session quickly;
- repeated API calls or rate limits should be avoided;
- the workflow can run from archived data without fetching fresh data first.

Archive restore is a convenience for moving a known derived checkpoint back
into fast local storage. It is not a replacement for ingestion when fresh source
data is required.

## Archive Packs Versus Project Sessions

Use `fintech-save-session` and `fintech-restore-session` for lightweight
notebook continuity: configs, reports, artifacts, and selected research outputs.
Session save/restore is explicit file transport for project-session workflows;
curated data remains excluded by default.

Use `fintech-backup-data pack`, `validate`, `inspect`, and `restore` for large
curated datasets and restore-to-local-first workflows. Archive backup packs are
designed for curated data roots that may contain many partitioned Parquet files,
such as daily bars, 1-minute bars, corporate-action snapshots, or other files
under the selected curated dataset root. The pack writer inventories Parquet
files under `--source-dataset-root`; it does not make Drive canonical and does
not replace ingestion when fresh source data is needed.

## Disk Space And Cleanup

Check available Colab disk space before restoring large packs. The restore
workflow validates shards, stages extraction, and then places files under the
target restore root, so the runtime may temporarily need additional free space.

Keep shard sizes reasonable for Drive and Colab transfers. The default
`--shard-size-mb 512` is a practical starting point. If a pack is copied to
local runtime storage before restore, plan for space for both the compressed
pack and the restored dataset.

Daily bars are usually smaller and quicker to restore. 1-minute bars can be
much larger and may need more local disk, longer validation time, and more
archive shards. Corporate-action curated snapshots are typically smaller, but
the same validate-inspect-restore sequence applies when they are included under
the archived curated dataset root.

When finished, you may remove local runtime copies to free space, but do that
only after any desired backup pack has been written and validated. Colab runtime
storage is ephemeral; mounted Drive backups are the durable checkpoint layer.
Do not delete Drive backups unless that is intentional.

## Safety Boundaries

- Local Parquet remains the canonical working dataset after restore.
- Backup packs remain derived and non-canonical.
- Google Drive is archival/checkpoint storage, not active working storage.
- Validation and inspection are read-only.
- Restore is explicit and controlled by the selected overwrite policy.
- Pack creation reads source Parquet files and writes derived archive shards; it
  does not mutate the source dataset.
- No Google Drive API credentials are required.
- No background sync, remote metadata service, or object-store abstraction is
  used.
- No restore command infers or mutates ingestion configuration.

## Troubleshooting

If validation reports a missing shard, confirm the whole backup pack directory
was copied and that `manifest.json` and `shards/` are from the same pack.

If validation reports a checksum mismatch or unreadable ZIP shard, treat the
pack as corrupted and restore from a different checkpoint.

If restore fails with `overwrite_policy=fail`, choose an empty local restore
root, remove the local files intentionally, or use `replace` only when replacing
archive-covered files is desired.

If restore fails with `overwrite_policy=merge`, an existing local file differs
from the manifest. Use a clean restore root or inspect the difference before
choosing `replace`.

If Colab runs out of disk space, remove unneeded local runtime outputs or select
a smaller restore scope in a future pack. Do not switch the active Parquet root
to Drive to work around local disk pressure; that reintroduces the small-file
performance problem archive packs are meant to avoid.

For the manifest, writer, restore, validation, inspection, and CLI contracts,
see [archive_backup_pack_manifest.md](archive_backup_pack_manifest.md).
