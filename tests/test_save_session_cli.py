from __future__ import annotations

import json
from pathlib import Path

from src.cli.save_session import main
from src.sessions import (
    create_project_session_manifest,
    write_project_session_manifest_for_workspace,
)


def create_session(root: Path, session_id: str = "session_20260525_222032_demo") -> str:
    manifest = create_project_session_manifest(
        session_name="demo",
        session_id=session_id,
        created_at_utc="2026-05-25T22:20:32Z",
        package_version="0.8.0",
    )
    write_project_session_manifest_for_workspace(root, manifest)
    return manifest.session_id


def test_save_session_main_missing_session_manifest_fails(tmp_path: Path, capsys) -> None:
    rc = main(["--root", str(tmp_path), "--session-id", "missing", "--dry-run"])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Session manifest does not exist" in captured.err


def test_save_session_dry_run_builds_plan_and_copies_no_files(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(destination),
            "--include",
            "configs",
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "dry_run: True" in captured.out
    assert "file_count: 1" in captured.out
    assert not destination.exists()


def test_save_session_non_dry_run_requires_include(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(tmp_path / "exports"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "At least one --include path" in captured.err


def test_save_session_with_local_adapter_copies_selected_files(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    source = _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--adapter",
            "local",
            "--destination",
            str(destination),
            "--include",
            "configs",
        ]
    )

    assert rc == 0
    assert (destination / "configs" / "tickers.txt").read_text(encoding="utf-8") == "AAPL\n"
    assert source.read_text(encoding="utf-8") == "AAPL\n"


def test_save_session_manifest_is_deterministic_json(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    destination = tmp_path / "exports" / session_id

    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "--session-id",
                session_id,
                "--destination",
                str(destination),
                "--include",
                "configs",
            ]
        )
        == 0
    )

    text = (destination / "session_save_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert text == json.dumps(manifest, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
    assert manifest["operation"] == "save"
    assert manifest["session_id"] == session_id
    assert manifest["adapter"] == "local"
    assert manifest["include"] == ["configs"]
    assert manifest["exclude"] == ["data/curated"]
    assert manifest["save_policy"]["name"] == "all_selected"
    assert manifest["save_policy"]["include_1m_data"] is False
    assert manifest["copied_file_count"] == 1
    assert manifest["files"][0]["status"] == "copied"


def test_save_session_excludes_curated_data_by_default(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    _write_text(tmp_path / "data" / "research" / "summary.txt", "research")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(destination),
            "--include",
            "data",
        ]
    )

    assert rc == 0
    assert not (destination / "data" / "curated" / "bars.parquet").exists()
    assert (destination / "data" / "research" / "summary.txt").exists()


def test_save_session_custom_exclude_preserves_curated_default(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    _write_text(tmp_path / "data" / "research" / "summary.txt", "research")
    _write_text(tmp_path / "reports" / "summary.txt", "report")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(destination),
            "--include",
            "data",
            "--exclude",
            "reports",
        ]
    )

    manifest = json.loads((destination / "session_save_manifest.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert not (destination / "data" / "curated" / "bars.parquet").exists()
    assert (destination / "data" / "research" / "summary.txt").exists()
    assert "data/curated" in manifest["exclude"]
    assert "reports" in manifest["exclude"]


def test_save_session_includes_curated_data_only_with_explicit_flag(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(destination),
            "--include",
            "data/curated",
            "--include-curated-data",
        ]
    )

    manifest = json.loads((destination / "session_save_manifest.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert (destination / "data" / "curated" / "bars.parquet").exists()
    assert manifest["include_curated_data"] is True
    assert manifest["include_1m_data"] is False
    assert manifest["exclude"] == [
        "data/curated/1m",
        "data/curated/bars_1m",
        "data/curated/features_1m",
    ]


def test_save_session_unsafe_include_path_is_rejected(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--destination",
            str(tmp_path / "exports"),
            "--include",
            "../configs",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "must not escape" in captured.err


def test_save_session_with_google_drive_adapter_uses_mounted_path(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    destination = tmp_path / "content" / "drive" / "MyDrive" / "fmi" / "demo"

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--adapter",
            "google-drive",
            "--destination",
            str(destination),
            "--create-destination",
            "--include",
            "configs",
        ]
    )

    assert rc == 0
    assert (destination / "configs" / "tickers.txt").exists()
    manifest = json.loads((destination / "session_save_manifest.json").read_text(encoding="utf-8"))
    assert manifest["adapter"] == "google-drive"


def test_save_session_policy_metadata_only_dry_run_copies_nothing(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "metadata_only",
            "--destination",
            str(destination),
            "--dry-run",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "policy: metadata_only" in captured.out
    assert "include_curated_data: False" in captured.out
    assert "include_1m_data: False" in captured.out
    assert not destination.exists()


def test_save_session_policy_artifacts_and_reports_selects_expected_files(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    _write_text(tmp_path / "reports" / "summary.txt", "summary")
    _write_text(tmp_path / "artifacts" / "run.json", "{}")
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "artifacts_and_reports",
            "--destination",
            str(destination),
        ]
    )

    assert rc == 0
    assert (destination / "configs" / "tickers.txt").exists()
    assert (destination / "reports" / "summary.txt").exists()
    assert (destination / "artifacts" / "run.json").exists()
    assert not (destination / "data" / "curated" / "bars.parquet").exists()


def test_save_session_policy_research_outputs_selects_expected_files(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    _write_text(tmp_path / "artifacts" / "run.json", "{}")
    _write_text(tmp_path / "reports" / "summary.txt", "summary")
    _write_text(tmp_path / "data" / "research" / "summary.txt", "research")
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "research_outputs",
            "--destination",
            str(destination),
        ]
    )

    assert rc == 0
    assert (destination / "data" / "research" / "summary.txt").exists()
    assert not (destination / "data" / "curated" / "bars.parquet").exists()


def test_save_session_policy_curated_daily_requires_curated_opt_in(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "curated_daily_bars",
            "--destination",
            str(tmp_path / "exports"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "requires --include-curated-data" in captured.err


def test_save_session_policy_curated_1m_requires_1m_opt_in(tmp_path: Path, capsys) -> None:
    session_id = create_session(tmp_path)

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "curated_1m_bars",
            "--include-curated-data",
            "--destination",
            str(tmp_path / "exports"),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "requires --include-1m-data" in captured.err


def test_save_session_policy_curated_1m_with_flags_succeeds(tmp_path: Path) -> None:
    session_id = create_session(tmp_path)
    _write_text(tmp_path / "data" / "curated" / "bars_1m" / "minute.parquet", "minute")
    destination = tmp_path / "exports" / session_id

    rc = main(
        [
            "--root",
            str(tmp_path),
            "--session-id",
            session_id,
            "--policy",
            "curated_1m_bars",
            "--include-curated-data",
            "--include-1m-data",
            "--destination",
            str(destination),
        ]
    )

    manifest = json.loads((destination / "session_save_manifest.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert (destination / "data" / "curated" / "bars_1m" / "minute.parquet").exists()
    assert manifest["save_policy"]["name"] == "curated_1m_bars"
    assert manifest["include_curated_data"] is True
    assert manifest["include_1m_data"] is True


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
