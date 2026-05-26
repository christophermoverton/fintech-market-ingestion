"""Deterministic manifest contract for archive backup packs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from src.sessions.session_paths import normalize_workspace_relative_path, workspace_relative_path

BACKUP_PACK_SCHEMA_VERSION = 1
ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE = "archive_backup_pack"
DERIVED_NON_CANONICAL_STATUS = "derived_non_canonical"
CHECKSUM_SHA256 = "sha256"
DEFAULT_SHARD_STRATEGY = "reserved_for_m10_archive_writer"
DEFAULT_RESTORE_LAYOUT = "restore files under the recorded source_dataset_root"
DEFAULT_RESTORE_OVERWRITE_POLICIES = ("fail_if_exists", "overwrite")
DEFAULT_MANIFEST_NOTES = (
    "Archive backup packs are derived transfer artifacts, not canonical datasets.",
)
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class BackupPackValidationError(ValueError):
    """Raised when an archive backup pack manifest is missing or malformed."""


@dataclass(frozen=True)
class BackupPackFileEntry:
    relative_path: str
    size_bytes: int
    dataset_name: str | None = None
    checksum: str | None = None
    checksum_algorithm: str | None = CHECKSUM_SHA256
    partitions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            _normalize_relative_manifest_path(self.relative_path, "files[].relative_path"),
        )
        _validate_non_negative_int(self.size_bytes, "files[].size_bytes")
        if self.dataset_name is not None and (
            not isinstance(self.dataset_name, str) or not self.dataset_name
        ):
            raise BackupPackValidationError("files[].dataset_name must be a non-empty string or null")
        if self.checksum is not None and (not isinstance(self.checksum, str) or not self.checksum):
            raise BackupPackValidationError("files[].checksum must be a non-empty string or null")
        if self.checksum_algorithm is not None and (
            not isinstance(self.checksum_algorithm, str) or not self.checksum_algorithm
        ):
            raise BackupPackValidationError(
                "files[].checksum_algorithm must be a non-empty string or null"
            )
        object.__setattr__(self, "partitions", _normalize_partition_mapping(self.partitions))

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "dataset_name": self.dataset_name,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "checksum_algorithm": self.checksum_algorithm,
            "partitions": dict(self.partitions),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BackupPackFileEntry":
        if not isinstance(data, Mapping):
            raise BackupPackValidationError("files[] must be an object")
        required = ["relative_path", "size_bytes"]
        _require_fields(data, "files[]", required)
        return cls(
            relative_path=_required_str(data, "files[]", "relative_path"),
            dataset_name=_optional_str(data, "files[]", "dataset_name"),
            size_bytes=_required_int(data, "files[]", "size_bytes"),
            checksum=_optional_str(data, "files[]", "checksum"),
            checksum_algorithm=_optional_str(data, "files[]", "checksum_algorithm"),
            partitions=_optional_mapping(data, "files[]", "partitions"),
        )


@dataclass(frozen=True)
class BackupPackShardEntry:
    shard_name: str
    relative_path: str
    shard_index: int
    file_count: int
    uncompressed_bytes: int
    archive_bytes: int | None = None
    checksum: str | None = None
    checksum_algorithm: str | None = CHECKSUM_SHA256

    def __post_init__(self) -> None:
        if not isinstance(self.shard_name, str) or not self.shard_name:
            raise BackupPackValidationError("shards[].shard_name must be a non-empty string")
        object.__setattr__(
            self,
            "relative_path",
            _normalize_relative_manifest_path(self.relative_path, "shards[].relative_path"),
        )
        _validate_non_negative_int(self.shard_index, "shards[].shard_index")
        _validate_non_negative_int(self.file_count, "shards[].file_count")
        _validate_non_negative_int(self.uncompressed_bytes, "shards[].uncompressed_bytes")
        if self.archive_bytes is not None:
            _validate_non_negative_int(self.archive_bytes, "shards[].archive_bytes")
        if self.checksum is not None and (not isinstance(self.checksum, str) or not self.checksum):
            raise BackupPackValidationError("shards[].checksum must be a non-empty string or null")
        if self.checksum_algorithm is not None and (
            not isinstance(self.checksum_algorithm, str) or not self.checksum_algorithm
        ):
            raise BackupPackValidationError(
                "shards[].checksum_algorithm must be a non-empty string or null"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "shard_name": self.shard_name,
            "relative_path": self.relative_path,
            "shard_index": self.shard_index,
            "file_count": self.file_count,
            "uncompressed_bytes": self.uncompressed_bytes,
            "archive_bytes": self.archive_bytes,
            "checksum": self.checksum,
            "checksum_algorithm": self.checksum_algorithm,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BackupPackShardEntry":
        if not isinstance(data, Mapping):
            raise BackupPackValidationError("shards[] must be an object")
        required = ["shard_name", "relative_path", "shard_index", "file_count", "uncompressed_bytes"]
        _require_fields(data, "shards[]", required)
        return cls(
            shard_name=_required_str(data, "shards[]", "shard_name"),
            relative_path=_required_str(data, "shards[]", "relative_path"),
            shard_index=_required_int(data, "shards[]", "shard_index"),
            file_count=_required_int(data, "shards[]", "file_count"),
            uncompressed_bytes=_required_int(data, "shards[]", "uncompressed_bytes"),
            archive_bytes=_optional_int(data, "shards[]", "archive_bytes"),
            checksum=_optional_str(data, "shards[]", "checksum"),
            checksum_algorithm=_optional_str(data, "shards[]", "checksum_algorithm"),
        )


@dataclass(frozen=True)
class BackupPackRestoreMetadata:
    expected_layout: str = DEFAULT_RESTORE_LAYOUT
    paths_are_relative: bool = True
    overwrite_policy_options: tuple[str, ...] = DEFAULT_RESTORE_OVERWRITE_POLICIES
    compatibility_schema_version: int = BACKUP_PACK_SCHEMA_VERSION
    source_root_semantics: str = "workspace_relative"

    def __post_init__(self) -> None:
        if not isinstance(self.expected_layout, str) or not self.expected_layout:
            raise BackupPackValidationError("restore.expected_layout must be a non-empty string")
        if self.paths_are_relative is not True:
            raise BackupPackValidationError("restore.paths_are_relative must be true")
        if not isinstance(self.compatibility_schema_version, int):
            raise BackupPackValidationError(
                "restore.compatibility_schema_version must be an integer"
            )
        if self.compatibility_schema_version != BACKUP_PACK_SCHEMA_VERSION:
            raise BackupPackValidationError(
                f"restore.compatibility_schema_version must be {BACKUP_PACK_SCHEMA_VERSION}"
            )
        if self.source_root_semantics != "workspace_relative":
            raise BackupPackValidationError(
                "restore.source_root_semantics must be 'workspace_relative'"
            )
        policies = _normalize_string_tuple(
            self.overwrite_policy_options,
            "restore.overwrite_policy_options",
        )
        object.__setattr__(self, "overwrite_policy_options", policies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_layout": self.expected_layout,
            "paths_are_relative": self.paths_are_relative,
            "overwrite_policy_options": list(self.overwrite_policy_options),
            "compatibility_schema_version": self.compatibility_schema_version,
            "source_root_semantics": self.source_root_semantics,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BackupPackRestoreMetadata":
        if not isinstance(data, Mapping):
            raise BackupPackValidationError("restore must be an object")
        required = [
            "expected_layout",
            "paths_are_relative",
            "overwrite_policy_options",
            "compatibility_schema_version",
            "source_root_semantics",
        ]
        _require_fields(data, "restore", required)
        return cls(
            expected_layout=_required_str(data, "restore", "expected_layout"),
            paths_are_relative=_required_bool(data, "restore", "paths_are_relative"),
            overwrite_policy_options=_required_str_sequence(
                data, "restore", "overwrite_policy_options"
            ),
            compatibility_schema_version=_required_int(
                data, "restore", "compatibility_schema_version"
            ),
            source_root_semantics=_required_str(data, "restore", "source_root_semantics"),
        )


@dataclass(frozen=True)
class BackupPackManifest:
    backup_id: str
    created_at_utc: str
    source_dataset_root: str
    files: tuple[BackupPackFileEntry, ...] = field(default_factory=tuple)
    shards: tuple[BackupPackShardEntry, ...] = field(default_factory=tuple)
    included_datasets: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = BACKUP_PACK_SCHEMA_VERSION
    artifact_type: str = ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE
    canonical_status: str = DERIVED_NON_CANONICAL_STATUS
    checksum_algorithm: str = CHECKSUM_SHA256
    shard_strategy: str = DEFAULT_SHARD_STRATEGY
    shard_size_mb: int | None = None
    total_archive_bytes: int | None = None
    restore: BackupPackRestoreMetadata = field(default_factory=BackupPackRestoreMetadata)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = DEFAULT_MANIFEST_NOTES

    def __post_init__(self) -> None:
        if self.schema_version != BACKUP_PACK_SCHEMA_VERSION:
            raise BackupPackValidationError(f"schema_version must be {BACKUP_PACK_SCHEMA_VERSION}")
        if not isinstance(self.backup_id, str) or not self.backup_id:
            raise BackupPackValidationError("backup_id must be a non-empty string")
        _validate_utc_timestamp(self.created_at_utc, "created_at_utc")
        if self.artifact_type != ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE:
            raise BackupPackValidationError(
                f"artifact_type must be '{ARCHIVE_BACKUP_PACK_ARTIFACT_TYPE}'"
            )
        if self.canonical_status != DERIVED_NON_CANONICAL_STATUS:
            raise BackupPackValidationError(
                f"canonical_status must be '{DERIVED_NON_CANONICAL_STATUS}'"
            )
        try:
            source_dataset_root = normalize_workspace_relative_path(
                self.source_dataset_root, field_name="source_dataset_root"
            )
        except ValueError as exc:
            raise BackupPackValidationError(str(exc)) from exc
        object.__setattr__(self, "source_dataset_root", source_dataset_root)
        if not isinstance(self.checksum_algorithm, str) or not self.checksum_algorithm:
            raise BackupPackValidationError("checksum_algorithm must be a non-empty string")
        if not isinstance(self.shard_strategy, str) or not self.shard_strategy:
            raise BackupPackValidationError("shard_strategy must be a non-empty string")
        if self.shard_size_mb is not None:
            _validate_positive_int(self.shard_size_mb, "shard_size_mb")
        if self.total_archive_bytes is not None:
            _validate_non_negative_int(self.total_archive_bytes, "total_archive_bytes")

        files = tuple(
            item if isinstance(item, BackupPackFileEntry) else BackupPackFileEntry.from_mapping(item)
            for item in self.files
        )
        shards = tuple(
            item if isinstance(item, BackupPackShardEntry) else BackupPackShardEntry.from_mapping(item)
            for item in self.shards
        )
        restore = (
            self.restore
            if isinstance(self.restore, BackupPackRestoreMetadata)
            else BackupPackRestoreMetadata.from_mapping(self.restore)
        )
        object.__setattr__(self, "files", tuple(sorted(files, key=lambda item: item.relative_path)))
        object.__setattr__(self, "shards", tuple(sorted(shards, key=lambda item: item.shard_index)))
        object.__setattr__(self, "restore", restore)
        object.__setattr__(
            self,
            "included_datasets",
            _normalize_included_datasets(self.included_datasets, self.files),
        )
        object.__setattr__(self, "metadata", _sorted_jsonable(dict(self.metadata)))
        object.__setattr__(self, "notes", _normalize_string_tuple(self.notes, "notes"))

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_uncompressed_bytes(self) -> int:
        return sum(file_entry.size_bytes for file_entry in self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backup_id": self.backup_id,
            "created_at_utc": self.created_at_utc,
            "artifact_type": self.artifact_type,
            "canonical_status": self.canonical_status,
            "source_dataset_root": self.source_dataset_root,
            "included_datasets": list(self.included_datasets),
            "file_count": self.file_count,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "total_archive_bytes": self.total_archive_bytes,
            "checksum_algorithm": self.checksum_algorithm,
            "shard_strategy": self.shard_strategy,
            "shard_size_mb": self.shard_size_mb,
            "files": [file_entry.to_dict() for file_entry in self.files],
            "shards": [shard.to_dict() for shard in self.shards],
            "restore": self.restore.to_dict(),
            "metadata": _sorted_jsonable(dict(self.metadata)),
            "notes": list(self.notes),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BackupPackManifest":
        if not isinstance(data, Mapping):
            raise BackupPackValidationError("manifest must be a JSON object")
        required = [
            "schema_version",
            "backup_id",
            "created_at_utc",
            "artifact_type",
            "canonical_status",
            "source_dataset_root",
            "included_datasets",
            "file_count",
            "total_uncompressed_bytes",
            "checksum_algorithm",
            "shard_strategy",
            "files",
            "shards",
            "restore",
        ]
        _require_fields(data, "manifest", required)
        manifest = cls(
            schema_version=_required_int(data, "manifest", "schema_version"),
            backup_id=_required_str(data, "manifest", "backup_id"),
            created_at_utc=_required_str(data, "manifest", "created_at_utc"),
            artifact_type=_required_str(data, "manifest", "artifact_type"),
            canonical_status=_required_str(data, "manifest", "canonical_status"),
            source_dataset_root=_required_str(data, "manifest", "source_dataset_root"),
            included_datasets=_required_str_sequence(data, "manifest", "included_datasets"),
            total_archive_bytes=_optional_int(data, "manifest", "total_archive_bytes"),
            checksum_algorithm=_required_str(data, "manifest", "checksum_algorithm"),
            shard_strategy=_required_str(data, "manifest", "shard_strategy"),
            shard_size_mb=_optional_int(data, "manifest", "shard_size_mb"),
            files=_required_file_entries(data),
            shards=_required_shard_entries(data),
            restore=BackupPackRestoreMetadata.from_mapping(data["restore"]),
            metadata=_optional_mapping(data, "manifest", "metadata"),
            notes=_optional_str_sequence(data, "manifest", "notes"),
        )
        _validate_reported_count(data, "file_count", manifest.file_count)
        _validate_reported_count(
            data, "total_uncompressed_bytes", manifest.total_uncompressed_bytes
        )
        return manifest


def build_archive_backup_pack_manifest(
    *,
    workspace_root: Path | str,
    source_dataset_root: Path | str,
    backup_id: str | None = None,
    created_at_utc: datetime | str | None = None,
    files: Sequence[BackupPackFileEntry] | None = None,
    shards: Sequence[BackupPackShardEntry] = (),
    shard_strategy: str = DEFAULT_SHARD_STRATEGY,
    shard_size_mb: int | None = None,
    total_archive_bytes: int | None = None,
    metadata: Mapping[str, Any] | None = None,
    notes: Sequence[str] | None = None,
) -> BackupPackManifest:
    created_at = normalize_created_at_utc(created_at_utc)
    source_root = workspace_relative_path(workspace_root, source_dataset_root)
    inventory = tuple(files) if files is not None else build_file_inventory(source_dataset_root)
    return BackupPackManifest(
        backup_id=backup_id or deterministic_backup_id(source_root, created_at),
        created_at_utc=created_at,
        source_dataset_root=source_root,
        files=inventory,
        shards=tuple(shards),
        shard_strategy=shard_strategy,
        shard_size_mb=shard_size_mb,
        total_archive_bytes=total_archive_bytes,
        metadata=metadata or {},
        notes=tuple(notes) if notes is not None else DEFAULT_MANIFEST_NOTES,
    )


def build_file_inventory(
    dataset_root: Path | str,
    *,
    checksum_algorithm: str = CHECKSUM_SHA256,
    pattern: str = "*.parquet",
) -> tuple[BackupPackFileEntry, ...]:
    root = Path(dataset_root)
    if not root.exists():
        raise FileNotFoundError(f"source dataset root does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"source dataset root must be a directory: {root}")
    if checksum_algorithm != CHECKSUM_SHA256:
        raise BackupPackValidationError("build_file_inventory currently supports sha256 only")

    entries: list[BackupPackFileEntry] = []
    for path in sorted(root.rglob(pattern), key=lambda item: _relative_posix_path(root, item)):
        if not path.is_file():
            continue
        relative_path = _relative_posix_path(root, path)
        entries.append(
            BackupPackFileEntry(
                relative_path=relative_path,
                dataset_name=_infer_dataset_name(relative_path, root),
                size_bytes=path.stat().st_size,
                checksum=_sha256_file(path),
                checksum_algorithm=checksum_algorithm,
                partitions=_infer_partitions(relative_path),
            )
        )
    return tuple(entries)


def deterministic_backup_id(source_dataset_root: str, created_at_utc: str) -> str:
    _validate_utc_timestamp(created_at_utc, "created_at_utc")
    slug = re.sub(r"[^a-z0-9]+", "_", source_dataset_root.lower()).strip("_") or "dataset"
    timestamp = created_at_utc.replace("-", "").replace(":", "").replace("T", "_").removesuffix("Z")
    return f"backup_{timestamp}_{slug}"


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
    raise BackupPackValidationError("created_at_utc must be a datetime, UTC string, or null")


def dumps_manifest_json(manifest: BackupPackManifest | Mapping[str, Any]) -> str:
    data = manifest.to_dict() if isinstance(manifest, BackupPackManifest) else dict(manifest)
    return json.dumps(data, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def loads_manifest(text: str) -> BackupPackManifest:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BackupPackValidationError(f"manifest is not valid JSON: {exc.msg}") from exc
    return BackupPackManifest.from_mapping(data)


def load_manifest(path: Path | str) -> BackupPackManifest:
    return loads_manifest(Path(path).read_text(encoding="utf-8"))


def write_manifest(manifest: BackupPackManifest, path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dumps_manifest_json(manifest), encoding="utf-8")
    return output_path


def validate_manifest_contract(manifest: Mapping[str, Any] | BackupPackManifest) -> BackupPackManifest:
    if isinstance(manifest, BackupPackManifest):
        return BackupPackManifest.from_mapping(manifest.to_dict())
    return BackupPackManifest.from_mapping(manifest)


def _relative_posix_path(root: Path, path: Path) -> str:
    return _normalize_relative_manifest_path(path.relative_to(root), "files[].relative_path")


def _normalize_relative_manifest_path(path: Path | str, field_name: str) -> str:
    try:
        normalized = normalize_workspace_relative_path(path, field_name=field_name)
    except ValueError as exc:
        raise BackupPackValidationError(str(exc)) from exc
    return normalized


def _infer_dataset_name(relative_path: str, root: Path) -> str:
    parts = PurePosixPath(relative_path).parts
    if len(parts) > 1 and "=" not in parts[0]:
        return parts[0]
    return root.name


def _infer_partitions(relative_path: str) -> dict[str, str]:
    partitions: dict[str, str] = {}
    for part in PurePosixPath(relative_path).parts[:-1]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key and value:
            partitions[key] = value
    return dict(sorted(partitions.items()))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_partition_mapping(value: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise BackupPackValidationError("files[].partitions must be an object")
    normalized: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise BackupPackValidationError("files[].partitions keys must be non-empty strings")
        if not isinstance(item, str) or not item:
            raise BackupPackValidationError("files[].partitions values must be non-empty strings")
        normalized[key] = item
    return dict(sorted(normalized.items()))


def _normalize_included_datasets(
    datasets: Sequence[str], files: Sequence[BackupPackFileEntry]
) -> tuple[str, ...]:
    values = tuple(datasets) if datasets else tuple(
        file_entry.dataset_name for file_entry in files if file_entry.dataset_name
    )
    return _normalize_string_tuple(values, "included_datasets")


def _normalize_string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise BackupPackValidationError(f"{field_name} must be a sequence of strings")
    normalized = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise BackupPackValidationError(f"{field_name} must contain only non-empty strings")
        normalized.append(value)
    return tuple(sorted(dict.fromkeys(normalized)))


def _validate_utc_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.match(value):
        raise BackupPackValidationError(
            f"{field_name} must be a UTC timestamp like YYYY-MM-DDTHH:MM:SSZ"
        )


def _validate_non_negative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BackupPackValidationError(f"{field_name} must be a non-negative integer")


def _validate_positive_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BackupPackValidationError(f"{field_name} must be a positive integer")


def _required_file_entries(data: Mapping[str, Any]) -> tuple[BackupPackFileEntry, ...]:
    value = data["files"]
    if not isinstance(value, list):
        raise BackupPackValidationError("manifest.files must be a list")
    return tuple(BackupPackFileEntry.from_mapping(item) for item in value)


def _required_shard_entries(data: Mapping[str, Any]) -> tuple[BackupPackShardEntry, ...]:
    value = data["shards"]
    if not isinstance(value, list):
        raise BackupPackValidationError("manifest.shards must be a list")
    return tuple(BackupPackShardEntry.from_mapping(item) for item in value)


def _require_fields(data: Mapping[str, Any], section: str, fields: Sequence[str]) -> None:
    missing = [field_name for field_name in fields if field_name not in data]
    if missing:
        raise BackupPackValidationError(
            f"{section} is missing required field(s): {', '.join(missing)}"
        )


def _required_str(data: Mapping[str, Any], section: str, field_name: str) -> str:
    if field_name not in data:
        raise BackupPackValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, str) or not value:
        raise BackupPackValidationError(f"{section}.{field_name} must be a non-empty string")
    return value


def _optional_str(data: Mapping[str, Any], section: str, field_name: str) -> str | None:
    if field_name not in data or data[field_name] is None:
        return None
    value = data[field_name]
    if not isinstance(value, str) or not value:
        raise BackupPackValidationError(f"{section}.{field_name} must be a non-empty string or null")
    return value


def _required_bool(data: Mapping[str, Any], section: str, field_name: str) -> bool:
    if field_name not in data:
        raise BackupPackValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, bool):
        raise BackupPackValidationError(f"{section}.{field_name} must be a boolean")
    return value


def _required_int(data: Mapping[str, Any], section: str, field_name: str) -> int:
    if field_name not in data:
        raise BackupPackValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise BackupPackValidationError(f"{section}.{field_name} must be an integer")
    return value


def _optional_int(data: Mapping[str, Any], section: str, field_name: str) -> int | None:
    if field_name not in data or data[field_name] is None:
        return None
    value = data[field_name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise BackupPackValidationError(f"{section}.{field_name} must be an integer or null")
    return value


def _required_str_sequence(
    data: Mapping[str, Any], section: str, field_name: str
) -> tuple[str, ...]:
    if field_name not in data:
        raise BackupPackValidationError(f"{section} is missing required field: {field_name}")
    value = data[field_name]
    if not isinstance(value, list):
        raise BackupPackValidationError(f"{section}.{field_name} must be a list")
    return _normalize_string_tuple(value, f"{section}.{field_name}")


def _optional_str_sequence(
    data: Mapping[str, Any], section: str, field_name: str
) -> tuple[str, ...]:
    if field_name not in data or data[field_name] is None:
        return ()
    value = data[field_name]
    if not isinstance(value, list):
        raise BackupPackValidationError(f"{section}.{field_name} must be a list")
    return _normalize_string_tuple(value, f"{section}.{field_name}")


def _optional_mapping(data: Mapping[str, Any], section: str, field_name: str) -> Mapping[str, Any]:
    if field_name not in data or data[field_name] is None:
        return {}
    value = data[field_name]
    if not isinstance(value, Mapping):
        raise BackupPackValidationError(f"{section}.{field_name} must be an object")
    return dict(value)


def _validate_reported_count(data: Mapping[str, Any], field_name: str, expected: int) -> None:
    reported = _required_int(data, "manifest", field_name)
    if reported != expected:
        raise BackupPackValidationError(
            f"manifest.{field_name} must match computed value {expected}"
        )


def _sorted_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sorted_jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sorted_jsonable(item) for item in value]
    return value
