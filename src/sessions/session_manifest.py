"""Deterministic portable project-session manifest model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.sessions.session_paths import (
    ROOT_SEMANTICS_WORKSPACE_RELATIVE,
    WorkspacePaths,
    normalize_workspace_relative_path,
)

SCHEMA_VERSION = 1
PACKAGE_NAME = "fintech-market-ingestion"
DEFAULT_SAVE_POLICY_MODE = "metadata_only"
DEFAULT_PERSISTENCE_ADAPTER = "none"
DEFAULT_CREATED_BY = "src.sessions"
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ManifestValidationError(ValueError):
    """Raised when a project-session manifest is missing or malformed."""


@dataclass(frozen=True)
class PackageMetadata:
    name: str = PACKAGE_NAME
    version: str = field(default_factory=lambda: package_version())

    def __post_init__(self) -> None:
        if not self.name:
            raise ManifestValidationError("package.name must be a non-empty string")
        if not self.version:
            raise ManifestValidationError("package.version must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PackageMetadata":
        if not isinstance(data, Mapping):
            raise ManifestValidationError("package must be an object")
        return cls(
            name=_required_str(data, "package", "name"),
            version=_required_str(data, "package", "version"),
        )


@dataclass(frozen=True)
class WorkspaceMetadata:
    root_semantics: str = ROOT_SEMANTICS_WORKSPACE_RELATIVE
    paths: WorkspacePaths = field(default_factory=WorkspacePaths)

    def __post_init__(self) -> None:
        if self.root_semantics != ROOT_SEMANTICS_WORKSPACE_RELATIVE:
            raise ManifestValidationError("workspace.root_semantics must be 'workspace_relative'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_semantics": self.root_semantics,
            "paths": self.paths.to_dict(),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "WorkspaceMetadata":
        if not isinstance(data, Mapping):
            raise ManifestValidationError("workspace must be an object")
        if "paths" not in data:
            raise ManifestValidationError("workspace is missing required field: paths")
        return cls(
            root_semantics=_required_str(data, "workspace", "root_semantics"),
            paths=_coerce_workspace_paths(data["paths"]),
        )


@dataclass(frozen=True)
class PersistenceSettings:
    adapter: str = DEFAULT_PERSISTENCE_ADAPTER
    destination: str | None = None
    runtime_only: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.adapter, str) or not self.adapter:
            raise ManifestValidationError("persistence.adapter must be a non-empty string")
        if self.destination is not None:
            if not isinstance(self.destination, str):
                raise ManifestValidationError("persistence.destination must be a string or null")
            try:
                destination = normalize_workspace_relative_path(
                    self.destination, field_name="persistence.destination"
                )
            except ValueError as exc:
                raise ManifestValidationError(str(exc)) from exc
            object.__setattr__(self, "destination", destination)
        if not isinstance(self.runtime_only, dict):
            raise ManifestValidationError("persistence.runtime_only must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "destination": self.destination,
            "runtime_only": _sorted_jsonable(self.runtime_only),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PersistenceSettings":
        if not isinstance(data, Mapping):
            raise ManifestValidationError("persistence must be an object")
        runtime_only = data.get("runtime_only", {})
        if not isinstance(runtime_only, dict):
            raise ManifestValidationError("persistence.runtime_only must be an object")
        return cls(
            adapter=_required_str(data, "persistence", "adapter"),
            destination=_optional_str(data, "persistence", "destination"),
            runtime_only=dict(runtime_only),
        )


@dataclass(frozen=True)
class SavePolicy:
    mode: str = DEFAULT_SAVE_POLICY_MODE
    include: tuple[str, ...] = field(default_factory=tuple)
    exclude: tuple[str, ...] = ("data/curated",)
    include_curated_data: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or not self.mode:
            raise ManifestValidationError("save_policy.mode must be a non-empty string")
        include = _normalize_path_sequence(self.include, "save_policy.include")
        exclude = _normalize_path_sequence(self.exclude, "save_policy.exclude")
        if not isinstance(self.include_curated_data, bool):
            raise ManifestValidationError("save_policy.include_curated_data must be a boolean")
        if not self.include_curated_data and "data/curated" not in exclude:
            exclude = tuple(sorted((*exclude, "data/curated")))
        object.__setattr__(self, "include", tuple(sorted(include)))
        object.__setattr__(self, "exclude", tuple(sorted(exclude)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "include_curated_data": self.include_curated_data,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SavePolicy":
        if not isinstance(data, Mapping):
            raise ManifestValidationError("save_policy must be an object")
        return cls(
            mode=_required_str(data, "save_policy", "mode"),
            include=_required_str_sequence(data, "save_policy", "include"),
            exclude=_required_str_sequence(data, "save_policy", "exclude"),
            include_curated_data=_required_bool(data, "save_policy", "include_curated_data"),
        )


@dataclass(frozen=True)
class SessionManifest:
    schema_version: int = SCHEMA_VERSION
    session_id: str = ""
    session_name: str = ""
    created_at_utc: str = ""
    package: PackageMetadata = field(default_factory=PackageMetadata)
    workspace: WorkspaceMetadata = field(default_factory=WorkspaceMetadata)
    persistence: PersistenceSettings = field(default_factory=PersistenceSettings)
    save_policy: SavePolicy = field(default_factory=SavePolicy)
    created_by: str = DEFAULT_CREATED_BY

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ManifestValidationError(f"schema_version must be {SCHEMA_VERSION}")
        if not self.session_id:
            raise ManifestValidationError("session_id must be a non-empty string")
        if not self.session_name:
            raise ManifestValidationError("session_name must be a non-empty string")
        _validate_utc_timestamp(self.created_at_utc, "created_at_utc")
        if not isinstance(self.created_by, str) or not self.created_by:
            raise ManifestValidationError("created_by must be a non-empty string")

    @classmethod
    def create(
        cls,
        *,
        session_name: str,
        session_id: str | None = None,
        created_at_utc: datetime | str | None = None,
        package: PackageMetadata | None = None,
        workspace: WorkspaceMetadata | None = None,
        persistence: PersistenceSettings | None = None,
        save_policy: SavePolicy | None = None,
    ) -> "SessionManifest":
        created_at = normalize_created_at_utc(created_at_utc)
        resolved_name = _validate_session_name(session_name)
        return cls(
            session_id=session_id or deterministic_session_id(resolved_name, created_at),
            session_name=resolved_name,
            created_at_utc=created_at,
            package=package or PackageMetadata(),
            workspace=workspace or WorkspaceMetadata(),
            persistence=persistence or PersistenceSettings(),
            save_policy=save_policy or SavePolicy(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "created_at_utc": self.created_at_utc,
            "package": self.package.to_dict(),
            "workspace": self.workspace.to_dict(),
            "persistence": self.persistence.to_dict(),
            "save_policy": self.save_policy.to_dict(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SessionManifest":
        if not isinstance(data, Mapping):
            raise ManifestValidationError("manifest must be a JSON object")
        required = [
            "schema_version",
            "session_id",
            "session_name",
            "created_at_utc",
            "package",
            "workspace",
            "persistence",
            "save_policy",
        ]
        missing = [field for field in required if field not in data]
        if missing:
            raise ManifestValidationError(
                f"manifest is missing required field(s): {', '.join(missing)}"
            )
        schema_version = data["schema_version"]
        if not isinstance(schema_version, int):
            raise ManifestValidationError("schema_version must be an integer")
        return cls(
            schema_version=schema_version,
            session_id=_required_str(data, "manifest", "session_id"),
            session_name=_required_str(data, "manifest", "session_name"),
            created_at_utc=_required_str(data, "manifest", "created_at_utc"),
            package=PackageMetadata.from_mapping(data["package"]),
            workspace=WorkspaceMetadata.from_mapping(data["workspace"]),
            persistence=PersistenceSettings.from_mapping(data["persistence"]),
            save_policy=SavePolicy.from_mapping(data["save_policy"]),
            created_by=_optional_str(data, "manifest", "created_by") or DEFAULT_CREATED_BY,
        )


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "0+unknown"


def deterministic_session_id(session_name: str, created_at_utc: str) -> str:
    _validate_utc_timestamp(created_at_utc, "created_at_utc")
    slug = re.sub(r"[^a-z0-9]+", "_", session_name.lower()).strip("_") or "session"
    timestamp = created_at_utc.replace("-", "").replace(":", "").replace("T", "_").removesuffix("Z")
    return f"session_{timestamp}_{slug}"


def normalize_created_at_utc(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        _validate_utc_timestamp(value, "created_at_utc")
        return value
    raise ManifestValidationError("created_at_utc must be a datetime, UTC string, or null")


def dumps_manifest_json(manifest: SessionManifest | Mapping[str, Any]) -> str:
    data = manifest.to_dict() if isinstance(manifest, SessionManifest) else dict(manifest)
    return json.dumps(data, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def loads_manifest(text: str) -> SessionManifest:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(f"manifest is not valid JSON: {exc.msg}") from exc
    return SessionManifest.from_mapping(data)


def load_manifest(path: Path | str) -> SessionManifest:
    return loads_manifest(Path(path).read_text(encoding="utf-8"))


def write_manifest(manifest: SessionManifest, path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dumps_manifest_json(manifest), encoding="utf-8")
    return output_path


def _validate_utc_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.match(value):
        raise ManifestValidationError(
            f"{field_name} must be a UTC timestamp like YYYY-MM-DDTHH:MM:SSZ"
        )


def _validate_session_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError("session_name must be a non-empty string")
    return value.strip()


def _required_str(data: Mapping[str, Any], section: str, field_name: str) -> str:
    if field_name not in data:
        raise ManifestValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, str) or not value:
        raise ManifestValidationError(f"{section}.{field_name} must be a non-empty string")
    return value


def _optional_str(data: Mapping[str, Any], section: str, field_name: str) -> str | None:
    if field_name not in data or data[field_name] is None:
        return None
    value = data[field_name]
    if not isinstance(value, str) or not value:
        raise ManifestValidationError(f"{section}.{field_name} must be a non-empty string or null")
    return value


def _required_bool(data: Mapping[str, Any], section: str, field_name: str) -> bool:
    if field_name not in data:
        raise ManifestValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, bool):
        raise ManifestValidationError(f"{section}.{field_name} must be a boolean")
    return value


def _required_str_sequence(
    data: Mapping[str, Any], section: str, field_name: str
) -> tuple[str, ...]:
    if field_name not in data:
        raise ManifestValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, list):
        raise ManifestValidationError(f"{section}.{field_name} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise ManifestValidationError(f"{section}.{field_name} must contain only strings")
    return tuple(value)


def _normalize_path_sequence(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ManifestValidationError(f"{field_name} must be a sequence of strings")
    return tuple(
        normalize_workspace_relative_path(value, field_name=f"{field_name}[]") for value in values
    )


def _coerce_workspace_paths(value: Any) -> WorkspacePaths:
    try:
        return WorkspacePaths.from_mapping(value)
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc


def _sorted_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_jsonable(item) for item in value]
    return value
