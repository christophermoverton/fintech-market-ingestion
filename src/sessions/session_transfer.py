"""Explicit project-session save/restore helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from src.persistence.base import PersistedFile, PersistenceAdapter
from src.sessions.save_plan import SavePlan, build_save_plan
from src.sessions.session_paths import (
    ROOT_SEMANTICS_WORKSPACE_RELATIVE,
    normalize_workspace_relative_path,
)

SAVE_MANIFEST_FILENAME = "session_save_manifest.json"
RESTORE_MANIFEST_FILENAME = "restore_manifest.json"
RESTORE_ARTIFACT_ROOT = Path("artifacts/restores")
SESSION_TRANSFER_SCHEMA_VERSION = 1
SKIPPED_RESTORE_FILES = frozenset({SAVE_MANIFEST_FILENAME, RESTORE_MANIFEST_FILENAME})


class RestoreCollisionError(ValueError):
    """Raised when restore would overwrite local files without force."""

    def __init__(self, collisions: Sequence[str]) -> None:
        self.collisions = tuple(collisions)
        super().__init__(
            "Restore would overwrite existing file(s) without --force: "
            + ", ".join(self.collisions)
        )


@dataclass(frozen=True)
class RestorePlanEntry:
    source_path: str
    destination_path: str
    size_bytes: int
    status: str
    kind: str = "file"

    def to_dict(self) -> dict[str, int | str]:
        return {
            "destination_path": self.destination_path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "source_path": self.source_path,
            "status": self.status,
        }


def utc_now_string() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_save_exclude(
    include_curated_data: bool, exclude: Sequence[str] | None
) -> tuple[str, ...]:
    if exclude is not None:
        return _normalize_paths(exclude, "exclude")
    if include_curated_data:
        return ()
    return ("data/curated",)


def build_session_save_plan(
    workspace_root: Path | str,
    include: Sequence[str],
    *,
    exclude: Sequence[str] | None = None,
    include_curated_data: bool = False,
) -> SavePlan:
    return build_save_plan(
        workspace_root,
        include=include,
        exclude=default_save_exclude(include_curated_data, exclude),
    )


def copy_save_plan_files(
    workspace_root: Path | str,
    adapter: PersistenceAdapter,
    plan: SavePlan,
) -> list[dict[str, Any]]:
    root = Path(workspace_root)
    copied: list[dict[str, Any]] = []
    for entry in plan.entries:
        adapter.write_file(root / entry.source_path, entry.destination_path)
        row = entry.to_dict()
        row["status"] = "copied"
        copied.append(row)
    return copied


def build_save_manifest(
    *,
    session_id: str,
    created_at_utc: str,
    adapter_name: str,
    destination: str,
    plan: SavePlan,
    include_curated_data: bool,
    dry_run: bool,
    files: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_files = list(files) if files is not None else _planned_save_files(plan)
    copied_file_count = sum(1 for item in manifest_files if item.get("status") == "copied")
    return {
        "schema_version": SESSION_TRANSFER_SCHEMA_VERSION,
        "operation": "save",
        "session_id": session_id,
        "created_at_utc": created_at_utc,
        "adapter": adapter_name,
        "workspace_root_semantics": ROOT_SEMANTICS_WORKSPACE_RELATIVE,
        "destination": destination,
        "include": list(plan.include),
        "exclude": list(plan.exclude),
        "include_curated_data": include_curated_data,
        "dry_run": dry_run,
        "copied_file_count": copied_file_count,
        "total_size_bytes": plan.summary.total_size_bytes,
        "files": manifest_files,
    }


def write_save_manifest(adapter: Any, manifest: dict[str, Any]) -> Path:
    path = _adapter_root(adapter) / SAVE_MANIFEST_FILENAME
    path.write_text(dumps_transfer_manifest_json(manifest), encoding="utf-8")
    return path


def build_restore_entries(
    workspace_root: Path | str,
    persisted_files: Sequence[PersistedFile],
) -> tuple[RestorePlanEntry, ...]:
    root = Path(workspace_root)
    entries: list[RestorePlanEntry] = []
    for persisted in sorted(persisted_files, key=lambda item: item.path):
        if Path(persisted.path).name in SKIPPED_RESTORE_FILES:
            continue
        relative_path = normalize_workspace_relative_path(
            persisted.path,
            field_name="restore source path",
        )
        destination = root / relative_path
        status = "skipped_existing" if destination.exists() else "planned"
        entries.append(
            RestorePlanEntry(
                source_path=relative_path,
                destination_path=relative_path,
                size_bytes=persisted.size_bytes,
                status=status,
            )
        )
    return tuple(entries)


def restore_files(
    workspace_root: Path | str,
    adapter: PersistenceAdapter,
    entries: Sequence[RestorePlanEntry],
    *,
    force: bool,
) -> tuple[list[dict[str, Any]], int, int, int]:
    root = Path(workspace_root)
    collisions = [
        entry.destination_path for entry in entries if (root / entry.destination_path).exists()
    ]
    if collisions and not force:
        raise RestoreCollisionError(collisions)

    rows: list[dict[str, Any]] = []
    restored_count = 0
    skipped_count = 0
    collision_count = len(collisions)
    for entry in entries:
        adapter.read_file(entry.source_path, root / entry.destination_path)
        row = entry.to_dict()
        row["status"] = "restored"
        rows.append(row)
        restored_count += 1
    return rows, restored_count, skipped_count, collision_count


def build_restore_manifest(
    *,
    created_at_utc: str,
    adapter_name: str,
    source: str,
    dry_run: bool,
    force: bool,
    files: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    restored_file_count = sum(1 for item in files if item.get("status") == "restored")
    skipped_file_count = sum(
        1 for item in files if str(item.get("status", "")).startswith("skipped")
    )
    collision_count = sum(1 for item in files if item.get("status") == "skipped_existing")
    return {
        "schema_version": SESSION_TRANSFER_SCHEMA_VERSION,
        "operation": "restore",
        "created_at_utc": created_at_utc,
        "adapter": adapter_name,
        "source": source,
        "workspace_root_semantics": ROOT_SEMANTICS_WORKSPACE_RELATIVE,
        "dry_run": dry_run,
        "force": force,
        "restored_file_count": restored_file_count,
        "skipped_file_count": skipped_file_count,
        "collision_count": collision_count,
        "files": list(files),
    }


def write_restore_manifest(
    workspace_root: Path | str,
    restore_id: str,
    manifest: dict[str, Any],
) -> Path:
    path = Path(workspace_root) / RESTORE_ARTIFACT_ROOT / restore_id / RESTORE_MANIFEST_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_transfer_manifest_json(manifest), encoding="utf-8")
    return path


def restore_id_from_timestamp(created_at_utc: str) -> str:
    timestamp = created_at_utc.replace("-", "").replace(":", "").replace("T", "_").removesuffix("Z")
    return f"restore_{timestamp}"


def dumps_transfer_manifest_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _planned_save_files(plan: SavePlan) -> list[dict[str, Any]]:
    files = []
    for entry in plan.entries:
        row = entry.to_dict()
        row["status"] = "planned"
        files.append(row)
    return files


def _adapter_root(adapter: Any) -> Path:
    root = getattr(adapter, "root", None)
    if root is None:
        raise ValueError("Persistence adapter does not expose a root path for manifest writing")
    return Path(root)


def _normalize_paths(paths: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(paths, str):
        raise ValueError(f"{field_name} must be a sequence of workspace-relative paths")
    return tuple(
        sorted(
            dict.fromkeys(
                normalize_workspace_relative_path(path, field_name=f"{field_name}[]")
                for path in paths
            )
        )
    )
