from __future__ import annotations

from pathlib import Path

import pytest

from src.persistence import (
    GOOGLE_DRIVE_ROOT_MISSING_MESSAGE,
    GoogleDrivePersistenceAdapter,
    PersistedFile,
    PersistenceAdapter,
    google_drive_session_root,
)


def mounted_drive_root(tmp_path: Path) -> Path:
    return tmp_path / "content" / "drive" / "MyDrive" / "fintech-market-ingestion" / "demo"


def test_existing_mounted_root_is_accepted(tmp_path: Path) -> None:
    root = mounted_drive_root(tmp_path)
    root.mkdir(parents=True)

    adapter = GoogleDrivePersistenceAdapter(root)

    assert adapter.root == root.resolve(strict=False)


def test_missing_root_without_create_root_raises_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Mount Google Drive first"):
        GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path))


def test_missing_root_with_create_root_creates_directory(tmp_path: Path) -> None:
    root = mounted_drive_root(tmp_path)

    adapter = GoogleDrivePersistenceAdapter(root, create_root=True)

    assert root.is_dir()
    assert adapter.root == root.resolve(strict=False)


def test_existing_file_root_is_rejected(tmp_path: Path) -> None:
    root = mounted_drive_root(tmp_path)
    root.parent.mkdir(parents=True)
    root.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a directory"):
        GoogleDrivePersistenceAdapter(root)


def test_mkdir_creates_adapter_relative_directory_under_drive_root(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)

    created = adapter.mkdir("sessions/demo")

    assert created == adapter.root / "sessions" / "demo"
    assert created.is_dir()


def test_write_file_copies_source_content_under_drive_root(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)
    source = _write_text(tmp_path / "workspace" / "reports" / "summary.txt", "summary")

    result = adapter.write_file(source, "exports/reports/summary.txt")

    assert result == PersistedFile(path="exports/reports/summary.txt", size_bytes=7)
    assert (adapter.root / "exports" / "reports" / "summary.txt").read_text(
        encoding="utf-8"
    ) == "summary"


def test_read_file_copies_persisted_content_to_local_destination(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)
    adapter.write_file(_write_text(tmp_path / "source.txt", "persisted"), "exports/source.txt")
    destination = tmp_path / "restored" / "source.txt"

    restored = adapter.read_file("exports/source.txt", destination)

    assert restored == destination
    assert destination.read_text(encoding="utf-8") == "persisted"


def test_list_files_returns_deterministic_persisted_file_entries(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)
    adapter.write_file(_write_text(tmp_path / "b.txt", "bb"), "exports/b.txt")
    adapter.write_file(_write_text(tmp_path / "a.txt", "a"), "exports/a.txt")
    adapter.write_file(_write_text(tmp_path / "c.txt", "ccc"), "exports/nested/c.txt")

    assert adapter.list_files("exports") == [
        PersistedFile(path="exports/a.txt", size_bytes=1),
        PersistedFile(path="exports/b.txt", size_bytes=2),
        PersistedFile(path="exports/nested/c.txt", size_bytes=3),
    ]


def test_exists_returns_expected_values(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)
    adapter.write_file(_write_text(tmp_path / "source.txt", "content"), "exports/source.txt")

    assert adapter.exists("exports/source.txt") is True
    assert adapter.exists("exports/missing.txt") is False


@pytest.mark.parametrize(
    ("unsafe_path", "message"),
    [
        ("../outside.txt", "must not escape"),
        ("/tmp/outside.txt", "absolute"),
        ("C:Temp/file.txt", "drive-qualified"),
    ],
)
def test_unsafe_adapter_relative_paths_are_rejected(
    tmp_path: Path, unsafe_path: str, message: str
) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)

    with pytest.raises(ValueError, match=message):
        adapter.exists(unsafe_path)


def test_source_file_is_not_mutated_by_write_file(tmp_path: Path) -> None:
    adapter = GoogleDrivePersistenceAdapter(mounted_drive_root(tmp_path), create_root=True)
    source = _write_text(tmp_path / "workspace" / "report.txt", "original")

    adapter.write_file(source, "exports/report.txt")

    assert source.read_text(encoding="utf-8") == "original"


def test_adapter_has_persistence_adapter_interface_methods(tmp_path: Path) -> None:
    adapter: PersistenceAdapter = GoogleDrivePersistenceAdapter(
        mounted_drive_root(tmp_path),
        create_root=True,
    )

    assert adapter.exists("") is True
    assert adapter.list_files() == []


def test_missing_root_message_does_not_claim_to_mount_drive() -> None:
    assert "Mount Google Drive first" in GOOGLE_DRIVE_ROOT_MISSING_MESSAGE
    assert "mounted Drive itself" not in GOOGLE_DRIVE_ROOT_MISSING_MESSAGE


def test_google_drive_session_root_is_path_only(tmp_path: Path) -> None:
    root = tmp_path / "content" / "drive" / "MyDrive" / "fintech-market-ingestion"

    assert google_drive_session_root(root, "demo") == root / "demo"


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
