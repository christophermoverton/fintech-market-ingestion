"""Tests for src.cli.init_project — fintech-init-project workspace bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.cli.init_project import (
    ENV_EXAMPLE_CONTENT,
    TICKERS_SAMPLE_CONTENT,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(tmp_path: Path, extra_args: list[str] | None = None) -> int:
    args = ["--root", str(tmp_path)]
    if extra_args:
        args.extend(extra_args)
    return main(args)


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
