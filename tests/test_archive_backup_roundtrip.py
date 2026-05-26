from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.backup import (
    ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE,
    DERIVED_NON_CANONICAL_STATUS,
    ZIP_SHARD_STRATEGY,
    create_backup_pack,
    inspect_backup_pack,
    restore_backup_pack,
    validate_backup_pack,
)
from src.cli.backup_data import main as backup_cli_main

FIXED_CREATED_AT = "2026-05-26T17:00:00Z"
BACKUP_ID = "backup_roundtrip"
EXPECTED_FILES = [
    "bars_1m/symbol=AAPL/date=2026-05-22/part-000.parquet",
    "bars_daily/symbol=AAPL/date=2026-05-22/part-000.parquet",
    "bars_daily/symbol=MSFT/date=2026-05-22/part-001.parquet",
]


def write_parquet_like(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def synthetic_partitioned_dataset(workspace_root: Path) -> Path:
    dataset_root = workspace_root / "data" / "curated"
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=MSFT" / "date=2026-05-22" / "part-001.parquet",
        b"msft daily deterministic payload\n",
    )
    write_parquet_like(
        dataset_root / "bars_1m" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl minute deterministic payload\n",
    )
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl daily deterministic payload\n",
    )
    return dataset_root


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_checksums(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*.parquet"))
    }


def relative_file_paths(root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in sorted(root.rglob("*.parquet"))]


def pack_file_checksums(pack_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(pack_dir).as_posix(): sha256_file(path)
        for path in sorted(pack_dir.rglob("*"))
        if path.is_file()
    }


