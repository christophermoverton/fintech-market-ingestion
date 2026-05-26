# Archive Backup Pack Manifest Contract

Milestone 10 archive backup packs are portable transfer artifacts for local
partitioned Parquet datasets. They exist because copying many small Parquet
partition files directly to Google Drive can be slow in notebook and Colab
workflows. A backup pack groups those files into later archive shards while
preserving a deterministic manifest that describes what came from the local
working dataset.

Local partitioned Parquet remains canonical. A backup pack is always derived and
non-canonical. It is a checkpoint and restore aid, not a replacement dataset, a
remote metadata service, or a new source of truth.

This issue defines only the manifest contract. It does not implement full pack
creation, restore, background sync, Google Drive API integration, or any change
to the canonical Parquet layout.

## Manifest File

Each archive backup pack contains a `manifest.json` serialized as deterministic
JSON with sorted keys, stable ordering, two-space indentation, and a trailing
newline. Durable paths are portable POSIX-style relative paths. Absolute local
paths, Windows drive-qualified paths, home-relative paths, and parent traversal
are invalid in serialized path fields.

Required top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer manifest schema version. Current value: `1`. |
| `backup_id` | Stable identifier for this pack. |
| `created_at_utc` | UTC timestamp formatted as `YYYY-MM-DDTHH:MM:SSZ`. |
| `artifact_type` | Must be `archive_backup_pack`. |
| `canonical_status` | Must be `derived_non_canonical`. |
| `source_dataset_root` | Workspace-relative root of the source Parquet dataset inventory. |
| `included_datasets` | Sorted logical dataset names represented by the file inventory. |
| `file_count` | Number of file inventory entries. Must match `files`. |
| `total_uncompressed_bytes` | Sum of inventory file sizes. Must match `files`. |
| `checksum_algorithm` | Manifest-level checksum algorithm. Current helper support: `sha256`. |
| `shard_strategy` | Strategy name or reserved value for later archive writing. |
| `files` | Sorted source file inventory entries. |
| `shards` | Sorted archive shard metadata entries. May be empty before shard writing exists. |
| `restore` | Restore compatibility metadata. |

Optional or reserved fields:

| Field | Meaning |
| --- | --- |
| `total_archive_bytes` | Sum of archive shard sizes when known. May be `null`. |
| `shard_size_mb` | Intended shard target size when applicable. May be `null`. |
| `metadata` | Small deterministic object for producer metadata. |
| `notes` | Human-readable notes. |

## Backup Pack Writer

The Python writer API creates derived archive backup packs from a local
partitioned Parquet dataset:

```python
from src.backup import create_backup_pack

result = create_backup_pack(
    workspace_root=".",
    source_dataset_root="data/curated",
    backup_root="artifacts/archive_backups",
    shard_size_mb=512,
)
```

The writer treats `backup_root` as an ordinary filesystem path. That path may be
local disk, Colab runtime storage, or an already-mounted Google Drive folder.
The package does not mount Drive, authenticate, call Google APIs, or run any
background sync.

The default pack layout is:

```text
<backup_root>/
  <backup_id>/
    manifest.json
    shards/
      shard-000000.zip
      shard-000001.zip
```

`backup_id` is used as the backup pack directory name. It must be one portable
path segment containing only letters, numbers, `.`, `_`, and `-`; path
separators, absolute paths, drive-qualified paths, home-relative paths,
traversal, and surrounding spaces are rejected before any pack directory is
created.

ZIP shard paths recorded in the manifest are relative to the backup pack root,
for example `shards/shard-000000.zip`. Archive members preserve source paths
relative to `source_dataset_root`, such as
`bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet`.

The shard strategy is `size_limited_zip`. Files are sorted by relative path and
grouped into shards up to `shard_size_mb`. Individual files are never split; if
a single Parquet file is larger than the configured shard size, it is placed
alone in its own shard. Shard names are deterministic and zero-padded.

