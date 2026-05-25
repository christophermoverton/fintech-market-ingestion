"""fintech-restore-session: Explicitly restore persisted project-session files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.persistence import GoogleDrivePersistenceAdapter, LocalPersistenceAdapter
from src.sessions import (
    RestoreCollisionError,
    build_restore_entries,
    build_restore_manifest,
    restore_files,
    restore_id_from_timestamp,
    utc_now_string,
    write_restore_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fintech-restore-session",
        description="Explicitly restore files from a persistence adapter into a workspace.",
    )
    parser.add_argument("--root", default=".", help="Workspace root (default: current directory).")
    parser.add_argument(
        "--adapter",
        choices=["local", "google-drive"],
        default="local",
        help="Persistence adapter to use (default: local).",
    )
    parser.add_argument("--source", required=True, help="Adapter root source path.")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", default=False)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve(strict=False)
    try:
        adapter = _adapter_for_restore(args.adapter, args.source)
        entries = build_restore_entries(root, adapter.list_files())
        created_at = utc_now_string()
        manifest_path = None
        if args.dry_run:
            files = [entry.to_dict() for entry in entries]
            restored_count = 0
            skipped_count = sum(1 for entry in entries if entry.status.startswith("skipped"))
            collision_count = skipped_count
        else:
            files, restored_count, skipped_count, collision_count = restore_files(
                root,
                adapter,
                entries,
                force=args.force,
            )
            manifest = build_restore_manifest(
                created_at_utc=created_at,
                adapter_name=args.adapter,
                source=args.source,
                dry_run=False,
                force=args.force,
                files=files,
            )
            restore_id = restore_id_from_timestamp(created_at)
            manifest_path = write_restore_manifest(root, restore_id, manifest)
    except RestoreCollisionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Session restore:")
    print(f"  adapter: {args.adapter}")
    print(f"  source: {args.source}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  force: {args.force}")
    print(f"  planned_file_count: {len(entries)}")
    print(f"  restored_file_count: {restored_count}")
    print(f"  skipped_file_count: {skipped_count}")
    print(f"  collision_count: {collision_count}")
    if manifest_path is not None:
        print(f"  manifest_path: {manifest_path}")
    return 0


def _adapter_for_restore(
    adapter_name: str,
    source: str,
) -> LocalPersistenceAdapter | GoogleDrivePersistenceAdapter:
    if adapter_name == "local":
        root = Path(source).expanduser().resolve(strict=False)
        if not root.exists():
            raise FileNotFoundError(f"Restore source does not exist: {root}")
        return LocalPersistenceAdapter(root)
    return GoogleDrivePersistenceAdapter(source)


if __name__ == "__main__":
    sys.exit(main())
