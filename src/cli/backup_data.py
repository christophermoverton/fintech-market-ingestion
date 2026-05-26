"""fintech-backup-data: Archive backup pack pack/restore/validate/inspect CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.backup import (
    BackupPackValidationError,
    create_backup_pack,
    inspect_backup_pack,
    restore_backup_pack,
    validate_backup_pack,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    try:
        if args.command == "pack":
            return _run_pack(args)
        if args.command == "restore":
            return _run_restore(args)
        if args.command == "validate":
            return _run_validate(args)
        if args.command == "inspect":
            return _run_inspect(args)
    except (BackupPackValidationError, FileExistsError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    raise AssertionError(f"Unhandled backup_data command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fintech-backup-data",
        description="Create, restore, validate, and inspect archive backup packs.",
    )
    subparsers = parser.add_subparsers(dest="command")

    pack = subparsers.add_parser("pack", help="Create an archive backup pack.")
    pack.add_argument("--workspace-root", required=True, help="Workspace root.")
    pack.add_argument(
        "--source-dataset-root", required=True, help="Source local Parquet dataset root."
    )
    pack.add_argument(
        "--backup-root", required=True, help="Directory where backup packs are stored."
    )
    pack.add_argument("--backup-id", default=None, help="Optional backup pack ID.")
    pack.add_argument("--created-at-utc", default=None, help="Optional UTC timestamp.")
    pack.add_argument("--shard-size-mb", type=int, default=512, help="Shard size in MB.")
    pack.add_argument("--dry-run", action="store_true", default=False)
    pack.add_argument("--metadata", action="append", default=[], help="Metadata as key=value.")
    pack.add_argument("--note", action="append", default=[], help="Manifest note. May be repeated.")

    restore = subparsers.add_parser("restore", help="Restore an archive backup pack.")
    restore.add_argument("--backup-pack-dir", required=True, help="Backup pack directory.")
    restore.add_argument("--restore-root", required=True, help="Target local dataset root.")
    restore.add_argument(
        "--overwrite-policy",
        choices=["fail", "replace", "merge"],
        default="fail",
        help="Existing-file behavior.",
    )

    validate = subparsers.add_parser("validate", help="Validate an archive backup pack.")
    validate.add_argument("--backup-pack-dir", required=True, help="Backup pack directory.")
    validate.add_argument("--raise-on-error", action="store_true", default=False)

    inspect = subparsers.add_parser("inspect", help="Inspect an archive backup pack.")
    inspect.add_argument("--backup-pack-dir", required=True, help="Backup pack directory.")
    return parser


def _run_pack(args: argparse.Namespace) -> int:
    result = create_backup_pack(
        workspace_root=Path(args.workspace_root).expanduser().resolve(strict=False),
        source_dataset_root=Path(args.source_dataset_root).expanduser().resolve(strict=False),
        backup_root=Path(args.backup_root).expanduser().resolve(strict=False),
        backup_id=args.backup_id,
        created_at_utc=args.created_at_utc,
        shard_size_mb=args.shard_size_mb,
        dry_run=args.dry_run,
        metadata=_parse_metadata(args.metadata),
        notes=tuple(args.note) if args.note else None,
    )
    print("Archive backup pack:")
    print(f"  backup_id: {result.backup_id}")
    print(f"  backup_pack_dir: {result.backup_pack_dir}")
    print(f"  manifest_path: {result.manifest_path}")
    print(f"  file_count: {result.file_count}")
    print(f"  shard_count: {len(result.manifest.shards)}")
    print(f"  total_uncompressed_bytes: {result.total_uncompressed_bytes}")
    print(f"  total_archive_bytes: {result.total_archive_bytes}")
    print(f"  dry_run: {result.dry_run}")
    return 0


def _run_restore(args: argparse.Namespace) -> int:
    result = restore_backup_pack(
        backup_pack_dir=args.backup_pack_dir,
        restore_root=args.restore_root,
        overwrite_policy=args.overwrite_policy,
    )
    print("Archive backup restore:")
    print(f"  backup_id: {result.backup_id}")
    print(f"  restore_root: {result.restore_root}")
    print(f"  restored_file_count: {result.restored_file_count}")
    print(f"  restored_bytes: {result.restored_bytes}")
    print(f"  overwrite_policy: {result.overwrite_policy}")
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    result = validate_backup_pack(
        args.backup_pack_dir,
        raise_on_error=args.raise_on_error,
    )
    print("Archive backup validation:")
    print(f"  backup_id: {result.backup_id or '(unavailable)'}")
    print(f"  is_valid: {result.is_valid}")
    print(f"  file_count: {result.file_count}")
    print(f"  shard_count: {result.shard_count}")
    print(f"  checked_shard_count: {len(result.checked_shards)}")
    print(f"  checked_file_count: {len(result.checked_files)}")
    if result.errors:
        print("  errors:")
        for error in result.errors:
            print(f"    - {error}")
    if result.warnings:
        print("  warnings:")
        for warning in result.warnings:
            print(f"    - {warning}")
    return 0 if result.is_valid else 1


def _run_inspect(args: argparse.Namespace) -> int:
    inspection = inspect_backup_pack(args.backup_pack_dir)
    print("Archive backup inspection:")
    print(f"  backup_id: {inspection.backup_id}")
    print(f"  source_dataset_root: {inspection.source_dataset_root}")
    print(
        "  included_datasets: "
        + (", ".join(inspection.included_datasets) if inspection.included_datasets else "(none)")
    )
    print(f"  file_count: {inspection.file_count}")
    print(f"  shard_count: {inspection.shard_count}")
    print(f"  total_uncompressed_bytes: {inspection.total_uncompressed_bytes}")
    print(f"  total_archive_bytes: {inspection.total_archive_bytes}")
    print(f"  checksum_algorithm: {inspection.checksum_algorithm}")
    print(f"  shard_strategy: {inspection.shard_strategy}")
    print(f"  shard_size_mb: {inspection.shard_size_mb}")
    print(f"  restore_target_hint: {inspection.restore_target_hint}")
    print("  datasets:")
    for dataset in inspection.datasets:
        print(
            "    - "
            f"{dataset.dataset_name}: files={dataset.file_count}, "
            f"bytes={dataset.total_uncompressed_bytes}, "
            f"partition_keys={','.join(dataset.partition_keys) if dataset.partition_keys else '(none)'}"
        )
    print("  shards:")
    for shard in inspection.shards:
        print(
            "    - "
            f"{shard.shard_name}: index={shard.shard_index}, "
            f"files={shard.file_count}, bytes={shard.uncompressed_bytes}, "
            f"archive_bytes={shard.archive_bytes}, checksum_present={shard.checksum_present}"
        )
    return 0


def _parse_metadata(values: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("--metadata values must be formatted as key=value")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("--metadata key must be non-empty")
        metadata[key] = value
    return metadata


if __name__ == "__main__":
    sys.exit(main())
