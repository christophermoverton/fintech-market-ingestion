"""fintech-save-session: Explicitly save selected project-session files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.persistence import GoogleDrivePersistenceAdapter, LocalPersistenceAdapter
from src.sessions import (
    build_save_manifest,
    build_session_save_plan,
    copy_save_plan_files,
    session_manifest_path,
    utc_now_string,
    write_save_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fintech-save-session",
        description="Explicitly save selected workspace files through a persistence adapter.",
    )
    parser.add_argument("--root", default=".", help="Workspace root (default: current directory).")
    parser.add_argument("--session-id", required=True, help="Project session ID to save.")
    parser.add_argument(
        "--adapter",
        choices=["local", "google-drive"],
        default="local",
        help="Persistence adapter to use (default: local).",
    )
    parser.add_argument("--destination", help="Adapter root destination path.")
    parser.add_argument(
        "--include",
        nargs="*",
        default=None,
        help="Workspace-relative files or directories to include.",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        help="Workspace-relative files or directories to exclude.",
    )
    parser.add_argument(
        "--include-curated-data",
        action="store_true",
        default=False,
        help="Allow data/curated to be selected when explicitly included.",
    )
    parser.add_argument(
        "--create-destination",
        action="store_true",
        default=False,
        help="Create a missing destination root for google-drive adapter.",
    )
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve(strict=False)
    session_manifest = session_manifest_path(root, args.session_id)
    if not session_manifest.exists():
        print(f"Session manifest does not exist: {session_manifest}", file=sys.stderr)
        return 1

    include = tuple(args.include or ())
    if not include and not args.dry_run:
        print("At least one --include path is required unless --dry-run is used.", file=sys.stderr)
        return 1
    if not args.destination and not args.dry_run:
        print("--destination is required unless --dry-run is used.", file=sys.stderr)
        return 1

    try:
        plan = build_session_save_plan(
            root,
            include=include,
            exclude=args.exclude,
            include_curated_data=args.include_curated_data,
        )
        created_at = utc_now_string()
        adapter = None
        files = None
        manifest_path = None
        if not args.dry_run:
            adapter = _adapter_for_save(args.adapter, args.destination, args.create_destination)
            files = copy_save_plan_files(root, adapter, plan)
            manifest = build_save_manifest(
                session_id=args.session_id,
                created_at_utc=created_at,
                adapter_name=args.adapter,
                destination=args.destination,
                plan=plan,
                include_curated_data=args.include_curated_data,
                dry_run=False,
                files=files,
            )
            manifest_path = write_save_manifest(adapter, manifest)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Session save:")
    print(f"  session_id: {args.session_id}")
    print(f"  adapter: {args.adapter}")
    print(f"  destination: {args.destination or '(dry-run only)'}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  include: {', '.join(plan.include) if plan.include else '(none)'}")
    print(f"  exclude: {', '.join(plan.exclude) if plan.exclude else '(none)'}")
    print(f"  file_count: {plan.summary.file_count}")
    print(f"  total_size_bytes: {plan.summary.total_size_bytes}")
    if manifest_path is not None:
        print(f"  manifest_path: {manifest_path}")
    return 0


def _adapter_for_save(
    adapter_name: str,
    destination: str,
    create_destination: bool,
) -> LocalPersistenceAdapter | GoogleDrivePersistenceAdapter:
    if adapter_name == "local":
        return LocalPersistenceAdapter(destination)
    return GoogleDrivePersistenceAdapter(destination, create_root=create_destination)


if __name__ == "__main__":
    sys.exit(main())
