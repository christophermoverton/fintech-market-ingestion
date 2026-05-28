"""Tests for src.cli.init_project — fintech-init-project workspace bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

import src.cli.init_project as init_project
from src.cli.init_project import (
    ENV_EXAMPLE_CONTENT,
    TICKERS_SAMPLE_CONTENT,
    main,
)
from src.sessions import create_project_session_manifest, load_manifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(tmp_path: Path, extra_args: list[str] | None = None) -> int:
    args = ["--root", str(tmp_path)]
    if extra_args:
        args.extend(extra_args)
    return main(args)


def session_manifest_files(root: Path) -> list[Path]:
    sessions_root = root / "artifacts" / "sessions"
    if not sessions_root.exists():
        return []
    return sorted(sessions_root.glob("*/session_manifest.json"))


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


def test_creates_configs_dir(tmp_path: Path) -> None:
    run(tmp_path)
    assert (tmp_path / "configs").is_dir()


def test_creates_data_curated_dir(tmp_path: Path) -> None:
    run(tmp_path)
    assert (tmp_path / "data" / "curated").is_dir()


def test_creates_reports_dir(tmp_path: Path) -> None:
    run(tmp_path)
    assert (tmp_path / "reports").is_dir()


def test_creates_artifacts_dir(tmp_path: Path) -> None:
    run(tmp_path)
    assert (tmp_path / "artifacts").is_dir()


def test_does_not_create_notebooks_by_default(tmp_path: Path) -> None:
    run(tmp_path)
    assert not (tmp_path / "notebooks").exists()


def test_creates_notebooks_when_flag_given(tmp_path: Path) -> None:
    run(tmp_path, ["--notebooks"])
    assert (tmp_path / "notebooks").is_dir()


def test_colab_profile_creates_colab_ready_workspace_shape(tmp_path: Path) -> None:
    run(tmp_path, ["--colab-profile"])

    expected_dirs = [
        "configs",
        "data/curated",
        "data/research",
        "artifacts",
        "reports",
        "notebooks",
    ]
    for relative_path in expected_dirs:
        assert (tmp_path / relative_path).is_dir()


def test_colab_profile_with_notebooks_is_idempotent(tmp_path: Path) -> None:
    run(tmp_path, ["--colab-profile", "--notebooks"])
    rc = run(tmp_path, ["--colab-profile", "--notebooks"])

    assert rc == 0
    assert (tmp_path / "data" / "research").is_dir()
    assert (tmp_path / "notebooks").is_dir()


# ---------------------------------------------------------------------------
# Sample file creation
# ---------------------------------------------------------------------------


def test_creates_tickers_sample(tmp_path: Path) -> None:
    run(tmp_path)
    tickers = tmp_path / "configs" / "tickers_sample.txt"
    assert tickers.is_file()
    assert "AAPL" in tickers.read_text()


def test_creates_env_example(tmp_path: Path) -> None:
    run(tmp_path)
    env_example = tmp_path / ".env.example"
    assert env_example.is_file()
    content = env_example.read_text()
    assert "ALPACA_API_KEY_ID" in content
    assert "ALPACA_API_SECRET_KEY" in content
    assert "ALPACA_FEED" in content


# ---------------------------------------------------------------------------
# No-overwrite behaviour (default)
# ---------------------------------------------------------------------------


def test_does_not_overwrite_existing_tickers_sample(tmp_path: Path) -> None:
    tickers = tmp_path / "configs" / "tickers_sample.txt"
    tickers.parent.mkdir(parents=True)
    original = "# custom\nMY_TICKER\n"
    tickers.write_text(original)

    run(tmp_path)

    assert tickers.read_text() == original


def test_does_not_overwrite_existing_env_example(tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    original = "MY_CUSTOM_VAR=1\n"
    env_example.write_text(original)

    run(tmp_path)

    assert env_example.read_text() == original


# ---------------------------------------------------------------------------
# --force overwrites sample files
# ---------------------------------------------------------------------------


def test_force_overwrites_tickers_sample(tmp_path: Path) -> None:
    tickers = tmp_path / "configs" / "tickers_sample.txt"
    tickers.parent.mkdir(parents=True)
    tickers.write_text("# old content\n")

    run(tmp_path, ["--force"])

    assert tickers.read_text() == TICKERS_SAMPLE_CONTENT


def test_force_overwrites_env_example(tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_example.write_text("OLD=1\n")

    run(tmp_path, ["--force"])

    assert env_example.read_text() == ENV_EXAMPLE_CONTENT


def test_force_with_colab_profile_does_not_overwrite_user_outputs(tmp_path: Path) -> None:
    research_file = tmp_path / "data" / "research" / "user_notes.txt"
    notebook_file = tmp_path / "notebooks" / "user_notebook.ipynb"
    artifact_file = tmp_path / "artifacts" / "user_artifact.json"
    report_file = tmp_path / "reports" / "user_report.txt"
    for path, content in [
        (research_file, "research\n"),
        (notebook_file, "{}\n"),
        (artifact_file, "{}\n"),
        (report_file, "report\n"),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    run(tmp_path, ["--force", "--colab-profile"])

    assert research_file.read_text(encoding="utf-8") == "research\n"
    assert notebook_file.read_text(encoding="utf-8") == "{}\n"
    assert artifact_file.read_text(encoding="utf-8") == "{}\n"
    assert report_file.read_text(encoding="utf-8") == "report\n"


# ---------------------------------------------------------------------------
# Path handling — relative and absolute --root values
# ---------------------------------------------------------------------------


def test_absolute_root_path(tmp_path: Path) -> None:
    absolute = tmp_path / "workspace"
    absolute.mkdir()
    rc = main(["--root", str(absolute)])
    assert rc == 0
    assert (absolute / "configs").is_dir()


def test_relative_root_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "myproject"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    rc = main(["--root", "myproject"])
    assert rc == 0
    assert (workspace / "configs").is_dir()


# ---------------------------------------------------------------------------
# Return code
# ---------------------------------------------------------------------------


def test_returns_zero_on_success(tmp_path: Path) -> None:
    assert run(tmp_path) == 0


# ---------------------------------------------------------------------------
# Idempotency — running twice is safe
# ---------------------------------------------------------------------------


def test_idempotent_on_second_run(tmp_path: Path) -> None:
    run(tmp_path)
    rc = run(tmp_path)
    assert rc == 0
    assert (tmp_path / "configs" / "tickers_sample.txt").is_file()


# ---------------------------------------------------------------------------
# Opt-in project-session bootstrap
# ---------------------------------------------------------------------------


def test_does_not_create_session_manifest_by_default(tmp_path: Path) -> None:
    run(tmp_path)

    assert session_manifest_files(tmp_path) == []


def test_session_name_without_with_session_does_not_create_manifest(tmp_path: Path) -> None:
    run(tmp_path, ["--session-name", "demo"])

    assert session_manifest_files(tmp_path) == []


def test_with_session_creates_valid_manifest_under_session_artifacts(tmp_path: Path) -> None:
    run(tmp_path, ["--notebooks", "--with-session", "--session-name", "demo"])

    manifests = session_manifest_files(tmp_path)
    assert len(manifests) == 1
    manifest_path = manifests[0]
    manifest = load_manifest(manifest_path)

    assert manifest_path == (
        tmp_path / "artifacts" / "sessions" / manifest.session_id / "session_manifest.json"
    )
    assert manifest.session_name == "demo"
    assert manifest.workspace.root_semantics == "workspace_relative"
    assert manifest.workspace.paths.to_dict() == {
        "configs": "configs",
        "curated_data": "data/curated",
        "research_data": "data/research",
        "artifacts": "artifacts",
        "reports": "reports",
        "notebooks": "notebooks",
    }
    assert manifest.persistence.adapter == "none"
    assert manifest.persistence.destination is None
    assert manifest.save_policy.mode == "metadata_only"
    assert manifest.save_policy.include == ()
    assert manifest.save_policy.exclude == ("data/curated",)
    assert manifest.save_policy.include_curated_data is False


def test_with_session_defaults_session_name(tmp_path: Path) -> None:
    run(tmp_path, ["--with-session"])

    manifest = load_manifest(session_manifest_files(tmp_path)[0])

    assert manifest.session_name == "default"
    assert manifest.session_id.endswith("_default")


def test_with_session_sanitizes_session_id_for_path_usage(tmp_path: Path) -> None:
    run(tmp_path, ["--with-session", "--session-name", "Demo Session / 1"])

    manifest_path = session_manifest_files(tmp_path)[0]
    manifest = load_manifest(manifest_path)

    assert manifest.session_name == "Demo Session / 1"
    assert manifest.session_id.endswith("_demo_session_1")
    assert "/" not in manifest.session_id
    assert "\\" not in manifest.session_id
    assert manifest_path.parent.name == manifest.session_id


def test_with_session_does_not_mutate_research_reports_or_curated_data(tmp_path: Path) -> None:
    run(tmp_path, ["--with-session", "--session-name", "demo"])

    assert (tmp_path / "data" / "curated").is_dir()
    assert list((tmp_path / "data" / "curated").iterdir()) == []
    assert not (tmp_path / "data" / "research").exists()
    assert list((tmp_path / "reports").iterdir()) == []


def test_colab_profile_with_session_creates_only_metadata_and_empty_workspace_dirs(
    tmp_path: Path,
) -> None:
    run(tmp_path, ["--colab-profile", "--with-session", "--session-name", "colab-market-data"])

    manifests = session_manifest_files(tmp_path)
    assert len(manifests) == 1
    manifest = load_manifest(manifests[0])

    assert manifest.session_name == "colab-market-data"
    assert manifest.workspace.paths.to_dict()["research_data"] == "data/research"
    assert manifest.persistence.adapter == "none"
    assert manifest.persistence.destination is None
    assert manifest.save_policy.mode == "metadata_only"
    assert list((tmp_path / "data" / "curated").iterdir()) == []
    assert list((tmp_path / "data" / "research").iterdir()) == []
    assert list((tmp_path / "reports").iterdir()) == []
    assert not (tmp_path / "artifacts" / "session_exports").exists()
    assert not (tmp_path / "artifacts" / "restores").exists()


def test_repeated_with_session_creates_new_timestamped_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created_at_values = iter(["2026-05-25T22:20:32Z", "2026-05-25T22:20:33Z"])

    def create_manifest_with_next_timestamp(*, session_name: str):
        return create_project_session_manifest(
            session_name=session_name,
            created_at_utc=next(created_at_values),
            package_version="0.8.0",
        )

    monkeypatch.setattr(
        init_project,
        "create_project_session_manifest",
        create_manifest_with_next_timestamp,
    )

    run(tmp_path, ["--with-session", "--session-name", "demo"])
    run(tmp_path, ["--with-session", "--session-name", "demo"])

    manifests = session_manifest_files(tmp_path)
    session_ids = {load_manifest(path).session_id for path in manifests}

    assert len(manifests) == 2
    assert session_ids == {
        "session_20260525_222032_demo",
        "session_20260525_222033_demo",
    }


def test_with_session_collision_skips_without_overwriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def create_manifest_with_fixed_timestamp(*, session_name: str):
        return create_project_session_manifest(
            session_name=session_name,
            created_at_utc="2026-05-25T22:20:32Z",
            package_version="0.8.0",
        )

    monkeypatch.setattr(
        init_project,
        "create_project_session_manifest",
        create_manifest_with_fixed_timestamp,
    )

    run(tmp_path, ["--with-session", "--session-name", "demo"])
    manifest_path = session_manifest_files(tmp_path)[0]
    original_text = manifest_path.read_text(encoding="utf-8")

    run(tmp_path, ["--with-session", "--session-name", "demo"])
    captured = capsys.readouterr()

    assert len(session_manifest_files(tmp_path)) == 1
    assert manifest_path.read_text(encoding="utf-8") == original_text
    assert "artifacts" in captured.out
    assert "skipped (already exists)" in captured.out


def test_force_with_session_still_only_overwrites_generated_sample_files(tmp_path: Path) -> None:
    run(tmp_path, ["--with-session", "--session-name", "demo"])
    unrelated_session_manifest = (
        tmp_path / "artifacts" / "sessions" / "session_existing" / "session_manifest.json"
    )
    unrelated_session_manifest.parent.mkdir(parents=True)
    unrelated_content = '{"sentinel": true}\n'
    unrelated_session_manifest.write_text(unrelated_content, encoding="utf-8")

    tickers = tmp_path / "configs" / "tickers_sample.txt"
    tickers.write_text("# custom\nCUSTOM\n", encoding="utf-8")
    run(tmp_path, ["--force", "--with-session", "--session-name", "demo"])

    assert tickers.read_text(encoding="utf-8") == TICKERS_SAMPLE_CONTENT
    assert unrelated_session_manifest.read_text(encoding="utf-8") == unrelated_content
