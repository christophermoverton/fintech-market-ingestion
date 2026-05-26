from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from src.backup import (
    CHECKSUM_SHA256,
    ZIP_SHARD_STRATEGY,
    BackupPackFileEntry,
    BackupPackManifest,
    BackupPackShardEntry,
    BackupPackValidationError,
    create_backup_pack,
    load_manifest,
    validate_manifest_contract,
)

FIXED_CREATED_AT = "2026-05-26T13:00:00Z"


def write_parquet_like(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_checksums(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*.parquet"))
    }


def zip_member_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def all_zip_member_names(paths: tuple[Path, ...]) -> list[str]:
    names: list[str] = []
    for path in paths:
        names.extend(zip_member_names(path))
    return names


def small_partitioned_dataset(workspace_root: Path) -> Path:
    dataset_root = workspace_root / "data" / "curated"
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=MSFT" / "date=2026-05-22" / "part-001.parquet",
        b"msft-daily",
    )
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-daily",
    )
    write_parquet_like(
        dataset_root / "bars_1m" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-minute",
    )
    return dataset_root


def test_create_backup_pack_writes_single_deterministic_zip_shard(tmp_path: Path) -> None:
    dataset_root = small_partitioned_dataset(tmp_path)
    before = source_checksums(dataset_root)

    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_single",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )

    assert result.dry_run is False
    assert result.backup_pack_dir == tmp_path / "backups" / "backup_single"
    assert result.manifest_path.is_file()
    assert len(result.shard_paths) == 1
    assert result.shard_paths[0].is_file()
    assert zip_member_names(result.shard_paths[0]) == [
        "bars_1m/symbol=AAPL/date=2026-05-22/part-000.parquet",
        "bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet",
        "bars_daily/symbol=MSFT/date=2026-05-22/part-001.parquet",
    ]

    manifest = load_manifest(result.manifest_path)
    validate_manifest_contract(manifest)
    assert manifest.backup_id == "backup_single"
    assert manifest.source_dataset_root == "data/curated"
    assert manifest.shard_strategy == ZIP_SHARD_STRATEGY
    assert manifest.shard_size_mb == 512
    assert manifest.total_archive_bytes == result.shard_paths[0].stat().st_size
    assert manifest.shards[0].archive_bytes == result.shard_paths[0].stat().st_size
    assert manifest.shards[0].checksum == sha256_file(result.shard_paths[0])
    assert source_checksums(dataset_root) == before


def test_create_backup_pack_splits_files_into_multiple_size_limited_shards(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "data" / "curated"
    write_parquet_like(dataset_root / "bars_daily" / "part-c.parquet", b"c" * 700_000)
    write_parquet_like(dataset_root / "bars_daily" / "part-a.parquet", b"a" * 700_000)
    write_parquet_like(dataset_root / "bars_daily" / "part-b.parquet", b"b" * 700_000)

    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_multi",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=1,
    )

    assert [path.name for path in result.shard_paths] == [
        "shard-000000.zip",
        "shard-000001.zip",
        "shard-000002.zip",
    ]
    assert [shard.shard_name for shard in result.manifest.shards] == [
        "shard-000000.zip",
        "shard-000001.zip",
        "shard-000002.zip",
    ]
    assert all(shard.file_count == 1 for shard in result.manifest.shards)
    assert all(shard.uncompressed_bytes == 700_000 for shard in result.manifest.shards)
    assert [shard.archive_bytes for shard in result.manifest.shards] == [
        path.stat().st_size for path in result.shard_paths
    ]
    assert [shard.checksum for shard in result.manifest.shards] == [
        sha256_file(path) for path in result.shard_paths
    ]
    assert sorted(all_zip_member_names(result.shard_paths)) == [
        "bars_daily/part-a.parquet",
        "bars_daily/part-b.parquet",
        "bars_daily/part-c.parquet",
    ]
    assert result.total_archive_bytes == sum(path.stat().st_size for path in result.shard_paths)


def test_file_larger_than_shard_limit_is_placed_alone(tmp_path: Path) -> None:
    dataset_root = tmp_path / "data" / "curated"
    write_parquet_like(dataset_root / "bars_daily" / "large.parquet", b"x" * 1_200_000)
    write_parquet_like(dataset_root / "bars_daily" / "small.parquet", b"small")

    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_large_file",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=1,
    )

    assert [zip_member_names(path) for path in result.shard_paths] == [
        ["bars_daily/large.parquet"],
        ["bars_daily/small.parquet"],
    ]
    assert [shard.file_count for shard in result.manifest.shards] == [1, 1]
    assert result.manifest.shards[0].uncompressed_bytes == 1_200_000


