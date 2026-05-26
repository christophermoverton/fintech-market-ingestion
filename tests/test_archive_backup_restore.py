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
    restore_backup_pack,
    validate_manifest_contract,
    write_manifest,
)

FIXED_CREATED_AT = "2026-05-26T14:00:00Z"


def write_parquet_like(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_checksums(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*.parquet"))
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
        backup_id="backup_restore",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )
    return dataset_root, result


def test_restore_backup_pack_round_trip_recreates_dataset_layout(tmp_path: Path) -> None:
    dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"

    result = restore_backup_pack(
        backup_pack_dir=pack.backup_pack_dir,
        restore_root=restore_root,
    )

    assert inventory_checksums(restore_root) == inventory_checksums(dataset_root)
    assert sorted(path.relative_to(restore_root).as_posix() for path in result.restored_paths) == [
        "bars_1m/symbol=AAPL/date=2026-05-22/part-000.parquet",
        "bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet",
        "bars_daily/symbol=MSFT/date=2026-05-22/part-001.parquet",
    ]
    assert validate_manifest_contract(result.manifest) == result.manifest
    assert result.backup_id == "backup_restore"
    assert result.backup_pack_dir == pack.backup_pack_dir
    assert result.manifest_path == pack.manifest_path
    assert result.restore_root == restore_root
    assert result.restored_file_count == 3
    assert result.restored_bytes == sum(
        path.stat().st_size for path in dataset_root.rglob("*.parquet")
    )
    assert result.overwrite_policy == "fail"


def test_restore_fails_before_writing_when_shard_is_missing(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    pack.shard_paths[0].unlink()
    restore_root = tmp_path / "restore" / "data" / "curated"

    with pytest.raises(FileNotFoundError, match="archive shard file is missing"):
        restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)

    assert not restore_root.exists()


def test_restore_fails_before_writing_when_shard_checksum_is_corrupt(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    pack.shard_paths[0].write_bytes(pack.shard_paths[0].read_bytes() + b"corrupt")
    restore_root = tmp_path / "restore" / "data" / "curated"

    with pytest.raises(BackupPackValidationError, match="shard size|shard checksum"):
        restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)

    assert not restore_root.exists()


@pytest.mark.parametrize(
    "member_name",
    [
        "../escape.parquet",
        "/tmp/escape.parquet",
        "C:/tmp/escape.parquet",
    ],
)
def test_restore_rejects_unsafe_archive_member_paths(tmp_path: Path, member_name: str) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    shard_path = pack.shard_paths[0]
    with zipfile.ZipFile(shard_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, b"escape")
    _rewrite_first_shard_metadata(pack.manifest, pack.manifest_path, shard_path)
    restore_root = tmp_path / "restore" / "data" / "curated"

    with pytest.raises(BackupPackValidationError, match="archive member path"):
        restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)

    assert not restore_root.exists()


def test_restore_fail_policy_refuses_existing_targets_before_writing(tmp_path: Path) -> None:
    dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"
    restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)
    target = restore_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet"
    target.write_bytes(b"local-change")

    with pytest.raises(FileExistsError, match="restore target already exists"):
        restore_backup_pack(
            backup_pack_dir=pack.backup_pack_dir,
            restore_root=restore_root,
            overwrite_policy="fail",
        )

    assert target.read_bytes() == b"local-change"
    assert inventory_checksums(dataset_root)[
        target.relative_to(restore_root).as_posix()
    ] != sha256_file(target)


def test_restore_replace_policy_replaces_existing_archive_files(tmp_path: Path) -> None:
    dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"
    restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)
    target = restore_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet"
    target.write_bytes(b"local-change")

    result = restore_backup_pack(
        backup_pack_dir=pack.backup_pack_dir,
        restore_root=restore_root,
        overwrite_policy="replace",
    )

    assert inventory_checksums(restore_root) == inventory_checksums(dataset_root)
    assert (
        target.read_bytes()
        == (
            dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet"
        ).read_bytes()
    )
    assert result.restored_file_count == 3
    assert result.overwrite_policy == "replace"


def test_restore_merge_policy_skips_matching_existing_files(tmp_path: Path) -> None:
    dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"
    restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)

    result = restore_backup_pack(
        backup_pack_dir=pack.backup_pack_dir,
        restore_root=restore_root,
        overwrite_policy="merge",
    )

    assert inventory_checksums(restore_root) == inventory_checksums(dataset_root)
    assert result.restored_file_count == 0
    assert result.restored_bytes == 0
    assert result.overwrite_policy == "merge"


def test_restore_merge_policy_fails_when_existing_file_differs(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"
    restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)
    target = restore_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet"
    target.write_bytes(b"local-change")

    with pytest.raises(BackupPackValidationError, match="merge target checksum differs"):
        restore_backup_pack(
            backup_pack_dir=pack.backup_pack_dir,
            restore_root=restore_root,
            overwrite_policy="merge",
        )

    assert target.read_bytes() == b"local-change"


def test_restore_does_not_mutate_backup_pack_files(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    before = {
        path.relative_to(pack.backup_pack_dir).as_posix(): sha256_file(path)
        for path in [pack.manifest_path, *pack.shard_paths]
    }

    restore_backup_pack(
        backup_pack_dir=pack.backup_pack_dir,
        restore_root=tmp_path / "restore" / "data" / "curated",
    )

    after = {
        path.relative_to(pack.backup_pack_dir).as_posix(): sha256_file(path)
        for path in [pack.manifest_path, *pack.shard_paths]
    }
    assert after == before


def test_restore_result_object_reports_expected_fields(tmp_path: Path) -> None:
    _dataset_root, pack = create_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"

    result = restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)

    assert result.backup_id == "backup_restore"
    assert result.backup_pack_dir == pack.backup_pack_dir
    assert result.manifest_path == pack.manifest_path
    assert result.restore_root == restore_root
    assert result.restored_file_count == len(result.restored_paths)
    assert result.restored_bytes == sum(path.stat().st_size for path in result.restored_paths)
    assert result.overwrite_policy == "fail"
    assert result.manifest.backup_id == "backup_restore"


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
