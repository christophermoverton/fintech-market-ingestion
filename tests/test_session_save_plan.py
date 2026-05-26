from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.sessions import (
    POLICY_ARTIFACTS_AND_REPORTS,
    POLICY_CURATED_1M_BARS,
    SavePlanEntry,
    build_save_plan,
    dumps_save_plan_json,
    resolve_save_policy,
)


def test_empty_include_list_returns_empty_explicit_plan(tmp_path: Path) -> None:
    plan = build_save_plan(tmp_path, include=())

    assert plan.entries == ()
    assert plan.include == ()
    assert plan.exclude == ("data/curated",)
    assert plan.summary.to_dict() == {"file_count": 0, "total_size_bytes": 0}


def test_include_selected_files_under_workspace_root(tmp_path: Path) -> None:
    _write_text(tmp_path / "reports" / "summary.txt", "summary")
    _write_text(tmp_path / "artifacts" / "run.json", "{}")

    plan = build_save_plan(tmp_path, include=("reports", "artifacts/run.json"))

    assert plan.entries == (
        SavePlanEntry(
            source_path="artifacts/run.json",
            destination_path="artifacts/run.json",
            size_bytes=2,
        ),
        SavePlanEntry(
            source_path="reports/summary.txt",
            destination_path="reports/summary.txt",
            size_bytes=7,
        ),
    )


def test_save_plan_entries_are_deterministically_ordered(tmp_path: Path) -> None:
    _write_text(tmp_path / "reports" / "z.txt", "z")
    _write_text(tmp_path / "reports" / "a.txt", "a")

    plan = build_save_plan(tmp_path, include=("reports",))

    assert [entry.source_path for entry in plan.entries] == ["reports/a.txt", "reports/z.txt"]


def test_save_plan_summary_counts_files_and_bytes(tmp_path: Path) -> None:
    _write_text(tmp_path / "reports" / "a.txt", "aa")
    _write_text(tmp_path / "reports" / "b.txt", "bbb")

    plan = build_save_plan(tmp_path, include=("reports",))

    assert plan.summary.file_count == 2
    assert plan.summary.total_size_bytes == 5


def test_exclude_roots_remove_matching_files(tmp_path: Path) -> None:
    _write_text(tmp_path / "reports" / "keep.txt", "keep")
    _write_text(tmp_path / "reports" / "tmp" / "skip.txt", "skip")

    plan = build_save_plan(tmp_path, include=("reports",), exclude=("reports/tmp",))

    assert [entry.source_path for entry in plan.entries] == ["reports/keep.txt"]


def test_workspace_relative_posix_paths_are_used(tmp_path: Path) -> None:
    _write_text(tmp_path / "data" / "research" / "summary.txt", "research")

    plan = build_save_plan(tmp_path, include=("data\\research",), exclude=())

    assert plan.include == ("data/research",)
    assert plan.entries[0].source_path == "data/research/summary.txt"
    assert "\\" not in plan.entries[0].source_path


def test_unsafe_include_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not escape"):
        build_save_plan(tmp_path, include=("../reports",))


def test_unsafe_exclude_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="drive-qualified"):
        build_save_plan(tmp_path, include=("reports",), exclude=("C:Temp/reports",))


def test_missing_include_path_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Included path does not exist"):
        build_save_plan(tmp_path, include=("reports",))


def test_save_plan_json_is_deterministic(tmp_path: Path) -> None:
    _write_text(tmp_path / "reports" / "summary.txt", "summary")

    plan = build_save_plan(tmp_path, include=("reports",))
    first = dumps_save_plan_json(plan)
    second = plan.to_json()

    assert first == second
    assert first.endswith("\n")
    assert (
        first
        == json.dumps(json.loads(first), sort_keys=True, indent=2, separators=(",", ": ")) + "\n"
    )


def test_save_plan_does_not_copy_or_mutate_files(tmp_path: Path) -> None:
    source = _write_text(tmp_path / "reports" / "summary.txt", "summary")

    build_save_plan(tmp_path, include=("reports",))

    assert source.read_text(encoding="utf-8") == "summary"
    assert not (tmp_path / "persisted").exists()


def test_curated_data_excluded_by_default_even_when_parent_is_included(tmp_path: Path) -> None:
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    _write_text(tmp_path / "data" / "research" / "summary.txt", "research")

    plan = build_save_plan(tmp_path, include=("data",))

    assert [entry.source_path for entry in plan.entries] == ["data/research/summary.txt"]


def test_curated_data_can_be_explicitly_included_when_not_excluded(tmp_path: Path) -> None:
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")

    plan = build_save_plan(tmp_path, include=("data/curated",), exclude=())

    assert [entry.source_path for entry in plan.entries] == ["data/curated/bars.parquet"]


def test_policy_resolved_includes_feed_build_save_plan(tmp_path: Path) -> None:
    _write_text(tmp_path / "configs" / "tickers.txt", "AAPL\n")
    _write_text(tmp_path / "artifacts" / "run.json", "{}")
    _write_text(tmp_path / "reports" / "summary.txt", "summary")
    _write_text(tmp_path / "data" / "curated" / "bars.parquet", "curated")
    policy = resolve_save_policy(POLICY_ARTIFACTS_AND_REPORTS)

    plan = build_save_plan(tmp_path, include=policy.include, exclude=policy.exclude)

    assert [entry.source_path for entry in plan.entries] == [
        "artifacts/run.json",
        "configs/tickers.txt",
        "reports/summary.txt",
    ]
    assert plan.summary.file_count == 3
    assert plan.summary.total_size_bytes == sum(
        (tmp_path / path).stat().st_size
        for path in ["artifacts/run.json", "configs/tickers.txt", "reports/summary.txt"]
    )


def test_policy_guardrails_exclude_1m_data_without_opt_in(tmp_path: Path) -> None:
    _write_text(tmp_path / "data" / "curated" / "bars_daily" / "daily.parquet", "daily")
    _write_text(tmp_path / "data" / "curated" / "bars_1m" / "minute.parquet", "minute")
    policy = resolve_save_policy(
        "all_selected",
        include_curated_data=True,
        extra_include=("data/curated",),
    )

    plan = build_save_plan(tmp_path, include=policy.include, exclude=policy.exclude)

    assert [entry.source_path for entry in plan.entries] == [
        "data/curated/bars_daily/daily.parquet"
    ]


def test_1m_policy_allows_1m_data_with_explicit_flags(tmp_path: Path) -> None:
    _write_text(tmp_path / "data" / "curated" / "bars_1m" / "minute.parquet", "minute")
    policy = resolve_save_policy(
        POLICY_CURATED_1M_BARS,
        include_curated_data=True,
        include_1m_data=True,
    )

    plan = build_save_plan(tmp_path, include=policy.include, exclude=policy.exclude)

    assert [entry.source_path for entry in plan.entries] == ["data/curated/bars_1m/minute.parquet"]


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
