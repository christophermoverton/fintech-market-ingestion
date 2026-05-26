from __future__ import annotations

from pathlib import Path

import pytest

from src.cli.backup_data import main

FIXED_CREATED_AT = "2026-05-26T16:00:00Z"


def write_parquet_like(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def synthetic_dataset(workspace_root: Path) -> Path:
    dataset_root = workspace_root / "data" / "curated"
    write_parquet_like(
        dataset_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-daily",
    )
    write_parquet_like(
        dataset_root / "bars_1m" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet",
        b"aapl-minute",
    )
    return dataset_root


def run_pack(tmp_path: Path, backup_id: str = "backup_cli") -> Path:
    synthetic_dataset(tmp_path)
    backup_root = tmp_path / "backups"
    assert (
        main(
            [
                "pack",
                "--workspace-root",
                str(tmp_path),
                "--source-dataset-root",
                str(tmp_path / "data" / "curated"),
                "--backup-root",
                str(backup_root),
                "--backup-id",
                backup_id,
                "--created-at-utc",
                FIXED_CREATED_AT,
                "--shard-size-mb",
                "512",
            ]
        )
        == 0
    )
    return backup_root / backup_id


def test_backup_data_pack_command_succeeds(tmp_path: Path, capsys) -> None:
    dataset_root = synthetic_dataset(tmp_path)
    backup_root = tmp_path / "backups"

    rc = main(
        [
            "pack",
            "--workspace-root",
            str(tmp_path),
            "--source-dataset-root",
            str(dataset_root),
            "--backup-root",
            str(backup_root),
            "--backup-id",
            "backup_cli",
            "--created-at-utc",
            FIXED_CREATED_AT,
            "--metadata",
            "purpose=test",
            "--note",
            "CLI fixture",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "backup_id: backup_cli" in captured.out
    assert "manifest_path:" in captured.out
    assert "file_count: 2" in captured.out
    assert (backup_root / "backup_cli" / "manifest.json").is_file()


def test_backup_data_pack_dry_run_succeeds_without_writing(tmp_path: Path, capsys) -> None:
    dataset_root = synthetic_dataset(tmp_path)
    backup_root = tmp_path / "backups"

    rc = main(
        [
            "pack",
            "--workspace-root",
            str(tmp_path),
            "--source-dataset-root",
            str(dataset_root),
            "--backup-root",
            str(backup_root),
            "--backup-id",
            "backup_dry",
            "--created-at-utc",
            FIXED_CREATED_AT,
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "dry_run: True" in captured.out
    assert not (backup_root / "backup_dry").exists()


def test_backup_data_restore_command_succeeds(tmp_path: Path, capsys) -> None:
    backup_pack_dir = run_pack(tmp_path)
    restore_root = tmp_path / "restore" / "data" / "curated"

    rc = main(
        [
            "restore",
            "--backup-pack-dir",
            str(backup_pack_dir),
            "--restore-root",
            str(restore_root),
            "--overwrite-policy",
            "fail",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "restored_file_count: 2" in captured.out
    assert (
        restore_root / "bars_daily" / "symbol=AAPL" / "date=2026-05-22" / "part-000.parquet"
    ).is_file()


def test_backup_data_validate_command_succeeds_on_valid_pack(tmp_path: Path, capsys) -> None:
    backup_pack_dir = run_pack(tmp_path)

    rc = main(["validate", "--backup-pack-dir", str(backup_pack_dir)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "is_valid: True" in captured.out
    assert "checked_file_count: 2" in captured.out


def test_backup_data_validate_command_fails_on_invalid_pack(tmp_path: Path, capsys) -> None:
    backup_pack_dir = run_pack(tmp_path)
    (backup_pack_dir / "shards" / "shard-000000.zip").unlink()

    rc = main(["validate", "--backup-pack-dir", str(backup_pack_dir)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "is_valid: False" in captured.out
    assert "archive shard file is missing" in captured.out


def test_backup_data_inspect_command_succeeds(tmp_path: Path, capsys) -> None:
    backup_pack_dir = run_pack(tmp_path)

    rc = main(["inspect", "--backup-pack-dir", str(backup_pack_dir)])

    captured = capsys.readouterr()
    assert rc == 0
    assert "backup_id: backup_cli" in captured.out
    assert "included_datasets: bars_1m, bars_daily" in captured.out
    assert "file_count: 2" in captured.out
    assert "shard_count: 1" in captured.out
    assert "datasets:" in captured.out
    assert "shards:" in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["pack", "--help"],
        ["restore", "--help"],
        ["validate", "--help"],
        ["inspect", "--help"],
    ],
)
def test_backup_data_help_works(argv: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out


def test_backup_data_pack_reports_expected_errors(tmp_path: Path, capsys) -> None:
    synthetic_dataset(tmp_path)

    rc = main(
        [
            "pack",
            "--workspace-root",
            str(tmp_path),
            "--source-dataset-root",
            str(tmp_path / "data" / "curated"),
            "--backup-root",
            str(tmp_path / "backups"),
            "--backup-id",
            "../bad",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "backup_id" in captured.err
