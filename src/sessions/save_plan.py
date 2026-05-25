"""Deterministic save-plan model for explicit project-session persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.sessions.session_paths import (
    ROOT_SEMANTICS_WORKSPACE_RELATIVE,
    normalize_workspace_relative_path,
)


@dataclass(frozen=True)
class SavePlanEntry:
    source_path: str
    destination_path: str
    size_bytes: int
    kind: str = "file"

    def to_dict(self) -> dict[str, int | str]:
        return {
            "destination_path": self.destination_path,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class SavePlanSummary:
    file_count: int
    total_size_bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "file_count": self.file_count,
            "total_size_bytes": self.total_size_bytes,
        }


@dataclass(frozen=True)
class SavePlan:
    entries: tuple[SavePlanEntry, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    root_semantics: str = ROOT_SEMANTICS_WORKSPACE_RELATIVE

    @property
    def summary(self) -> SavePlanSummary:
        return SavePlanSummary(
            file_count=len(self.entries),
            total_size_bytes=sum(entry.size_bytes for entry in self.entries),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "exclude": list(self.exclude),
            "include": list(self.include),
            "root_semantics": self.root_semantics,
            "summary": self.summary.to_dict(),
        }

    def to_json(self) -> str:
        return dumps_save_plan_json(self)


def build_save_plan(
    workspace_root: Path | str,
    include: Sequence[str],
    exclude: Sequence[str] = ("data/curated",),
) -> SavePlan:
    """Build a deterministic explicit file-selection plan without copying files."""

    root = Path(workspace_root).expanduser().resolve(strict=False)
    include_paths = _normalize_paths(include, "include")
    exclude_paths = _normalize_paths(exclude, "exclude")
    if not include_paths:
        return SavePlan(entries=(), include=(), exclude=exclude_paths)

    entries_by_source: dict[str, SavePlanEntry] = {}
    for include_path in include_paths:
        selected_root = root / include_path
        if not selected_root.exists():
            raise FileNotFoundError(f"Included path does not exist: {include_path}")
        if selected_root.is_file():
            candidates = [selected_root]
        else:
            candidates = [path for path in selected_root.rglob("*") if path.is_file()]

        for candidate in candidates:
            relative_path = candidate.relative_to(root).as_posix()
            normalized_relative = normalize_workspace_relative_path(
                relative_path,
                field_name="save plan source path",
            )
            if _is_excluded(normalized_relative, exclude_paths):
                continue
            entries_by_source[normalized_relative] = SavePlanEntry(
                source_path=normalized_relative,
                destination_path=normalized_relative,
                size_bytes=candidate.stat().st_size,
            )

    entries = tuple(entries_by_source[path] for path in sorted(entries_by_source))
    return SavePlan(entries=entries, include=include_paths, exclude=exclude_paths)


def dumps_save_plan_json(plan: SavePlan) -> str:
    return json.dumps(plan.to_dict(), sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _normalize_paths(paths: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(paths, str):
        raise ValueError(f"{field_name} must be a sequence of workspace-relative paths")
    normalized = [
        normalize_workspace_relative_path(path, field_name=f"{field_name}[]") for path in paths
    ]
    return tuple(sorted(dict.fromkeys(normalized)))


def _is_excluded(path: str, exclude_paths: Sequence[str]) -> bool:
    return any(path == excluded or path.startswith(f"{excluded}/") for excluded in exclude_paths)
