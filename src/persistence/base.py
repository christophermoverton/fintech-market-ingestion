"""Small persistence adapter interface for explicit file transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PersistedFile:
    """Adapter-relative metadata for a persisted file."""

    path: str
    size_bytes: int
    kind: str = "file"

    def to_dict(self) -> dict[str, int | str]:
        return {
            "kind": self.kind,
            "path": self.path,
            "size_bytes": self.size_bytes,
        }


class PersistenceAdapter(Protocol):
    """Synchronous, explicit file transport operations."""

    def mkdir(self, path: str) -> Path:
        """Create an adapter-relative directory."""

    def exists(self, path: str) -> bool:
        """Return whether an adapter-relative path exists."""

    def write_file(self, source_path: Path | str, destination_path: str) -> PersistedFile:
        """Copy a local source file to an adapter-relative destination."""

    def read_file(self, source_path: str, destination_path: Path | str) -> Path:
        """Copy an adapter-relative source file to a local destination."""

    def list_files(self, prefix: str = "") -> list[PersistedFile]:
        """Return deterministic metadata for files under an adapter-relative prefix."""
