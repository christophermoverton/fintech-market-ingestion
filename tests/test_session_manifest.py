from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.sessions import (
    ManifestValidationError,
    SavePolicy,
    SessionManifest,
    WorkspacePaths,
    create_project_session_manifest,
    dumps_manifest_json,
    load_manifest,
    loads_manifest,
    normalize_workspace_relative_path,
    workspace_relative_path,
    write_project_session_manifest,
)

FIXED_CREATED_AT = "2026-05-25T22:20:32Z"


def fixed_manifest() -> SessionManifest:
    return create_project_session_manifest(
        session_name="demo",
        created_at_utc=FIXED_CREATED_AT,
        package_version="0.8.0",
    )


def test_manifest_creation_contains_required_contract_fields() -> None:
    manifest = fixed_manifest()
    data = manifest.to_dict()

    assert data["schema_version"] == 1
    assert data["session_id"] == "session_20260525_222032_demo"
    assert data["session_name"] == "demo"
    assert data["created_at_utc"] == FIXED_CREATED_AT
    assert data["package"] == {
        "name": "fintech-market-ingestion",
        "version": "0.8.0",
    }
    assert data["workspace"]["root_semantics"] == "workspace_relative"
    assert data["workspace"]["paths"]["configs"] == "configs"
    assert data["workspace"]["paths"]["curated_data"] == "data/curated"
    assert data["workspace"]["paths"]["research_data"] == "data/research"
    assert data["workspace"]["paths"]["artifacts"] == "artifacts"
    assert data["workspace"]["paths"]["reports"] == "reports"
    assert data["workspace"]["paths"]["notebooks"] == "notebooks"
    assert data["persistence"] == {
        "adapter": "none",
        "destination": None,
        "runtime_only": {},
    }


def test_manifest_json_is_deterministic_and_stably_formatted() -> None:
    manifest = fixed_manifest()

    first = dumps_manifest_json(manifest)
    second = dumps_manifest_json(manifest)

    assert first == second
    assert first.endswith("\n")
    assert (
        first
        == json.dumps(json.loads(first), sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
    )


def test_manifest_round_trip_from_json() -> None:
    original = fixed_manifest()

    loaded = loads_manifest(dumps_manifest_json(original))

    assert loaded == original
    assert dumps_manifest_json(loaded) == dumps_manifest_json(original)


def test_manifest_file_round_trip(tmp_path: Path) -> None:
    output_path = tmp_path / "artifacts" / "project_session" / "session_manifest.json"
    manifest = fixed_manifest()

    written = write_project_session_manifest(manifest, output_path)
    loaded = load_manifest(written)

    assert written == output_path
    assert loaded == manifest


def test_required_field_validation_reports_missing_field() -> None:
    data = fixed_manifest().to_dict()
    del data["save_policy"]

    with pytest.raises(ManifestValidationError, match="missing required field.*save_policy"):
        SessionManifest.from_mapping(data)


def test_invalid_manifest_json_fails_clearly() -> None:
    with pytest.raises(ManifestValidationError, match="not valid JSON"):
        loads_manifest("{not-json")


def test_invalid_manifest_field_type_fails_clearly() -> None:
    data = fixed_manifest().to_dict()
    data["schema_version"] = "1"

    with pytest.raises(ManifestValidationError, match="schema_version must be an integer"):
        SessionManifest.from_mapping(data)


def test_invalid_utc_timestamp_fails_clearly() -> None:
    with pytest.raises(ManifestValidationError, match="UTC timestamp"):
        create_project_session_manifest(
            session_name="demo",
            created_at_utc="2026-05-25 22:20:32",
        )


def test_workspace_paths_are_workspace_relative() -> None:
    paths = WorkspacePaths(
        configs="configs",
        curated_data=Path("data") / "curated",
        research_data="data\\research",
        artifacts="artifacts",
        reports="reports",
        notebooks="notebooks",
    )

    assert paths.to_dict() == {
        "configs": "configs",
        "curated_data": "data/curated",
        "research_data": "data/research",
        "artifacts": "artifacts",
        "reports": "reports",
        "notebooks": "notebooks",
    }
    assert normalize_workspace_relative_path("data\\research") == "data/research"


def test_absolute_path_under_workspace_can_be_converted_to_relative(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    absolute_report_path = workspace_root / "reports" / "summary.csv"

    assert workspace_relative_path(workspace_root, absolute_report_path) == "reports/summary.csv"


def test_absolute_path_outside_workspace_is_rejected(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    outside_path = tmp_path / "other" / "reports" / "summary.csv"

    with pytest.raises(ValueError, match="outside the workspace root"):
        workspace_relative_path(workspace_root, outside_path)


def test_absolute_workspace_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="workspace-relative, not drive-qualified"):
        WorkspacePaths(configs="C:/Temp/project/configs")


def test_drive_qualified_windows_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="drive-qualified"):
        WorkspacePaths(configs="C:Temp/project/configs")


def test_parent_traversal_workspace_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not escape"):
        WorkspacePaths(artifacts="../artifacts")


def test_persistence_destination_avoids_absolute_path_leakage() -> None:
    with pytest.raises(ManifestValidationError, match="persistence.destination.*drive-qualified"):
        create_project_session_manifest(
            session_name="demo",
            created_at_utc=FIXED_CREATED_AT,
            persistence_adapter="drive",
            persistence_destination="C:/Temp/session-copy",
        )


def test_drive_qualified_persistence_destination_is_rejected() -> None:
    with pytest.raises(ManifestValidationError, match="drive-qualified"):
        create_project_session_manifest(
            session_name="demo",
            created_at_utc=FIXED_CREATED_AT,
            persistence_adapter="local_copy",
            persistence_destination="C:Temp/session-copy",
        )


def test_relative_persistence_destination_is_allowed() -> None:
    manifest = create_project_session_manifest(
        session_name="demo",
        created_at_utc=FIXED_CREATED_AT,
        persistence_adapter="local_copy",
        persistence_destination="artifacts/project_session/backups",
        package_version="0.8.0",
    )

    assert manifest.persistence.destination == "artifacts/project_session/backups"


def test_curated_data_is_excluded_by_default() -> None:
    manifest = fixed_manifest()

    assert manifest.save_policy.include_curated_data is False
    assert manifest.save_policy.include == ()
    assert manifest.save_policy.exclude == ("data/curated",)
    assert manifest.to_dict()["save_policy"] == {
        "mode": "metadata_only",
        "include": [],
        "exclude": ["data/curated"],
        "include_curated_data": False,
    }


def test_save_policy_sorts_include_and_exclude_rules() -> None:
    policy = SavePolicy(
        include=("reports", "artifacts"),
        exclude=("data/research", "configs"),
        include_curated_data=False,
    )

    assert policy.include == ("artifacts", "reports")
    assert policy.exclude == ("configs", "data/curated", "data/research")


def test_session_manifest_write_only_creates_requested_manifest(tmp_path: Path) -> None:
    output_path = tmp_path / "artifacts" / "project_session" / "session_manifest.json"

    write_project_session_manifest(fixed_manifest(), output_path)

    assert output_path.is_file()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "reports").exists()
    assert not (tmp_path / "artifacts" / "unrelated").exists()
