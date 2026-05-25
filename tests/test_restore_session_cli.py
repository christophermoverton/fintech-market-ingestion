from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.cli.restore_session as restore_session
from src.cli.restore_session import main
from src.persistence import PersistedFile


def test_restore_session_main_dry_run_lists_plan_and_writes_no_files(
    tmp_path: Path, capsys
) -> None:
    source = tmp_path / "exports"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")

    rc = main(["--root", str(tmp_path / "workspace"), "--source", str(source), "--dry-run"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "dry_run: True" in captured.out
    assert "planned_file_count: 1" in captured.out
    assert not (tmp_path / "workspace" / "configs" / "tickers.txt").exists()
    assert not (tmp_path / "workspace" / "artifacts" / "restores").exists()


def test_restore_session_copies_persisted_files_into_workspace(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")

    rc = main(["--root", str(workspace), "--source", str(source)])

    assert rc == 0
    assert (workspace / "configs" / "tickers.txt").read_text(encoding="utf-8") == "AAPL\n"


def test_restore_session_refuses_overwrite_without_force(tmp_path: Path, capsys) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")
    existing = _write_text(workspace / "configs" / "tickers.txt", "LOCAL\n")

    rc = main(["--root", str(workspace), "--source", str(source)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "without --force" in captured.err
    assert existing.read_text(encoding="utf-8") == "LOCAL\n"


def test_restore_session_overwrites_with_force(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")
    _write_text(workspace / "configs" / "tickers.txt", "LOCAL\n")

    rc = main(["--root", str(workspace), "--source", str(source), "--force"])

    assert rc == 0
    assert (workspace / "configs" / "tickers.txt").read_text(encoding="utf-8") == "AAPL\n"


def test_restore_session_manifest_is_deterministic_when_executed(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")

    assert main(["--root", str(workspace), "--source", str(source)]) == 0

    manifests = sorted((workspace / "artifacts" / "restores").glob("*/restore_manifest.json"))
    assert len(manifests) == 1
    text = manifests[0].read_text(encoding="utf-8")
    manifest = json.loads(text)
    assert text == json.dumps(manifest, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
    assert manifest["operation"] == "restore"
    assert manifest["adapter"] == "local"
    assert manifest["restored_file_count"] == 1
    assert manifest["overwritten_file_count"] == 0
    assert manifest["collision_count"] == 0
    assert manifest["files"][0]["status"] == "restored"


def test_restore_session_force_manifest_records_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")
    _write_text(workspace / "configs" / "tickers.txt", "LOCAL\n")

    assert main(["--root", str(workspace), "--source", str(source), "--force"]) == 0

    manifest_path = next((workspace / "artifacts" / "restores").glob("*/restore_manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["restored_file_count"] == 1
    assert manifest["overwritten_file_count"] == 1
    assert manifest["collision_count"] == 1
    assert manifest["skipped_file_count"] == 0
    assert manifest["files"][0]["status"] == "restored_overwrite"


def test_restore_session_skips_save_metadata_file(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    workspace = tmp_path / "workspace"
    _write_text(source / "session_save_manifest.json", "{}\n")
    _write_text(source / "configs" / "tickers.txt", "AAPL\n")

    assert main(["--root", str(workspace), "--source", str(source)]) == 0

    assert not (workspace / "session_save_manifest.json").exists()
    assert (workspace / "configs" / "tickers.txt").exists()


def test_restore_session_source_root_must_exist(tmp_path: Path, capsys) -> None:
    rc = main(["--root", str(tmp_path / "workspace"), "--source", str(tmp_path / "missing")])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Restore source does not exist" in captured.err


def test_restore_session_unsafe_persisted_path_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    class FakeAdapter:
        def list_files(self):
            return [PersistedFile(path="../outside.txt", size_bytes=1)]

    monkeypatch.setattr(
        restore_session, "_adapter_for_restore", lambda adapter_name, source: FakeAdapter()
    )

    rc = main(["--root", str(tmp_path / "workspace"), "--source", str(tmp_path / "source")])

    captured = capsys.readouterr()
    assert rc == 1
    assert "must not escape" in captured.err


def test_restore_session_with_google_drive_adapter_uses_mounted_path(tmp_path: Path) -> None:
    source = tmp_path / "content" / "drive" / "MyDrive" / "fmi" / "demo"
    workspace = tmp_path / "workspace"
    _write_text(source / "reports" / "summary.txt", "summary")

    rc = main(
        [
            "--root",
            str(workspace),
            "--adapter",
            "google-drive",
            "--source",
            str(source),
        ]
    )

    assert rc == 0
    assert (workspace / "reports" / "summary.txt").read_text(encoding="utf-8") == "summary"


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
