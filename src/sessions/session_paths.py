"""Workspace-relative path helpers for portable project sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping

ROOT_SEMANTICS_WORKSPACE_RELATIVE = "workspace_relative"


@dataclass(frozen=True)
class WorkspacePaths:
    """Standard fintech-market-ingestion workspace layout.

    Durable manifest paths are stored relative to the workspace root so a
    session can move between local folders, notebooks, and mounted runtimes.
    """

    configs: str = "configs"
    curated_data: str = "data/curated"
    research_data: str = "data/research"
    artifacts: str = "artifacts"
    reports: str = "reports"
    notebooks: str = "notebooks"

    def __post_init__(self) -> None:
        for field_name, value in self.to_dict().items():
            normalized = normalize_workspace_relative_path(value, field_name=field_name)
            object.__setattr__(self, field_name, normalized)

    def to_dict(self) -> dict[str, str]:
        return {
            "configs": self.configs,
            "curated_data": self.curated_data,
            "research_data": self.research_data,
            "artifacts": self.artifacts,
            "reports": self.reports,
            "notebooks": self.notebooks,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "WorkspacePaths":
        if not isinstance(data, Mapping):
            raise ValueError("workspace.paths must be an object")
        required = [
            "configs",
            "curated_data",
            "research_data",
            "artifacts",
            "reports",
            "notebooks",
        ]
        missing = [field for field in required if field not in data]
        if missing:
            raise ValueError(f"workspace.paths is missing required field(s): {', '.join(missing)}")
        return cls(
            configs=_coerce_path(data["configs"], "configs"),
            curated_data=_coerce_path(data["curated_data"], "curated_data"),
            research_data=_coerce_path(data["research_data"], "research_data"),
            artifacts=_coerce_path(data["artifacts"], "artifacts"),
            reports=_coerce_path(data["reports"], "reports"),
            notebooks=_coerce_path(data["notebooks"], "notebooks"),
        )


def normalize_workspace_relative_path(path: Path | str, *, field_name: str = "path") -> str:
    """Return a portable POSIX-style workspace-relative path.

    Absolute local paths, drive-qualified Windows paths, home-relative paths,
    and parent-directory traversal are rejected because durable manifests should
    not leak machine-local filesystem details.
    """

    raw = str(path).strip()
    if not raw:
        raise ValueError(f"{field_name} must be a non-empty relative path")
    if raw.startswith("~"):
        raise ValueError(f"{field_name} must be workspace-relative, not home-relative: {raw}")
    if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
        raise ValueError(f"{field_name} must be workspace-relative, not absolute: {raw}")

    normalized = raw.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if any(part == ".." for part in parts):
        raise ValueError(f"{field_name} must not escape the workspace root: {raw}")
    if normalized in {".", "./"}:
        raise ValueError(f"{field_name} must identify a path below the workspace root")
    return str(PurePosixPath(normalized))


def workspace_relative_path(workspace_root: Path | str, path: Path | str) -> str:
    """Convert a path to a workspace-relative manifest path when possible."""

    candidate = Path(path)
    if not candidate.is_absolute():
        return normalize_workspace_relative_path(candidate)

    root = Path(workspace_root).expanduser().resolve(strict=False)
    resolved = candidate.expanduser().resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside the workspace root: {candidate}") from exc
    return normalize_workspace_relative_path(relative)


def _coerce_path(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"workspace.paths.{field_name} must be a string")
    return normalize_workspace_relative_path(value, field_name=f"workspace.paths.{field_name}")
