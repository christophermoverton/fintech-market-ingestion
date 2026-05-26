"""Deterministic sharded archive backup pack writer."""

from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from src.backup.manifest import (
    CHECKSUM_SHA256,
    BackupPackFileEntry,
    BackupPackManifest,
    BackupPackShardEntry,
    BackupPackValidationError,
    build_archive_backup_pack_manifest,
    build_file_inventory,
    deterministic_backup_id,
    normalize_created_at_utc,
    write_manifest,
)
from src.sessions.session_paths import workspace_relative_path

BACKUP_PACK_MANIFEST_FILENAME = "manifest.json"
BACKUP_PACK_SHARDS_DIR = "shards"
DEFAULT_SHARD_SIZE_MB = 512
ZIP_COMPRESSION = "zip"
ZIP_SHARD_STRATEGY = "size_limited_zip"
ZIP_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_BACKUP_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class BackupPackWriteResult:
    backup_id: str
    backup_pack_dir: Path
    manifest_path: Path
    shard_paths: tuple[Path, ...]
    file_count: int
    total_uncompressed_bytes: int
    total_archive_bytes: int | None
    dry_run: bool
    manifest: BackupPackManifest


def create_backup_pack(
    *,
    workspace_root: Path | str,
    source_dataset_root: Path | str,
    backup_root: Path | str,
    backup_id: str | None = None,
    created_at_utc: datetime | str | None = None,
    shard_size_mb: int = DEFAULT_SHARD_SIZE_MB,
    compression: str = ZIP_COMPRESSION,
    dry_run: bool = False,
    metadata: Mapping[str, Any] | None = None,
    notes: Sequence[str] | None = None,
) -> BackupPackWriteResult:
    """Create or plan a deterministic archive backup pack from local Parquet files."""

    if compression != ZIP_COMPRESSION:
        raise BackupPackValidationError(
            "create_backup_pack currently supports zip compression only"
        )
    if not isinstance(shard_size_mb, int) or isinstance(shard_size_mb, bool) or shard_size_mb <= 0:
        raise BackupPackValidationError("shard_size_mb must be a positive integer")

    created_at = normalize_created_at_utc(created_at_utc)
    source_root = _resolve_source_root(workspace_root, source_dataset_root)
    source_root_relative = workspace_relative_path(workspace_root, source_root)
    resolved_backup_id = _normalize_backup_id(
        deterministic_backup_id(source_root_relative, created_at)
        if backup_id is None
        else backup_id
    )
    backup_pack_dir = Path(backup_root) / resolved_backup_id
    manifest_path = backup_pack_dir / BACKUP_PACK_MANIFEST_FILENAME
    shard_plan = _plan_shards(build_file_inventory(source_root), shard_size_mb)
    planned_shard_paths = tuple(
        backup_pack_dir / BACKUP_PACK_SHARDS_DIR / _shard_name(index)
        for index, _group in enumerate(shard_plan)
    )

    if dry_run:
        planned_shards = _planned_shard_entries(shard_plan)
        manifest = build_archive_backup_pack_manifest(
            workspace_root=workspace_root,
            source_dataset_root=source_root,
            backup_id=resolved_backup_id,
            created_at_utc=created_at,
            files=tuple(file_entry for group in shard_plan for file_entry in group),
            shards=planned_shards,
            shard_strategy=ZIP_SHARD_STRATEGY,
            shard_size_mb=shard_size_mb,
            total_archive_bytes=None,
            metadata=metadata,
            notes=notes,
        )
        return BackupPackWriteResult(
            backup_id=resolved_backup_id,
            backup_pack_dir=backup_pack_dir,
            manifest_path=manifest_path,
            shard_paths=planned_shard_paths,
            file_count=manifest.file_count,
            total_uncompressed_bytes=manifest.total_uncompressed_bytes,
            total_archive_bytes=None,
            dry_run=True,
            manifest=manifest,
        )

    _prepare_backup_pack_dir(backup_pack_dir)
    actual_shards = []
    total_archive_bytes = 0
    for index, group in enumerate(shard_plan):
        shard_path = backup_pack_dir / BACKUP_PACK_SHARDS_DIR / _shard_name(index)
        _write_zip_shard(source_root, group, shard_path)
        archive_bytes = shard_path.stat().st_size
        total_archive_bytes += archive_bytes
        actual_shards.append(_shard_entry(index, group, archive_bytes, _sha256_file(shard_path)))

    manifest = build_archive_backup_pack_manifest(
        workspace_root=workspace_root,
        source_dataset_root=source_root,
        backup_id=resolved_backup_id,
        created_at_utc=created_at,
        files=tuple(file_entry for group in shard_plan for file_entry in group),
        shards=tuple(actual_shards),
        shard_strategy=ZIP_SHARD_STRATEGY,
        shard_size_mb=shard_size_mb,
        total_archive_bytes=total_archive_bytes,
        metadata=metadata,
        notes=notes,
    )
    write_manifest(manifest, manifest_path)
    return BackupPackWriteResult(
        backup_id=resolved_backup_id,
        backup_pack_dir=backup_pack_dir,
        manifest_path=manifest_path,
        shard_paths=tuple(backup_pack_dir / shard.relative_path for shard in actual_shards),
        file_count=manifest.file_count,
        total_uncompressed_bytes=manifest.total_uncompressed_bytes,
        total_archive_bytes=total_archive_bytes,
        dry_run=False,
        manifest=manifest,
    )


