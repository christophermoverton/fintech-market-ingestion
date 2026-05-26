"""Local restore workflow for archive backup packs."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.backup.manifest import (
    CHECKSUM_SHA256,
    DERIVED_NON_CANONICAL_STATUS,
    BackupPackFileEntry,
    BackupPackManifest,
    BackupPackValidationError,
    load_manifest,
    validate_manifest_contract,
)
from src.backup.writer import BACKUP_PACK_MANIFEST_FILENAME, ZIP_SHARD_STRATEGY
from src.sessions.session_paths import normalize_workspace_relative_path

OVERWRITE_POLICY_FAIL = "fail"
OVERWRITE_POLICY_REPLACE = "replace"
OVERWRITE_POLICY_MERGE = "merge"
SUPPORTED_OVERWRITE_POLICIES = frozenset(
    {OVERWRITE_POLICY_FAIL, OVERWRITE_POLICY_REPLACE, OVERWRITE_POLICY_MERGE}
)


@dataclass(frozen=True)
class BackupPackRestoreResult:
    backup_id: str
    backup_pack_dir: Path
    manifest_path: Path
    restore_root: Path
    restored_paths: tuple[Path, ...]
    restored_file_count: int
    restored_bytes: int
    overwrite_policy: str
    manifest: BackupPackManifest


@dataclass(frozen=True)
class _RestoreCandidate:
    relative_path: str
    file_entry: BackupPackFileEntry
    shard_path: Path
    zip_member_name: str
    size_bytes: int


def restore_backup_pack(
    *,
    backup_pack_dir: Path | str,
    restore_root: Path | str,
    overwrite_policy: str = OVERWRITE_POLICY_FAIL,
) -> BackupPackRestoreResult:
    """Restore a validated archive backup pack into a local dataset root."""

    policy = _normalize_overwrite_policy(overwrite_policy)
    pack_dir = Path(backup_pack_dir)
    target_root = Path(restore_root)
    manifest_path = pack_dir / BACKUP_PACK_MANIFEST_FILENAME
    manifest = validate_manifest_contract(load_manifest(manifest_path))
    _validate_restore_manifest(manifest)
    candidates = _validate_pack_shards_and_members(pack_dir, manifest)
    skipped = _validate_target_policy(target_root, candidates, policy)

    restored_paths: list[Path] = []
    restored_bytes = 0
    target_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".archive-restore-",
        dir=target_root.parent,
    ) as tmp_dir:
        staging_root = Path(tmp_dir)
        _extract_candidates_to_staging(staging_root, candidates, skipped)
        for candidate in sorted(candidates, key=lambda item: item.relative_path):
            if candidate.relative_path in skipped:
                continue
            staged_path = staging_root / candidate.relative_path
            target_path = target_root / candidate.relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if policy == OVERWRITE_POLICY_REPLACE and target_path.exists():
                target_path.unlink()
            shutil.move(str(staged_path), str(target_path))
            restored_paths.append(target_path)
            restored_bytes += candidate.size_bytes

    _validate_restored_inventory(target_root, manifest)
    return BackupPackRestoreResult(
        backup_id=manifest.backup_id,
        backup_pack_dir=pack_dir,
        manifest_path=manifest_path,
        restore_root=target_root,
        restored_paths=tuple(restored_paths),
        restored_file_count=len(restored_paths),
        restored_bytes=restored_bytes,
        overwrite_policy=policy,
        manifest=manifest,
    )


def _normalize_overwrite_policy(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise BackupPackValidationError("overwrite_policy must be a non-empty string")
    if value not in SUPPORTED_OVERWRITE_POLICIES:
        raise BackupPackValidationError(
            "overwrite_policy must be one of: " + ", ".join(sorted(SUPPORTED_OVERWRITE_POLICIES))
        )
    return value


def _validate_restore_manifest(manifest: BackupPackManifest) -> None:
    if manifest.canonical_status != DERIVED_NON_CANONICAL_STATUS:
        raise BackupPackValidationError("manifest canonical_status must be derived_non_canonical")
    if manifest.shard_strategy != ZIP_SHARD_STRATEGY:
        raise BackupPackValidationError("restore currently supports size_limited_zip shards only")
    if manifest.file_count > 0 and not manifest.shards:
        raise BackupPackValidationError("manifest must include shard metadata for restore")
    if any(shard.checksum_algorithm != CHECKSUM_SHA256 for shard in manifest.shards):
        raise BackupPackValidationError("shard checksum_algorithm must be sha256")


def _validate_pack_shards_and_members(
    backup_pack_dir: Path,
    manifest: BackupPackManifest,
) -> tuple[_RestoreCandidate, ...]:
    expected = {file_entry.relative_path: file_entry for file_entry in manifest.files}
    seen: dict[str, _RestoreCandidate] = {}
    for shard in sorted(manifest.shards, key=lambda item: item.shard_index):
        shard_path = backup_pack_dir / shard.relative_path
        _validate_shard_file(shard_path, shard.archive_bytes, shard.checksum)
        with zipfile.ZipFile(shard_path) as archive:
            for info in sorted(archive.infolist(), key=lambda item: item.filename):
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
                seen[relative_path] = _RestoreCandidate(
                    relative_path=relative_path,
                    file_entry=file_entry,
                    shard_path=shard_path,
                    zip_member_name=info.filename,
                    size_bytes=len(payload),
                )

    missing = sorted(set(expected) - set(seen))
    if missing:
        raise BackupPackValidationError(
            "archive shards are missing manifest file(s): " + ", ".join(missing)
        )
    return tuple(seen[path] for path in sorted(seen))


def _validate_shard_file(
    shard_path: Path,
    expected_archive_bytes: int | None,
    expected_checksum: str | None,
) -> None:
    if not shard_path.is_file():
        raise FileNotFoundError(f"archive shard file is missing: {shard_path}")
    if expected_archive_bytes is not None and shard_path.stat().st_size != expected_archive_bytes:
        raise BackupPackValidationError(f"archive shard size does not match manifest: {shard_path}")
    if expected_checksum and _sha256_file(shard_path) != expected_checksum:
        raise BackupPackValidationError(
            f"archive shard checksum does not match manifest: {shard_path}"
        )


def _normalize_archive_member_path(value: str) -> str:
    try:
        return normalize_workspace_relative_path(value, field_name="archive member path")
    except ValueError as exc:
        raise BackupPackValidationError(str(exc)) from exc


def _validate_target_policy(
    restore_root: Path,
    candidates: Sequence[_RestoreCandidate],
    overwrite_policy: str,
) -> set[str]:
    skipped: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: item.relative_path):
        target_path = _safe_restore_target(restore_root, candidate.relative_path)
        if not target_path.exists():
            continue
        if overwrite_policy == OVERWRITE_POLICY_FAIL:
            raise FileExistsError(f"restore target already exists: {target_path}")
        if overwrite_policy == OVERWRITE_POLICY_MERGE:
            if not candidate.file_entry.checksum:
                raise BackupPackValidationError(
                    f"merge requires manifest file checksum for existing target: {target_path}"
                )
            if _sha256_file(target_path) != candidate.file_entry.checksum:
                raise BackupPackValidationError(
                    f"merge target checksum differs from archive member: {target_path}"
                )
            skipped.add(candidate.relative_path)
    return skipped


def _safe_restore_target(restore_root: Path, relative_path: str) -> Path:
    root = restore_root.resolve(strict=False)
    target_path = (restore_root / relative_path).resolve(strict=False)
    try:
        target_path.relative_to(root)
    except ValueError as exc:
        raise BackupPackValidationError(
            f"restore target escapes restore_root: {relative_path}"
        ) from exc
    return target_path


def _extract_candidates_to_staging(
    staging_root: Path,
    candidates: Sequence[_RestoreCandidate],
    skipped: set[str],
) -> None:
    by_shard: dict[Path, list[_RestoreCandidate]] = {}
    for candidate in candidates:
        if candidate.relative_path in skipped:
            continue
        by_shard.setdefault(candidate.shard_path, []).append(candidate)

    for shard_path in sorted(by_shard, key=lambda item: str(item)):
        with zipfile.ZipFile(shard_path) as archive:
            for candidate in sorted(by_shard[shard_path], key=lambda item: item.relative_path):
                staged_path = _safe_restore_target(staging_root, candidate.relative_path)
                staged_path.parent.mkdir(parents=True, exist_ok=True)
                with (
                    archive.open(candidate.zip_member_name) as source,
                    staged_path.open("wb") as dest,
                ):
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        dest.write(chunk)


def _validate_restored_inventory(restore_root: Path, manifest: BackupPackManifest) -> None:
    for file_entry in manifest.files:
        restored_path = _safe_restore_target(restore_root, file_entry.relative_path)
        if not restored_path.is_file():
            raise BackupPackValidationError(f"restored file is missing: {restored_path}")
        if restored_path.stat().st_size != file_entry.size_bytes:
            raise BackupPackValidationError(f"restored file size mismatch: {restored_path}")
        if file_entry.checksum and _sha256_file(restored_path) != file_entry.checksum:
            raise BackupPackValidationError(f"restored file checksum mismatch: {restored_path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
