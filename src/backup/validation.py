"""Read-only archive backup pack validation and inspection APIs."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from src.backup.manifest import (
    CHECKSUM_SHA256,
    DERIVED_NON_CANONICAL_STATUS,
    BackupPackManifest,
    BackupPackValidationError,
    load_manifest,
    validate_manifest_contract,
)
from src.backup.restore import _normalize_archive_member_path
from src.backup.writer import BACKUP_PACK_MANIFEST_FILENAME, ZIP_SHARD_STRATEGY


@dataclass(frozen=True)
class BackupPackValidationResult:
    backup_pack_dir: Path
    manifest_path: Path
    backup_id: str | None
    is_valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    file_count: int
    shard_count: int
    total_uncompressed_bytes: int
    total_archive_bytes: int | None
    checked_shards: tuple[str, ...]
    checked_files: tuple[str, ...]
    manifest: BackupPackManifest | None


@dataclass(frozen=True)
class BackupPackShardSummary:
    shard_name: str
    relative_path: str
    shard_index: int
    file_count: int
    uncompressed_bytes: int
    archive_bytes: int | None
    checksum_algorithm: str | None
    checksum_present: bool


@dataclass(frozen=True)
class BackupPackDatasetSummary:
    dataset_name: str
    file_count: int
    total_uncompressed_bytes: int
    partition_keys: tuple[str, ...]


@dataclass(frozen=True)
class BackupPackInspection:
    backup_id: str
    backup_pack_dir: Path
    manifest_path: Path
    schema_version: int
    artifact_type: str
    canonical_status: str
    source_dataset_root: str
    included_datasets: tuple[str, ...]
    file_count: int
    shard_count: int
    total_uncompressed_bytes: int
    total_archive_bytes: int | None
    checksum_algorithm: str
    shard_strategy: str
    shard_size_mb: int | None
    datasets: tuple[BackupPackDatasetSummary, ...]
    shards: tuple[BackupPackShardSummary, ...]
    restore: Mapping[str, object]
    restore_target_hint: str
    manifest: BackupPackManifest


def validate_backup_pack(
    backup_pack_dir: Path | str,
    *,
    raise_on_error: bool = False,
) -> BackupPackValidationResult:
    """Validate an archive backup pack without mutating it."""

    pack_dir = Path(backup_pack_dir)
    manifest_path = pack_dir / BACKUP_PACK_MANIFEST_FILENAME
    errors: list[str] = []
    warnings: list[str] = []
    checked_shards: list[str] = []
    checked_files: list[str] = []
    manifest: BackupPackManifest | None = None

    try:
        manifest = validate_manifest_contract(load_manifest(manifest_path))
        _validate_manifest_restore_compatibility(manifest)
        checked_shards, checked_files = _validate_shards_and_inventory(pack_dir, manifest)
    except FileNotFoundError as exc:
        errors.append(str(exc))
    except (BackupPackValidationError, zipfile.BadZipFile) as exc:
        errors.append(str(exc))

    result = BackupPackValidationResult(
        backup_pack_dir=pack_dir,
        manifest_path=manifest_path,
        backup_id=manifest.backup_id if manifest is not None else None,
        is_valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        file_count=manifest.file_count if manifest is not None else 0,
        shard_count=len(manifest.shards) if manifest is not None else 0,
        total_uncompressed_bytes=manifest.total_uncompressed_bytes if manifest is not None else 0,
        total_archive_bytes=manifest.total_archive_bytes if manifest is not None else None,
        checked_shards=tuple(checked_shards),
        checked_files=tuple(checked_files),
        manifest=manifest,
    )
    if raise_on_error and not result.is_valid:
        raise BackupPackValidationError("; ".join(result.errors))
    return result


def inspect_backup_pack(backup_pack_dir: Path | str) -> BackupPackInspection:
    """Return deterministic manifest-based backup pack inspection details."""

    pack_dir = Path(backup_pack_dir)
    manifest_path = pack_dir / BACKUP_PACK_MANIFEST_FILENAME
    manifest = validate_manifest_contract(load_manifest(manifest_path))
    return BackupPackInspection(
        backup_id=manifest.backup_id,
        backup_pack_dir=pack_dir,
        manifest_path=manifest_path,
        schema_version=manifest.schema_version,
        artifact_type=manifest.artifact_type,
        canonical_status=manifest.canonical_status,
        source_dataset_root=manifest.source_dataset_root,
        included_datasets=manifest.included_datasets,
        file_count=manifest.file_count,
        shard_count=len(manifest.shards),
        total_uncompressed_bytes=manifest.total_uncompressed_bytes,
        total_archive_bytes=manifest.total_archive_bytes,
        checksum_algorithm=manifest.checksum_algorithm,
        shard_strategy=manifest.shard_strategy,
        shard_size_mb=manifest.shard_size_mb,
        datasets=_dataset_summaries(manifest),
        shards=tuple(
            BackupPackShardSummary(
                shard_name=shard.shard_name,
                relative_path=shard.relative_path,
                shard_index=shard.shard_index,
                file_count=shard.file_count,
                uncompressed_bytes=shard.uncompressed_bytes,
                archive_bytes=shard.archive_bytes,
                checksum_algorithm=shard.checksum_algorithm,
                checksum_present=bool(shard.checksum),
            )
            for shard in sorted(manifest.shards, key=lambda item: item.shard_index)
        ),
        restore=manifest.restore.to_dict(),
        restore_target_hint=manifest.source_dataset_root,
        manifest=manifest,
    )


def _validate_manifest_restore_compatibility(manifest: BackupPackManifest) -> None:
    if manifest.canonical_status != DERIVED_NON_CANONICAL_STATUS:
        raise BackupPackValidationError("manifest canonical_status must be derived_non_canonical")
    if manifest.shard_strategy != ZIP_SHARD_STRATEGY:
        raise BackupPackValidationError("restore compatibility requires size_limited_zip shards")
    if manifest.file_count > 0 and not manifest.shards:
        raise BackupPackValidationError("manifest must include shard metadata")
    if manifest.checksum_algorithm != CHECKSUM_SHA256:
        raise BackupPackValidationError("manifest checksum_algorithm must be sha256")


def _validate_shards_and_inventory(
    backup_pack_dir: Path,
    manifest: BackupPackManifest,
) -> tuple[list[str], list[str]]:
    expected = {file_entry.relative_path: file_entry for file_entry in manifest.files}
    seen: dict[str, str] = {}
    checked_shards: list[str] = []

    for shard in sorted(manifest.shards, key=lambda item: item.shard_index):
        shard_path = backup_pack_dir / shard.relative_path
        if not _is_relative_to(
            shard_path.resolve(strict=False), backup_pack_dir.resolve(strict=False)
        ):
            raise BackupPackValidationError(
                f"archive shard path escapes backup pack: {shard.relative_path}"
            )
        if not shard_path.is_file():
            raise FileNotFoundError(f"archive shard file is missing: {shard.relative_path}")
        if shard.archive_bytes is not None and shard_path.stat().st_size != shard.archive_bytes:
            raise BackupPackValidationError(
                f"archive shard size does not match manifest: {shard.relative_path}"
            )
        if shard.checksum and _sha256_file(shard_path) != shard.checksum:
            raise BackupPackValidationError(
                f"archive shard checksum does not match manifest: {shard.relative_path}"
            )
        try:
            with zipfile.ZipFile(shard_path) as archive:
                members = sorted(archive.infolist(), key=lambda item: item.filename)
                for info in members:
                    if info.is_dir():
                        raise BackupPackValidationError(
                            f"archive member is not expected file inventory: {info.filename}"
                        )
                    relative_path = _normalize_archive_member_path(info.filename)
                    if relative_path not in expected:
                        raise BackupPackValidationError(
                            f"archive member is not listed in manifest files: {relative_path}"
                        )
                    if relative_path in seen:
                        raise BackupPackValidationError(
                            f"archive member appears in more than one shard: {relative_path}"
                        )
                    payload = archive.read(info)
                    file_entry = expected[relative_path]
                    if len(payload) != file_entry.size_bytes:
                        raise BackupPackValidationError(
                            f"archive member size does not match manifest: {relative_path}"
                        )
                    if file_entry.checksum and _sha256_bytes(payload) != file_entry.checksum:
                        raise BackupPackValidationError(
                            f"archive member checksum does not match manifest: {relative_path}"
                        )
                    seen[relative_path] = shard.relative_path
        except zipfile.BadZipFile as exc:
            raise BackupPackValidationError(
                f"archive shard is not a readable zip file: {shard.relative_path}"
            ) from exc
        checked_shards.append(shard.relative_path)

    missing = sorted(set(expected) - set(seen))
    if missing:
        raise BackupPackValidationError(
            "archive shards are missing manifest file(s): " + ", ".join(missing)
        )
    return checked_shards, sorted(seen)


def _dataset_summaries(manifest: BackupPackManifest) -> tuple[BackupPackDatasetSummary, ...]:
    grouped: dict[str, list] = {}
    for file_entry in manifest.files:
        dataset_name = file_entry.dataset_name or "unknown"
        grouped.setdefault(dataset_name, []).append(file_entry)
    summaries = []
    for dataset_name in sorted(grouped):
        entries = grouped[dataset_name]
        partition_keys = sorted({key for file_entry in entries for key in file_entry.partitions})
        summaries.append(
            BackupPackDatasetSummary(
                dataset_name=dataset_name,
                file_count=len(entries),
                total_uncompressed_bytes=sum(file_entry.size_bytes for file_entry in entries),
                partition_keys=tuple(partition_keys),
            )
        )
    return tuple(summaries)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
