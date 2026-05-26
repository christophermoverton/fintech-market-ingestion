from __future__ import annotations

import pytest

from src.sessions import (
    POLICY_ALL_SELECTED,
    POLICY_ARTIFACTS_AND_REPORTS,
    POLICY_CORPORATE_ACTIONS,
    POLICY_CURATED_1M_BARS,
    POLICY_CURATED_DAILY_BARS,
    POLICY_METADATA_ONLY,
    POLICY_RESEARCH_OUTPUTS,
    list_save_policies,
    resolve_save_policy,
)
from src.sessions.save_policy import SavePolicyDefinition


def test_list_save_policies_is_deterministic() -> None:
    assert list_save_policies() == tuple(sorted(list_save_policies()))
    assert {
        POLICY_METADATA_ONLY,
        POLICY_ARTIFACTS_AND_REPORTS,
        POLICY_RESEARCH_OUTPUTS,
        POLICY_CORPORATE_ACTIONS,
        POLICY_CURATED_DAILY_BARS,
        POLICY_CURATED_1M_BARS,
        POLICY_ALL_SELECTED,
    }.issubset(set(list_save_policies()))


def test_metadata_only_excludes_curated_data() -> None:
    policy = resolve_save_policy(POLICY_METADATA_ONLY)

    assert policy.include == ("artifacts/sessions", "configs")
    assert policy.exclude == ("data/curated",)
    assert policy.include_curated_data is False


def test_artifacts_and_reports_policy_includes_expected_roots() -> None:
    policy = resolve_save_policy(POLICY_ARTIFACTS_AND_REPORTS)

    assert policy.include == ("artifacts", "configs", "reports")
    assert policy.exclude == ("data/curated",)


def test_research_outputs_policy_includes_research_and_excludes_curated() -> None:
    policy = resolve_save_policy(POLICY_RESEARCH_OUTPUTS)

    assert policy.include == ("artifacts", "configs", "data/research", "reports")
    assert policy.exclude == ("data/curated",)


def test_corporate_actions_policy_selects_only_corporate_action_curated_path() -> None:
    policy = resolve_save_policy(POLICY_CORPORATE_ACTIONS, include_curated_data=True)

    assert "data/curated/corporate_actions" in policy.include
    assert "data/curated/bars_daily" not in policy.include
    assert "data/curated/bars_1m" not in policy.include


def test_curated_daily_bars_requires_curated_data_opt_in() -> None:
    with pytest.raises(ValueError, match="requires --include-curated-data"):
        resolve_save_policy(POLICY_CURATED_DAILY_BARS)


def test_curated_daily_bars_does_not_require_1m_opt_in() -> None:
    policy = resolve_save_policy(POLICY_CURATED_DAILY_BARS, include_curated_data=True)

    assert policy.include == ("data/curated/bars_daily",)
    assert "data/curated/bars_1m" in policy.exclude


def test_curated_1m_bars_requires_curated_data_opt_in() -> None:
    with pytest.raises(ValueError, match="requires --include-curated-data"):
        resolve_save_policy(POLICY_CURATED_1M_BARS, include_1m_data=True)


def test_curated_1m_bars_requires_1m_opt_in() -> None:
    with pytest.raises(ValueError, match="requires --include-1m-data"):
        resolve_save_policy(POLICY_CURATED_1M_BARS, include_curated_data=True)


def test_curated_1m_bars_resolves_with_both_opt_ins() -> None:
    policy = resolve_save_policy(
        POLICY_CURATED_1M_BARS,
        include_curated_data=True,
        include_1m_data=True,
    )

    assert policy.include == ("data/curated/bars_1m",)
    assert policy.exclude == ()
    assert policy.include_1m_data is True


def test_all_selected_requires_curated_opt_in_for_curated_paths() -> None:
    with pytest.raises(ValueError, match="Curated data paths require"):
        resolve_save_policy(POLICY_ALL_SELECTED, extra_include=("data/curated",))


def test_all_selected_requires_1m_opt_in_for_known_1m_paths() -> None:
    with pytest.raises(ValueError, match="1-minute curated data paths require"):
        resolve_save_policy(
            POLICY_ALL_SELECTED,
            include_curated_data=True,
            extra_include=("data/curated/bars_1m",),
        )


def test_resolved_include_and_exclude_roots_are_deterministic() -> None:
    policy = resolve_save_policy(
        POLICY_ALL_SELECTED,
        extra_include=("reports", "configs", "reports"),
        extra_exclude=("tmp", "artifacts/tmp", "tmp"),
    )

    assert policy.include == ("configs", "reports")
    assert policy.exclude == ("artifacts/tmp", "tmp")


def test_unsafe_policy_extra_paths_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not escape"):
        resolve_save_policy(POLICY_ALL_SELECTED, extra_include=("../reports",))


def test_policy_definition_paths_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.sessions import save_policy as save_policy_module

    monkeypatch.setitem(
        save_policy_module._POLICIES,
        "unsafe_policy",
        SavePolicyDefinition(
            name="unsafe_policy",
            include=("../reports",),
            exclude=(),
            description="invalid",
        ),
    )

    with pytest.raises(ValueError, match="must not escape"):
        resolve_save_policy("unsafe_policy")
