"""Portable project-session contracts for fintech-market-ingestion."""

from src.sessions.project_session import (
    SESSION_MANIFEST_FILENAME,
    SESSIONS_ARTIFACT_DIR,
    create_project_session_manifest,
    session_manifest_path,
    write_project_session_manifest,
    write_project_session_manifest_for_workspace,
)
from src.sessions.save_plan import (
    SavePlan,
    SavePlanEntry,
    SavePlanSummary,
    build_save_plan,
    dumps_save_plan_json,
)
from src.sessions.session_manifest import (
    DEFAULT_SAVE_POLICY_MODE,
    PACKAGE_NAME,
    SCHEMA_VERSION,
    ManifestValidationError,
    PackageMetadata,
    PersistenceSettings,
    SavePolicy,
    SessionManifest,
    WorkspaceMetadata,
    dumps_manifest_json,
    load_manifest,
    loads_manifest,
    write_manifest,
)
from src.sessions.session_paths import (
    ROOT_SEMANTICS_WORKSPACE_RELATIVE,
    WorkspacePaths,
    normalize_workspace_relative_path,
    workspace_relative_path,
)

__all__ = [
    "DEFAULT_SAVE_POLICY_MODE",
    "PACKAGE_NAME",
    "ROOT_SEMANTICS_WORKSPACE_RELATIVE",
    "SCHEMA_VERSION",
    "ManifestValidationError",
    "PackageMetadata",
    "PersistenceSettings",
    "SavePolicy",
    "SavePlan",
    "SavePlanEntry",
    "SavePlanSummary",
    "SessionManifest",
    "SESSION_MANIFEST_FILENAME",
    "SESSIONS_ARTIFACT_DIR",
    "WorkspaceMetadata",
    "WorkspacePaths",
    "build_save_plan",
    "create_project_session_manifest",
    "dumps_manifest_json",
    "dumps_save_plan_json",
    "load_manifest",
    "loads_manifest",
    "normalize_workspace_relative_path",
    "session_manifest_path",
    "workspace_relative_path",
    "write_manifest",
    "write_project_session_manifest",
    "write_project_session_manifest_for_workspace",
]
