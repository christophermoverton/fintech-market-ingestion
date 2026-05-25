from __future__ import annotations

from pathlib import Path

import pytest

from src.persistence import LocalPersistenceAdapter, PersistedFile


def test_adapter_creates_root(tmp_path: Path) -> None:
    root = tmp_path / "persisted"

    adapter = LocalPersistenceAdapter(root)

    assert adapter.root == root.resolve(strict=False)
    assert root.is_dir()


def test_adapter_rejects_file_root(tmp_path: Path) -> None:
    root = tmp_path / "not-a-dir.txt"
    root.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="root must be a directory"):
        LocalPersistenceAdapter(root)


def test_mkdir_creates_adapter_relative_directory(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")

    created = adapter.mkdir("sessions/demo")

    assert created.is_dir()
    assert created == adapter.root / "sessions" / "demo"


def test_write_file_copies_content_and_preserves_source(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    source = tmp_path / "workspace" / "reports" / "summary.txt"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")

    result = adapter.write_file(source, "reports/summary.txt")

    assert result == PersistedFile(path="reports/summary.txt", size_bytes=len("original"))
    assert (adapter.root / "reports" / "summary.txt").read_text(encoding="utf-8") == "original"
    assert source.read_text(encoding="utf-8") == "original"


def test_read_file_copies_persisted_content_to_local_destination(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    adapter.write_file(_write_text(tmp_path / "source.txt", "persisted"), "snapshots/source.txt")
    destination = tmp_path / "restored" / "source.txt"

    restored = adapter.read_file("snapshots/source.txt", destination)

    assert restored == destination
    assert destination.read_text(encoding="utf-8") == "persisted"


def test_exists_returns_expected_values(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    adapter.write_file(_write_text(tmp_path / "source.txt", "content"), "snapshots/source.txt")

    assert adapter.exists("snapshots/source.txt") is True
    assert adapter.exists("snapshots/missing.txt") is False


def test_list_files_returns_sorted_deterministic_results(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    adapter.write_file(_write_text(tmp_path / "b.txt", "bb"), "snapshots/b.txt")
    adapter.write_file(_write_text(tmp_path / "a.txt", "a"), "snapshots/a.txt")
    adapter.write_file(_write_text(tmp_path / "nested.txt", "ccc"), "snapshots/nested/c.txt")

    files = adapter.list_files("snapshots")

    assert files == [
        PersistedFile(path="snapshots/a.txt", size_bytes=1),
        PersistedFile(path="snapshots/b.txt", size_bytes=2),
        PersistedFile(path="snapshots/nested/c.txt", size_bytes=3),
    ]
    assert [file.to_dict() for file in files] == [
        {"kind": "file", "path": "snapshots/a.txt", "size_bytes": 1},
        {"kind": "file", "path": "snapshots/b.txt", "size_bytes": 2},
        {"kind": "file", "path": "snapshots/nested/c.txt", "size_bytes": 3},
    ]


def test_list_files_for_missing_prefix_returns_empty_list(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")

    assert adapter.list_files("missing") == []


def test_missing_source_file_raises_clear_error(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")

    with pytest.raises(FileNotFoundError, match="Source file does not exist"):
        adapter.write_file(tmp_path / "missing.txt", "missing.txt")


def test_directory_source_to_write_file_raises_clear_error(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    source_dir = tmp_path / "workspace"
    source_dir.mkdir()

    with pytest.raises(ValueError, match="must be a file"):
        adapter.write_file(source_dir, "workspace")


def test_directory_source_to_read_file_raises_clear_error(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")
    adapter.mkdir("snapshots")

    with pytest.raises(ValueError, match="must be a file"):
        adapter.read_file("snapshots", tmp_path / "restored.txt")


def test_adapter_relative_path_traversal_is_rejected(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")

    with pytest.raises(ValueError, match="must not escape"):
        adapter.write_file(_write_text(tmp_path / "source.txt", "content"), "../outside.txt")


def test_adapter_rejects_drive_qualified_relative_paths(tmp_path: Path) -> None:
    adapter = LocalPersistenceAdapter(tmp_path / "persisted")

    with pytest.raises(ValueError, match="drive-qualified"):
        adapter.exists("C:Temp/file.txt")


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