def test_archive_member_and_manifest_file_ordering_are_deterministic(tmp_path: Path) -> None:
    dataset_root = tmp_path / "data" / "curated"
    write_parquet_like(dataset_root / "z_dataset" / "part.parquet", b"z")
    write_parquet_like(dataset_root / "a_dataset" / "part.parquet", b"a")
    write_parquet_like(dataset_root / "m_dataset" / "part.parquet", b"m")

    first = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups_first",
        backup_id="backup_ordered",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )
    second = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups_second",
        backup_id="backup_ordered",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )

    expected_order = [
        "a_dataset/part.parquet",
        "m_dataset/part.parquet",
        "z_dataset/part.parquet",
    ]
    assert [entry.relative_path for entry in first.manifest.files] == expected_order
    assert zip_member_names(first.shard_paths[0]) == expected_order
    assert sha256_file(first.shard_paths[0]) == sha256_file(second.shard_paths[0])


def test_dry_run_returns_planned_manifest_without_writing_archives(tmp_path: Path) -> None:
    dataset_root = small_partitioned_dataset(tmp_path)
    before = source_checksums(dataset_root)

    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_dry_run",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.backup_pack_dir == tmp_path / "backups" / "backup_dry_run"
    assert not result.backup_pack_dir.exists()
    assert not result.manifest_path.exists()
    assert result.shard_paths == (
        tmp_path / "backups" / "backup_dry_run" / "shards" / "shard-000000.zip",
    )
    assert result.total_archive_bytes is None
    assert result.manifest.total_archive_bytes is None
    assert result.manifest.shards[0].archive_bytes is None
    assert result.manifest.shards[0].checksum is None
    validate_manifest_contract(result.manifest)
    assert source_checksums(dataset_root) == before


def test_source_files_are_not_mutated_by_backup_writer(tmp_path: Path) -> None:
    dataset_root = small_partitioned_dataset(tmp_path)
    before = source_checksums(dataset_root)

    create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_immutability",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )

    assert source_checksums(dataset_root) == before


def test_written_manifest_loads_through_contract_validation(tmp_path: Path) -> None:
    dataset_root = small_partitioned_dataset(tmp_path)

    result = create_backup_pack(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        backup_root=tmp_path / "backups",
        backup_id="backup_validation",
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )

    manifest = load_manifest(result.manifest_path)

    assert validate_manifest_contract(manifest) == manifest
    assert manifest.file_count == 3
    assert manifest.total_uncompressed_bytes == sum(
        path.stat().st_size for path in dataset_root.rglob("*.parquet")
    )


@pytest.mark.parametrize(
    "shard_name",
    [
        "nested/shard-000000.zip",
        "nested\\shard-000000.zip",
        "../shard-000000.zip",
        "/tmp/shard-000000.zip",
        "C:/tmp/shard-000000.zip",
        "~/shard-000000.zip",
    ],
)
def test_invalid_shard_names_are_rejected(shard_name: str) -> None:
    with pytest.raises(BackupPackValidationError, match="shard_name"):
        BackupPackShardEntry(
            shard_name=shard_name,
            relative_path="shards/shard-000000.zip",
            shard_index=0,
            file_count=1,
            uncompressed_bytes=1,
        )


def test_unsupported_checksum_algorithms_are_rejected() -> None:
    with pytest.raises(BackupPackValidationError, match="checksum_algorithm.*sha256"):
        BackupPackFileEntry(
            relative_path="part.parquet",
            size_bytes=1,
            checksum_algorithm="md5",
        )

    with pytest.raises(BackupPackValidationError, match="checksum_algorithm.*sha256"):
        BackupPackShardEntry(
            shard_name="shard-000000.zip",
            relative_path="shards/shard-000000.zip",
            shard_index=0,
            file_count=1,
            uncompressed_bytes=1,
            checksum_algorithm="md5",
        )

    with pytest.raises(BackupPackValidationError, match="checksum_algorithm.*sha256"):
        BackupPackManifest(
            backup_id="backup_20260526_130000_data_curated",
            created_at_utc=FIXED_CREATED_AT,
            source_dataset_root="data/curated",
            checksum_algorithm="md5",
        )

    assert CHECKSUM_SHA256 == "sha256"
