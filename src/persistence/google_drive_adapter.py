"""Mounted-path Google Drive persistence adapter.

This adapter operates only on an already-mounted filesystem path. It does not
mount Google Drive, authenticate, import Colab helpers, or call Google APIs.
"""

from __future__ import annotations

from pathlib import Path

from src.persistence.base import PersistedFile
from src.persistence.local_adapter import LocalPersistenceAdapter

GOOGLE_DRIVE_ROOT_MISSING_MESSAGE = (
    "Google Drive root does not exist. Mount Google Drive first or pass "
    "create_root=True for a local/mounted target."
)


class GoogleDrivePersistenceAdapter:
    """Persistence adapter for an already-mounted Google Drive filesystem path."""

    def __init__(self, drive_root: Path | str, *, create_root: bool = False) -> None:
        root = Path(drive_root).expanduser().resolve(strict=False)
        if root.exists() and not root.is_dir():
            raise ValueError(f"Google Drive root must be a directory: {root}")
        if not root.exists():
            if not create_root:
                raise FileNotFoundError(GOOGLE_DRIVE_ROOT_MISSING_MESSAGE)
            root.mkdir(parents=True, exist_ok=True)

        self.drive_root = root
        self._local_adapter = LocalPersistenceAdapter(root)

    @property
    def root(self) -> Path:
        return self.drive_root

    def mkdir(self, path: str) -> Path:
        return self._local_adapter.mkdir(path)

    def exists(self, path: str) -> bool:
        return self._local_adapter.exists(path)

    def write_file(self, source_path: Path | str, destination_path: str) -> PersistedFile:
        return self._local_adapter.write_file(source_path, destination_path)

    def read_file(self, source_path: str, destination_path: Path | str) -> Path:
        return self._local_adapter.read_file(source_path, destination_path)

    def list_files(self, prefix: str = "") -> list[PersistedFile]:
        return self._local_adapter.list_files(prefix)


def google_drive_session_root(drive_root: Path | str, session_name_or_id: str) -> Path:
    """Return a deterministic path below a mounted Drive root for a session label."""

    if not session_name_or_id or not session_name_or_id.strip():
        raise ValueError("session_name_or_id must be a non-empty string")
    return Path(drive_root).expanduser() / session_name_or_id.strip()