The writer fixes ZIP member timestamps, ordering, permissions metadata, and
member paths so equivalent inputs produce stable shard bytes in the standard
library ZIP implementation. Manifest, file, and shard checksum algorithms are
currently restricted to `sha256`.

Dry-run mode builds the source inventory, planned shard names, planned shard
entries, and planned manifest without creating the backup directory, writing
archives, or writing `manifest.json`.

## Local Restore Workflow

The Python restore API reads a backup pack from an ordinary filesystem path and
restores archive members into a local dataset root:

```python
from src.backup import restore_backup_pack

result = restore_backup_pack(
    backup_pack_dir="/content/drive/MyDrive/fintech-market-ingestion/backups/<backup_id>",
    restore_root="/content/fintech-market-ingestion/data/curated",
    overwrite_policy="fail",
)
```

`restore_root` represents the target dataset root. If a shard contains
`bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet`, restore writes:

```text
<restore_root>/bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet
```

It does not add another `source_dataset_root` directory layer. The restored
local Parquet files are the working dataset after restore; the backup pack
remains a derived, non-canonical transfer artifact.

Before final placement, restore validates `manifest.json`, confirms the pack is
derived/non-canonical, checks that required ZIP shards exist, verifies shard
sizes and SHA-256 checksums when recorded, validates ZIP member paths, confirms
archive members match manifest file inventory, and stages extraction in a
temporary directory. Unsafe archive member paths, including absolute paths,
Windows drive-qualified paths, home-relative paths, and parent traversal, are
rejected.

Overwrite policies:

| Policy | Behavior |
| --- | --- |
| `fail` | Default. Any existing target file fails before final writes. |
| `replace` | Replaces files present in the archive. Unrelated files are left alone. |
| `merge` | Skips existing files only when their checksum matches the manifest; differing files fail. |

Restore treats mounted Google Drive as a plain filesystem source path. It does
not mount Drive, authenticate, call Google APIs, make Drive active working
storage, infer ingestion configuration, or run background sync.

## Validation And Inspection

Validation and inspection are read-only notebook-friendly APIs for checking
archive backup packs before restore:

```python
from src.backup import inspect_backup_pack, validate_backup_pack

validation = validate_backup_pack("/content/drive/MyDrive/.../<backup_id>")
inspection = inspect_backup_pack("/content/drive/MyDrive/.../<backup_id>")
```

`validate_backup_pack(...)` returns a structured result with `is_valid`,
`errors`, `warnings`, checked shard paths, checked file paths, byte totals, and
the validated manifest when readable. Expected pack problems are reported as
actionable errors instead of mutating or repairing the pack. Pass
`raise_on_error=True` when an exception is preferred.

Validation checks:

- `manifest.json` exists, is readable, and satisfies the manifest contract.
- The pack is explicitly `derived_non_canonical`.
- The shard strategy is compatible with local ZIP restore.
- Expected shard files exist under the backup pack directory.
- Shard sizes and SHA-256 checksums match recorded metadata when present.
- ZIP shards are readable.
- ZIP member paths are safe relative paths.
- ZIP members are listed in manifest file inventory.
- Manifest file entries appear exactly once across shards.
- Member sizes and file checksums match manifest inventory when present.

`inspect_backup_pack(...)` summarizes the manifest without extraction:
datasets, partition keys, file counts, byte totals, shard summaries, checksum
presence, restore metadata, and a restore target hint. Inspection ordering is
deterministic.

These APIs do not create directories, extract archives, repair metadata, contact
Google Drive APIs, infer remote state, or mutate canonical local datasets.

For the notebook-oriented Colab workflow that uses these APIs and CLI wrappers
with mounted Google Drive as archival storage, see
[colab_archive_backup_restore.md](colab_archive_backup_restore.md).

## CLI Wrappers

The `backup_data` CLI is a thin shell-friendly wrapper over the Python APIs.
It treats mounted Google Drive paths as ordinary filesystem paths and does not
use Google Drive APIs, credentials, network access, or background sync.