def _plan_shards(
    files: Sequence[BackupPackFileEntry], shard_size_mb: int
) -> tuple[tuple[BackupPackFileEntry, ...], ...]:
    max_bytes = shard_size_mb * 1024 * 1024
    groups: list[tuple[BackupPackFileEntry, ...]] = []
    current: list[BackupPackFileEntry] = []
    current_bytes = 0

    for file_entry in sorted(files, key=lambda item: item.relative_path):
        if current and current_bytes + file_entry.size_bytes > max_bytes:
            groups.append(tuple(current))
            current = []
            current_bytes = 0
        current.append(file_entry)
        current_bytes += file_entry.size_bytes
        if file_entry.size_bytes > max_bytes:
            groups.append(tuple(current))
            current = []
            current_bytes = 0

    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _resolve_source_root(workspace_root: Path | str, source_dataset_root: Path | str) -> Path:
    source_root = Path(source_dataset_root)
    if source_root.is_absolute():
        return source_root
    return Path(workspace_root) / source_root


def _normalize_backup_id(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise BackupPackValidationError("backup_id must be a non-empty string")
    raw = value.strip()
    if raw != value:
        raise BackupPackValidationError("backup_id must not contain surrounding spaces")
    if raw.startswith("~"):
        raise BackupPackValidationError("backup_id must not be home-relative")
    windows_path = PureWindowsPath(raw)
    posix_path = PurePosixPath(raw)
    if windows_path.drive:
        raise BackupPackValidationError("backup_id must not be drive-qualified")
    if windows_path.is_absolute() or posix_path.is_absolute():
        raise BackupPackValidationError("backup_id must not be absolute")
    if "\\" in raw or "/" in raw:
        raise BackupPackValidationError("backup_id must not contain path separators")
    if raw in {".", ".."} or ".." in posix_path.parts:
        raise BackupPackValidationError("backup_id must not contain parent traversal")
    if not _BACKUP_ID_RE.match(raw):
        raise BackupPackValidationError("backup_id contains unsupported characters")
    return raw


def _planned_shard_entries(
    shard_plan: Sequence[Sequence[BackupPackFileEntry]],
) -> tuple[BackupPackShardEntry, ...]:
    return tuple(
        _shard_entry(index, group, archive_bytes=None, checksum=None)
        for index, group in enumerate(shard_plan)
    )


def _shard_entry(
    index: int,
    group: Sequence[BackupPackFileEntry],
    archive_bytes: int | None,
    checksum: str | None,
) -> BackupPackShardEntry:
    shard_name = _shard_name(index)
    return BackupPackShardEntry(
        shard_name=shard_name,
        relative_path=f"{BACKUP_PACK_SHARDS_DIR}/{shard_name}",
        shard_index=index,
        file_count=len(group),
        uncompressed_bytes=sum(file_entry.size_bytes for file_entry in group),
        archive_bytes=archive_bytes,
        checksum=checksum,
        checksum_algorithm=CHECKSUM_SHA256,
    )


def _shard_name(index: int) -> str:
    return f"shard-{index:06d}.zip"


def _prepare_backup_pack_dir(backup_pack_dir: Path) -> None:
    if backup_pack_dir.exists() and any(backup_pack_dir.iterdir()):
        raise FileExistsError(
            f"backup pack directory already exists and is not empty: {backup_pack_dir}"
        )
    (backup_pack_dir / BACKUP_PACK_SHARDS_DIR).mkdir(parents=True, exist_ok=True)


def _write_zip_shard(
    source_root: Path,
    group: Sequence[BackupPackFileEntry],
    shard_path: Path,
) -> None:
    with zipfile.ZipFile(shard_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_entry in sorted(group, key=lambda item: item.relative_path):
            source_path = source_root / file_entry.relative_path
            info = zipfile.ZipInfo(file_entry.relative_path, date_time=ZIP_FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            with source_path.open("rb") as handle:
                archive.writestr(info, handle.read())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
