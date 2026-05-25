"""CI-safe local filesystem persistence adapter."""

from __future__ import annotations

import shutil
from pathlib import Path

from src.persistence.base import PersistedFile
from src.sessions.session_paths import normalize_workspace_relative_path


class LocalPersistenceAdapter:
    """Adapter that copies files under a local root using explicit paths only."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        if self.root.exists() and not self.root.is_dir():
            raise ValueError(f"Local persistence root must be a directory: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)

    def mkdir(self, path: str) -> Path:
        target = self._resolve_adapter_path(path)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def exists(self, path: str) -> bool:
        return self._resolve_adapter_path(path, allow_root=True).exists()

    def write_file(self, source_path: Path | str, destination_path: str) -> PersistedFile:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file does not exist: {source}")
        if source.is_dir():
            raise ValueError(f"Source path must be a file, not a directory: {source}")

        destination = self._resolve_adapter_path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return self._file_metadata(destination)

    def read_file(self, source_path: str, destination_path: Path | str) -> Path:
        source = self._resolve_adapter_path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Persisted source file does not exist: {source_path}")
        if source.is_dir():
            raise ValueError(
                f"Persisted source path must be a file, not a directory: {source_path}"
            )

        destination = Path(destination_path)
        if destination.exists() and destination.is_dir():
            raise ValueError(f"Destination path must be a file, not a directory: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    def list_files(self, prefix: str = "") -> list[PersistedFile]:
        base = self._resolve_adapter_path(prefix, allow_root=True)
        if not base.exists():
            return []
        if base.is_file():
            return [self._file_metadata(base)]
        files = [path for path in base.rglob("*") if path.is_file()]
        return [self._file_metadata(path) for path in sorted(files, key=self._relative_posix_path)]

    def _resolve_adapter_path(self, path: str, *, allow_root: bool = False) -> Path:
        relative = _normalize_adapter_relative_path(path, allow_root=allow_root)
        resolved = self.root if relative == "" else (self.root / relative).resolve(strict=False)
        if resolved != self.root and not _is_relative_to(resolved, self.root):
            raise ValueError(f"Adapter-relative path escapes the persistence root: {path}")
        return resolved

    def _file_metadata(self, path: Path) -> PersistedFile:
        return PersistedFile(
            path=self._relative_posix_path(path),
            size_bytes=path.stat().st_size,
        )

    def _relative_posix_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def _normalize_adapter_relative_path(path: str, *, allow_root: bool) -> str:
    raw = str(path).strip()
    if allow_root and raw in {"", ".", "./"}:
        return ""
    return normalize_workspace_relative_path(raw, field_name="adapter path")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
