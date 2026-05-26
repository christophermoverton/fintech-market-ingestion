from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.backup import (
    DERIVED_NON_CANONICAL_STATUS,
    BackupPackFileEntry,
    BackupPackManifest,
    BackupPackShardEntry,
    BackupPackValidationError,
    build_archive_backup_pack_manifest,
    build_file_inventory,
    dumps_manifest_json,
    loads_manifest,
    validate_manifest_contract,
)

FIXED_CREATED_AT = "2026-05-26T12:00:00Z"


def write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def synthetic_dataset(root: Path) -> Path:
    dataset_root = root / "data" / "curated"
    write_bytes(
        dataset_root / "bars_1m" / "symbol=MSFT" / "date=2026-05-22" / "part-001.parquet",
        b"minute-bars",
    )
    write_bytes(
        dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"daily-bars",
    )
    write_bytes(dataset_root / "bars_daily" / "_metadata.txt", b"not part of inventory")
    return dataset_root


def test_file_inventory_uses_relative_paths_and_infers_partitions(tmp_path: Path) -> None:
    dataset_root = synthetic_dataset(tmp_path)

    inventory = build_file_inventory(dataset_root)

    assert [entry.relative_path for entry in inventory] == [
        "bars_1m/symbol=MSFT/date=2026-05-22/part-001.parquet",
        "bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet",
    ]
    assert {entry.dataset_name for entry in inventory} == {"bars_1m", "bars_daily"}
    assert inventory[0].partitions == {"date": "2026-05-22", "symbol": "MSFT"}
    assert all(not Path(entry.relative_path).is_absolute() for entry in inventory)
    assert all(str(tmp_path) not in entry.relative_path for entry in inventory)
    assert all(entry.checksum_algorithm == "sha256" for entry in inventory)


def test_manifest_json_is_deterministic_for_equivalent_inventory(tmp_path: Path) -> None:
    dataset_root = synthetic_dataset(tmp_path)

    first = build_archive_backup_pack_manifest(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        created_at_utc=FIXED_CREATED_AT,
        shard_strategy="size_limited_tar_zstd",
        shard_size_mb=512,
    )
    second = build_archive_backup_pack_manifest(
        workspace_root=tmp_path,
        source_dataset_root=dataset_root,
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
        shard_strategy="size_limited_tar_zstd",
    )

    assert dumps_manifest_json(first) == dumps_manifest_json(second)
    assert dumps_manifest_json(first).endswith("\n")
    assert dumps_manifest_json(first) == (
        json.dumps(first.to_dict(), sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
    )


def test_manifest_sorts_files_shards_and_metadata() -> None:
    manifest = BackupPackManifest(
        backup_id="backup_20260526_120000_data_curated",
        created_at_utc=FIXED_CREATED_AT,
        source_dataset_root="data/curated",
        files=(
            BackupPackFileEntry(relative_path="z/part.parquet", size_bytes=1),
            BackupPackFileEntry(relative_path="a/part.parquet", size_bytes=2),
        ),
        shards=(
            BackupPackShardEntry(
                shard_name="pack-001.tar.zst",
                relative_path="shards/pack-001.tar.zst",
                shard_index=1,
                file_count=1,
                uncompressed_bytes=1,
            ),
            BackupPackShardEntry(
                shard_name="pack-000.tar.zst",
                relative_path="shards/pack-000.tar.zst",
                shard_index=0,
                file_count=1,
                uncompressed_bytes=2,
            ),
        ),
        metadata={"z": 1, "a": {"b": 2}},
    )
    data = manifest.to_dict()

    assert [entry["relative_path"] for entry in data["files"]] == [
        "a/part.parquet",
        "z/part.parquet",
    ]
    assert [entry["shard_index"] for entry in data["shards"]] == [0, 1]
    assert list(data["metadata"]) == ["a", "z"]
    assert data["canonical_status"] == DERIVED_NON_CANONICAL_STATUS


def test_complete_fixture_validates_successfully() -> None:
    fixture = Path("tests/fixtures/archive_backup_pack_manifest.json")

    manifest = loads_manifest(fixture.read_text(encoding="utf-8"))

    assert manifest.backup_id == "backup_20260526_120000_data_curated"
    assert manifest.file_count == 2
    assert manifest.total_uncompressed_bytes == 46
    assert manifest.canonical_status == DERIVED_NON_CANONICAL_STATUS


def test_missing_schema_version_fails_with_actionable_error() -> None:
    data = json.loads(Path("tests/fixtures/archive_backup_pack_manifest.json").read_text())
    del data["schema_version"]

    with pytest.raises(BackupPackValidationError, match="missing required field.*schema_version"):
        validate_manifest_contract(data)


def test_missing_derived_non_canonical_status_fails() -> None:
    data = json.loads(Path("tests/fixtures/archive_backup_pack_manifest.json").read_text())
    del data["canonical_status"]

    with pytest.raises(BackupPackValidationError, match="missing required field.*canonical_status"):
        validate_manifest_contract(data)


def test_authoritative_canonical_status_is_rejected() -> None:
    data = json.loads(Path("tests/fixtures/archive_backup_pack_manifest.json").read_text())
    data["canonical_status"] = "canonical"

    with pytest.raises(BackupPackValidationError, match="canonical_status.*derived_non_canonical"):
        validate_manifest_contract(data)


def test_absolute_paths_are_rejected_in_serialized_manifest_fields() -> None:
    with pytest.raises(BackupPackValidationError, match="source_dataset_root.*absolute"):
        BackupPackManifest(
            backup_id="backup_20260526_120000_data_curated",
            created_at_utc=FIXED_CREATED_AT,
            source_dataset_root="/tmp/data/curated",
        )

    with pytest.raises(BackupPackValidationError, match="files\\[\\].relative_path.*drive-qualified"):
        BackupPackFileEntry(relative_path="C:/tmp/data/part.parquet", size_bytes=1)


def test_reported_file_count_and_bytes_must_match_entries() -> None:
    data = json.loads(Path("tests/fixtures/archive_backup_pack_manifest.json").read_text())
    data["file_count"] = 99

    with pytest.raises(BackupPackValidationError, match="file_count must match"):
        validate_manifest_contract(data)

    data = json.loads(Path("tests/fixtures/archive_backup_pack_manifest.json").read_text())
    data["total_uncompressed_bytes"] = 99

    with pytest.raises(BackupPackValidationError, match="total_uncompressed_bytes must match"):
        validate_manifest_contract(data)
