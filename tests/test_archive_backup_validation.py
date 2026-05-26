from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from src.backup import (
    BackupPackManifest,
    BackupPackShardEntry,
    BackupPackValidationError,
    create_backup_pack,
    inspect_backup_pack,
    validate_backup_pack,
    write_manifest,
)

FIXED_CREATED_AT = "2026-05-26T15:00:00Z"


def write_parquet_like(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_file_checksums(pack_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(pack_dir).as_posix(): sha256_file(path)
        for path in sorted(pack_dir.rglob("*"))
        if path.is_file()
    }


def synthetic_dataset(workspace_root: Path) -> Path:
    dataset_root = workspace_root / "data" / "curated"
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-daily",
    )
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=MSFT" / "date=2026-05-22" / "part-001.parquet",
        b"msft-daily",
    )
    write_parquet_like(
        dataset_root / "bars_1m" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-minute",
    )
    return dataset_root


def create_pack(tmp_path: Path):
    dataset_root = synthetic_dataset(tmp_path)
    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_validation",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )
    return dataset_root, result


def test_validate_backup_pack_success(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is True
    assert result.errors == ()
    assert result.warnings == ()
    assert result.backup_id == "backup_validation"
    assert result.file_count == 3
    assert result.shard_count == 1
    assert result.total_uncompressed_bytes == pack.manifest.total_uncompressed_bytes
    assert result.total_archive_bytes == pack.manifest.total_archive_bytes
    assert result.checked_shards == ("shards/shard-000000.zip",)
    assert result.checked_files == tuple(
        file_entry.relative_path for file_entry in pack.manifest.files
    )
    assert result.manifest == pack.manifest


def test_validate_backup_pack_missing_manifest_failure(tmp_path: Path) -> None:
    pack_dir = tmp_path / "backups" / "missing_manifest"
    pack_dir.mkdir(parents=True)

    result = validate_backup_pack(pack_dir)

    assert result.is_valid is False
    assert result.manifest is None
    assert any("manifest.json" in error for error in result.errors)


def test_validate_backup_pack_missing_shard_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    pack.shard_paths[0].unlink()

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert any("archive shard file is missing" in error for error in result.errors)


def test_validate_backup_pack_corrupt_shard_checksum_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    pack.shard_paths[0].write_bytes(pack.shard_paths[0].read_bytes() + b"corrupt")

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert any("shard size" in error or "shard checksum" in error for error in result.errors)


def test_validate_backup_pack_malformed_zip_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    shard_path = pack.shard_paths[0]
    shard_path.write_bytes(b"not-a-zip")
    _rewrite_first_shard_metadata(pack.manifest, pack.manifest_path, shard_path)

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert result.errors == ("archive shard is not a readable zip file: shards/shard-000000.zip",)


def test_validate_backup_pack_unsafe_zip_member_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    shard_path = pack.shard_paths[0]
    _rewrite_zip(shard_path, {"../escape.parquet": b"escape"})
    _rewrite_first_shard_metadata(pack.manifest, pack.manifest_path, shard_path)

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert any("archive member path" in error for error in result.errors)


def test_validate_backup_pack_missing_manifest_inventory_member_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    shard_path = pack.shard_paths[0]
    first_file = pack.manifest.files[0]
    _rewrite_zip(shard_path, {first_file.relative_path: b"aapl-minute"})
    _rewrite_first_shard_metadata(pack.manifest, pack.manifest_path, shard_path)

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert any("missing manifest file" in error for error in result.errors)


def test_validate_backup_pack_extra_archive_member_failure(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    shard_path = pack.shard_paths[0]
    with zipfile.ZipFile(shard_path, mode="a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extra/part.parquet", b"extra")
    _rewrite_first_shard_metadata(pack.manifest, pack.manifest_path, shard_path)

    result = validate_backup_pack(pack.backup_pack_dir)

    assert result.is_valid is False
    assert any("not listed in manifest files" in error for error in result.errors)


def test_validate_backup_pack_raise_on_error(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    pack.shard_paths[0].unlink()

    with pytest.raises(BackupPackValidationError, match="archive shard file is missing"):
        validate_backup_pack(pack.backup_pack_dir, raise_on_error=True)


def test_inspect_backup_pack_summary_is_deterministic(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)

    inspection = inspect_backup_pack(pack.backup_pack_dir)

    assert inspection.backup_id == "backup_validation"
    assert inspection.backup_pack_dir == pack.backup_pack_dir
    assert inspection.manifest_path == pack.manifest_path
    assert inspection.schema_version == 1
    assert inspection.artifact_type == "archive_backup_pack"
    assert inspection.canonical_status == "derived_non_canonical"
    assert inspection.source_dataset_root == "data/curated"
    assert inspection.included_datasets == ("bars_1m", "bars_daily")
    assert inspection.file_count == 3
    assert inspection.shard_count == 1
    assert inspection.total_uncompressed_bytes == pack.manifest.total_uncompressed_bytes
    assert inspection.total_archive_bytes == pack.manifest.total_archive_bytes
    assert inspection.checksum_algorithm == "sha256"
    assert inspection.shard_strategy == "size_limited_zip"
    assert inspection.shard_size_mb == 512
    assert [dataset.dataset_name for dataset in inspection.datasets] == ["bars_1m", "bars_daily"]
    assert [dataset.file_count for dataset in inspection.datasets] == [1, 2]
    assert inspection.datasets[0].partition_keys == ("date", "symbol")
    assert [shard.relative_path for shard in inspection.shards] == ["shards/shard-000000.zip"]
    assert inspection.shards[0].checksum_present is True
    assert inspection.restore["source_root_semantics"] == "workspace_relative"
    assert inspection.restore_target_hint == "data/curated"
    assert inspection.manifest == pack.manifest


def test_inspection_does_not_mutate_pack(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    before = pack_file_checksums(pack.backup_pack_dir)

    inspect_backup_pack(pack.backup_pack_dir)

    assert pack_file_checksums(pack.backup_pack_dir) == before


def test_validation_does_not_mutate_pack(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    before = pack_file_checksums(pack.backup_pack_dir)

    validate_backup_pack(pack.backup_pack_dir)

    assert pack_file_checksums(pack.backup_pack_dir) == before


def test_validation_and_inspection_do_not_create_restore_roots(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"

    validate_backup_pack(pack.backup_pack_dir)
    inspect_backup_pack(pack.backup_pack_dir)

    assert not restore_root.exists()


def _rewrite_zip(shard_path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(shard_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            archive.writestr(name, members[name])


def _rewrite_first_shard_metadata(
    manifest: BackupPackManifest,
    manifest_path: Path,
    shard_path: Path,
) -> None:
    first_shard = manifest.shards[0]
    updated_shard = BackupPackShardEntry(
        shard_name=first_shard.shard_name,
        relative_path=first_shard.relative_path,
        shard_index=first_shard.shard_index,
        file_count=first_shard.file_count,
        uncompressed_bytes=first_shard.uncompressed_bytes,
        archive_bytes=shard_path.stat().st_size,
        checksum=sha256_file(shard_path),
    )
    updated_manifest = BackupPackManifest(
        backup_id=manifest.backup_id,
        created_at_utc=manifest.created_at_utc,
        source_dataset_root=manifest.source_dataset_root,
        files=manifest.files,
        shards=(updated_shard, *manifest.shards[1:]),
        included_datasets=manifest.included_datasets,
        shard_strategy=manifest.shard_strategy,
        shard_size_mb=manifest.shard_size_mb,
        total_archive_bytes=sum(
            shard.archive_bytes or 0 for shard in (updated_shard, *manifest.shards[1:])
        ),
        metadata=manifest.metadata,
        notes=manifest.notes,
    )
    write_manifest(updated_manifest, manifest_path)
