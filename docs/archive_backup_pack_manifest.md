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
