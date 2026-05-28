# Colab Archive Backup And Restore Workflow

Milestone 10 archive backup packs are designed for Colab and notebook sessions
where Google Drive is useful for durable storage but slow as the active working
layer for partitioned Parquet data. A curated market dataset can contain many
small files. Copying those files one by one to or from Drive is often much
slower than transferring a smaller number of archive shards.

The intended pattern is:

1. Keep active processing on local Colab runtime storage.
2. Store compact archive backup packs in mounted Google Drive.
3. Validate and inspect a backup pack before restore.
4. Restore the pack from Drive into local runtime storage.
5. Run ingestion, feature, QA, or analysis workflows against local files.
6. Optionally create a fresh backup pack back to mounted Drive when finished.

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

### 1. Mount Drive If Needed

In Colab, mounting Drive is optional notebook setup. It is not part of the
project backup API.

```python
from google.colab import drive

drive.mount("/content/drive")
```

### 2. Use Local Runtime As The Workspace

Clone, install, or otherwise prepare the project under local runtime storage,
then work from that local workspace.

```python
%cd {FINTECH_ROOT}
```

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

### 4. Inspect Pack Contents

Inspect the pack to confirm the included datasets, shard count, byte totals,
checksum algorithm, and restore hints.

```python
!python -m src.cli.backup_data inspect \
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

Overwrite policies:

| Policy | Behavior |
| --- | --- |
| `fail` | Default. Fail before final writes if any target file already exists. |
| `replace` | Replace files present in the archive and leave unrelated files alone. |
| `merge` | Skip matching existing files and fail if an existing file differs. |

### 6. Run Local Workflows

After restore, point ingestion, feature, QA, or analysis commands at the local
workspace and local dataset root. Avoid using the mounted Drive backup folder as
the active dataset root.

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

### 7. Dry-Run A New Backup Pack

At the end of a session, preview a new pack before writing archives to Drive.

```python
!python -m src.cli.backup_data pack \
  --workspace-root "{FINTECH_ROOT}" \
  --source-dataset-root "{CURATED_ROOT}" \
  --backup-root "{BACKUP_PACK_ROOT}" \
  --dry-run
```

### 8. Create A Fresh Backup Pack To Drive

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

## Disk Space And Cleanup

Check available Colab disk space before restoring large packs. The restore
workflow validates shards, stages extraction, and then places files under the
target restore root, so the runtime may temporarily need additional free space.

Keep shard sizes reasonable for Drive and Colab transfers. The default
`--shard-size-mb 512` is a practical starting point. If a pack is copied to
local runtime storage before restore, plan for space for both the compressed
pack and the restored dataset.

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