Create a pack:

```bash
python -m src.cli.backup_data pack \
  --workspace-root . \
  --source-dataset-root data/curated \
  --backup-root artifacts/archive_backups \
  --backup-id backup_example \
  --shard-size-mb 512
```

Preview pack creation without writing a pack directory:

```bash
python -m src.cli.backup_data pack \
  --workspace-root . \
  --source-dataset-root data/curated \
  --backup-root artifacts/archive_backups \
  --dry-run
```

Restore a pack into the active local dataset root:

```bash
python -m src.cli.backup_data restore \
  --backup-pack-dir artifacts/archive_backups/backup_example \
  --restore-root data/curated \
  --overwrite-policy fail
```

Validate and inspect a pack:

```bash
python -m src.cli.backup_data validate \
  --backup-pack-dir artifacts/archive_backups/backup_example

python -m src.cli.backup_data inspect \
  --backup-pack-dir artifacts/archive_backups/backup_example
```

The CLI prints concise notebook-friendly summaries and returns nonzero for
expected pack, validation, or restore failures. It does not add behavior that
is unavailable through the Python APIs.

## File Inventory Entries

Each `files[]` entry describes one source Parquet file without reading Parquet
contents. The helper inventories files matching `*.parquet`, records file size,
computes a SHA-256 checksum, infers `dataset_name` from the first path segment
when available, and infers partition metadata from `key=value` path segments.

Required fields:

| Field | Meaning |
| --- | --- |
| `relative_path` | Path relative to `source_dataset_root`. |
| `size_bytes` | Source file size in bytes. |

Optional fields:

| Field | Meaning |
| --- | --- |
| `dataset_name` | Logical dataset name if inferable. |
| `checksum` | File checksum. |
| `checksum_algorithm` | File checksum algorithm, usually `sha256`. |
| `partitions` | Object of path-derived partition keys and values. |

## Shard Entries

Issue 72 does not create archive shards, but the manifest reserves the shard
contract so Issue 73 can add sharded archive writing without changing the
manifest shape.

Required `shards[]` fields:

| Field | Meaning |
| --- | --- |
| `shard_name` | Portable shard filename. |
| `relative_path` | Shard path relative to the backup pack root. |
| `shard_index` | Zero-based shard order. |
| `file_count` | Number of source files represented in the shard. |
| `uncompressed_bytes` | Sum of source file sizes represented in the shard. |

Optional `shards[]` fields:

| Field | Meaning |
| --- | --- |
| `archive_bytes` | Compressed archive size when known. |
| `checksum` | Shard checksum when known. |
| `checksum_algorithm` | Shard checksum algorithm. |

## Restore Metadata

The `restore` section describes compatibility expectations for later restore
work. It does not perform restore.

Required fields:

| Field | Meaning |
| --- | --- |
| `expected_layout` | Human-readable restore layout description. |
| `paths_are_relative` | Must be `true`. |
| `overwrite_policy_options` | Expected later options, currently `fail_if_exists` and `overwrite`. |
| `compatibility_schema_version` | Manifest schema version compatible with restore. |
| `source_root_semantics` | Must be `workspace_relative`. |

## Validation Rules

Validation treats missing required fields as contract failures with actionable
field names. Malformed timestamps, counts that do not match inventory entries,
invalid path values, unsupported canonical status, and non-relative restore
semantics all fail validation.

The manifest must explicitly say `canonical_status:
derived_non_canonical`. Missing that field is invalid, and any value implying
the archive pack is authoritative is rejected. Google Drive API credentials,
remote service metadata, sync daemon state, and absolute runtime paths do not
belong in this manifest.

## Example

See
[`tests/fixtures/archive_backup_pack_manifest.json`](../tests/fixtures/archive_backup_pack_manifest.json)
for a complete synthetic manifest fixture.