def manifest_json(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def create_roundtrip_pack(workspace_root: Path, backup_root: Path, backup_id: str = BACKUP_ID):
    dataset_root = synthetic_partitioned_dataset(workspace_root)
    pack = create_backup_pack(
        workspace_root=workspace_root,
        source_dataset_root=dataset_root,
        backup_root=backup_root,
        backup_id=backup_id,
        created_at_utc=FIXED_CREATED_AT,
        shard_size_mb=512,
    )
    return dataset_root, pack


def test_api_round_trip_validates_inspects_restores_and_matches_source(tmp_path: Path) -> None:
    dataset_root, pack = create_roundtrip_pack(tmp_path / "workspace", tmp_path / "backups")
    source_before = file_checksums(dataset_root)
    pack_before = pack_file_checksums(pack.backup_pack_dir)

    validation = validate_backup_pack(pack.backup_pack_dir)
    inspection = inspect_backup_pack(pack.backup_pack_dir)
    restore_root = tmp_path / "restore" / "data" / "curated"
    restore = restore_backup_pack(
        backup_pack_dir=pack.backup_pack_dir,
        restore_root=restore_root,
    )

    assert validation.is_valid is True
    assert validation.errors == ()
    assert validation.file_count == 3
    assert validation.shard_count == 1
    assert inspection.backup_id == BACKUP_ID
    assert inspection.included_datasets == ("bars_1m", "bars_daily")
    assert inspection.file_count == 3
    assert inspection.shard_count == 1
    assert inspection.shard_strategy == ZIP_SHARD_STRATEGY
    assert inspection.restore_target_hint == "data/curated"
    assert restore.restored_file_count == 3
    assert restore.restored_bytes == sum(
        path.stat().st_size for path in dataset_root.rglob("*.parquet")
    )
    assert relative_file_paths(restore_root) == EXPECTED_FILES
    assert file_checksums(restore_root) == source_before
    assert file_checksums(dataset_root) == source_before
    assert pack_file_checksums(pack.backup_pack_dir) == pack_before
    assert pack.manifest.canonical_status == DERIVED_NON_CANONICAL_STATUS
    assert pack.manifest.artifact_type == ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE


def test_equivalent_pack_creation_has_deterministic_manifest_and_shards(tmp_path: Path) -> None:
    first_dataset, first = create_roundtrip_pack(
        tmp_path / "workspace_first",
        tmp_path / "backups_first",
    )
    _second_dataset, second = create_roundtrip_pack(
        tmp_path / "workspace_second",
        tmp_path / "backups_second",
    )

    first_manifest_json = manifest_json(first.manifest_path)
    second_manifest_json = manifest_json(second.manifest_path)

    assert first_manifest_json == second_manifest_json
    assert first_manifest_json.endswith("\n")
    assert str(tmp_path) not in first_manifest_json
    assert tmp_path.as_posix() not in first_manifest_json
    assert [entry.relative_path for entry in first.manifest.files] == EXPECTED_FILES
    assert [shard.relative_path for shard in first.manifest.shards] == ["shards/shard-000000.zip"]
    assert first.manifest.included_datasets == ("bars_1m", "bars_daily")
    assert [sha256_file(path) for path in first.shard_paths] == [
        sha256_file(path) for path in second.shard_paths
    ]
    assert file_checksums(first_dataset) == {
        entry.relative_path: entry.checksum for entry in first.manifest.files
    }


@pytest.mark.parametrize("mode", ["missing", "corrupt"])
def test_invalid_shards_fail_validation_and_restore_writes_nothing(
    tmp_path: Path,
    mode: str,
) -> None:
    _dataset_root, pack = create_roundtrip_pack(tmp_path / "workspace", tmp_path / "backups")
    restore_root = tmp_path / "restore" / "data" / "curated"
    shard_path = pack.shard_paths[0]

    if mode == "missing":
        shard_path.unlink()
        expected = "archive shard file is missing"
    else:
        shard_path.write_bytes(shard_path.read_bytes() + b"corrupt")
        expected = "shard size|shard checksum"

    validation = validate_backup_pack(pack.backup_pack_dir)

    assert validation.is_valid is False
    assert any(
        "archive shard file is missing" in error
        or "shard size" in error
        or "shard checksum" in error
        for error in validation.errors
    )
    with pytest.raises((FileNotFoundError, ValueError), match=expected):
        restore_backup_pack(backup_pack_dir=pack.backup_pack_dir, restore_root=restore_root)
    assert not restore_root.exists()


def test_cli_round_trip_uses_shared_backup_workflow(tmp_path: Path, capsys) -> None:
    workspace_root = tmp_path / "workspace"
    dataset_root = synthetic_partitioned_dataset(workspace_root)
    source_before = file_checksums(dataset_root)
    backup_root = tmp_path / "backups"
    restore_root = tmp_path / "restore" / "data" / "curated"

    pack_rc = backup_cli_main(
        [
            "pack",
            "--workspace-root",
            str(workspace_root),
            "--source-dataset-root",
            str(dataset_root),
            "--backup-root",
            str(backup_root),
            "--backup-id",
            BACKUP_ID,
            "--created-at-utc",
            FIXED_CREATED_AT,
            "--shard-size-mb",
            "512",
        ]
    )
    validate_rc = backup_cli_main(["validate", "--backup-pack-dir", str(backup_root / BACKUP_ID)])
    inspect_rc = backup_cli_main(["inspect", "--backup-pack-dir", str(backup_root / BACKUP_ID)])
    restore_rc = backup_cli_main(
        [
            "restore",
            "--backup-pack-dir",
            str(backup_root / BACKUP_ID),
            "--restore-root",
            str(restore_root),
            "--overwrite-policy",
            "fail",
        ]
    )

    captured = capsys.readouterr()
    assert pack_rc == 0
    assert validate_rc == 0
    assert inspect_rc == 0
    assert restore_rc == 0
    assert "backup_id: backup_roundtrip" in captured.out
    assert "is_valid: True" in captured.out
    assert "included_datasets: bars_1m, bars_daily" in captured.out
    assert "restored_file_count: 3" in captured.out
    assert file_checksums(restore_root) == source_before

    (backup_root / BACKUP_ID / "shards" / "shard-000000.zip").unlink()
    invalid_rc = backup_cli_main(["validate", "--backup-pack-dir", str(backup_root / BACKUP_ID)])
    invalid_output = capsys.readouterr()

    assert invalid_rc == 1
    assert "is_valid: False" in invalid_output.out
    assert "archive shard file is missing" in invalid_output.out
