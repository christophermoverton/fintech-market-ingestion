"""High-level project-session helpers independent from CLI commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.sessions.session_manifest import (
    PackageMetadata,
    PersistenceSettings,
    SavePolicy,
    SessionManifest,
    WorkspaceMetadata,
    write_manifest,
)
from src.sessions.session_paths import WorkspacePaths

DEFAULT_SESSION_MANIFEST_PATH = Path("artifacts/project_session/session_manifest.json")


def create_project_session_manifest(
    *,
    session_name: str,
    session_id: str | None = None,
    created_at_utc: datetime | str | None = None,
    package_version: str | None = None,
    workspace_paths: WorkspacePaths | None = None,
    persistence_adapter: str = "none",
    persistence_destination: str | None = None,
    save_policy_mode: str = "metadata_only",
    include: tuple[str, ...] = (),
    exclude: tuple[str, ...] = ("data/curated",),
    include_curated_data: bool = False,
) -> SessionManifest:
    """Build a portable project-session manifest without touching workspace data."""

    package = PackageMetadata(version=package_version) if package_version else PackageMetadata()
    workspace = WorkspaceMetadata(paths=workspace_paths or WorkspacePaths())
    persistence = PersistenceSettings(
        adapter=persistence_adapter,
        destination=persistence_destination,
    )
    save_policy = SavePolicy(
        mode=save_policy_mode,
        include=include,
        exclude=exclude,
        include_curated_data=include_curated_data,
    )
    return SessionManifest.create(
        session_name=session_name,
        session_id=session_id,
        created_at_utc=created_at_utc,
        package=package,
        workspace=workspace,
        persistence=persistence,
        save_policy=save_policy,
    )


def write_project_session_manifest(
    manifest: SessionManifest,
    output_path: Path | str = DEFAULT_SESSION_MANIFEST_PATH,
) -> Path:
    """Write only the session manifest JSON artifact."""

    return write_manifest(manifest, output_path)
