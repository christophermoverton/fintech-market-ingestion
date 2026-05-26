"""Deterministic save-policy resolution and curated-data guardrails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.sessions.session_paths import normalize_workspace_relative_path

POLICY_METADATA_ONLY = "metadata_only"
POLICY_ARTIFACTS_AND_REPORTS = "artifacts_and_reports"
POLICY_RESEARCH_OUTPUTS = "research_outputs"
POLICY_CORPORATE_ACTIONS = "corporate_actions"
POLICY_CURATED_DAILY_BARS = "curated_daily_bars"
POLICY_CURATED_1M_BARS = "curated_1m_bars"
POLICY_ALL_SELECTED = "all_selected"

DEFAULT_CURATED_EXCLUDE = "data/curated"
KNOWN_1M_CURATED_PATHS = (
    "data/curated/1m",
    "data/curated/bars_1m",
    "data/curated/features_1m",
)


@dataclass(frozen=True)
class SavePolicyDefinition:
    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    description: str
    requires_curated_data: bool = False
    requires_1m_data: bool = False
    safety_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedSavePolicy:
    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    include_curated_data: bool
    include_1m_data: bool
    safety_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "include_curated_data": self.include_curated_data,
            "include_1m_data": self.include_1m_data,
            "resolved_include": list(self.include),
            "resolved_exclude": list(self.exclude),
            "safety_warnings": list(self.safety_warnings),
        }


_POLICIES: dict[str, SavePolicyDefinition] = {
    POLICY_METADATA_ONLY: SavePolicyDefinition(
        name=POLICY_METADATA_ONLY,
        include=("artifacts/sessions", "configs"),
        exclude=(DEFAULT_CURATED_EXCLUDE,),
        description="Session metadata and lightweight configuration only.",
    ),
    POLICY_ARTIFACTS_AND_REPORTS: SavePolicyDefinition(
        name=POLICY_ARTIFACTS_AND_REPORTS,
        include=("artifacts", "configs", "reports"),
        exclude=(DEFAULT_CURATED_EXCLUDE,),
        description="Artifacts, reports, and configs without curated datasets.",
    ),
    POLICY_RESEARCH_OUTPUTS: SavePolicyDefinition(
        name=POLICY_RESEARCH_OUTPUTS,
        include=("artifacts", "configs", "data/research", "reports"),
        exclude=(DEFAULT_CURATED_EXCLUDE,),
        description="Derived research outputs plus artifacts, reports, and configs.",
    ),
    POLICY_CORPORATE_ACTIONS: SavePolicyDefinition(
        name=POLICY_CORPORATE_ACTIONS,
        include=("artifacts", "configs", "data/curated/corporate_actions", "reports"),
        exclude=(),
        description="Curated corporate-action outputs without broad OHLCV bars.",
        requires_curated_data=True,
        safety_warnings=("Includes curated corporate-action data only.",),
    ),
    POLICY_CURATED_DAILY_BARS: SavePolicyDefinition(
        name=POLICY_CURATED_DAILY_BARS,
        include=("data/curated/bars_daily",),
        exclude=(),
        description="Curated daily bar dataset only.",
        requires_curated_data=True,
        safety_warnings=("Includes curated daily OHLCV bars.",),
    ),
    POLICY_CURATED_1M_BARS: SavePolicyDefinition(
        name=POLICY_CURATED_1M_BARS,
        include=("data/curated/bars_1m",),
        exclude=(),
        description="Curated 1-minute bar dataset only.",
        requires_curated_data=True,
        requires_1m_data=True,
        safety_warnings=("Includes curated 1-minute bars, which can be large.",),
    ),
    POLICY_ALL_SELECTED: SavePolicyDefinition(
        name=POLICY_ALL_SELECTED,
        include=(),
        exclude=(DEFAULT_CURATED_EXCLUDE,),
        description="Honor explicit include paths with curated-data guardrails.",
    ),
}


def list_save_policies() -> tuple[str, ...]:
    return tuple(sorted(_POLICIES))


def resolve_save_policy(
    policy_name: str = POLICY_ALL_SELECTED,
    *,
    include_curated_data: bool = False,
    include_1m_data: bool = False,
    extra_include: Sequence[str] = (),
    extra_exclude: Sequence[str] | None = None,
) -> ResolvedSavePolicy:
    if policy_name not in _POLICIES:
        supported = ", ".join(list_save_policies())
        raise ValueError(f"Unsupported save policy: {policy_name}. Supported: {supported}")

    definition = _validate_definition(_POLICIES[policy_name])
    normalized_extra_include = _normalize_paths(extra_include, "include")
    normalized_extra_exclude = (
        None if extra_exclude is None else _normalize_paths(extra_exclude, "exclude")
    )
    include = _sorted_unique((*definition.include, *normalized_extra_include))

    if definition.requires_curated_data and not include_curated_data:
        raise ValueError(f"Save policy {policy_name} requires --include-curated-data")
    if definition.requires_1m_data and not include_1m_data:
        raise ValueError(f"Save policy {policy_name} requires --include-1m-data")
    if _selects_curated_path(normalized_extra_include) and not include_curated_data:
        raise ValueError("Curated data paths require --include-curated-data")
    if _selects_known_1m_path(include) and not include_1m_data:
        raise ValueError("Known 1-minute curated data paths require --include-1m-data")

    if normalized_extra_exclude is not None:
        exclude = normalized_extra_exclude
    elif include_curated_data:
        exclude = ()
    else:
        exclude = definition.exclude or (DEFAULT_CURATED_EXCLUDE,)

    if include_curated_data and not include_1m_data:
        exclude = _sorted_unique((*exclude, *KNOWN_1M_CURATED_PATHS))

    return ResolvedSavePolicy(
        name=definition.name,
        include=include,
        exclude=exclude,
        include_curated_data=include_curated_data,
        include_1m_data=include_1m_data,
        safety_warnings=definition.safety_warnings,
    )


def _validate_definition(definition: SavePolicyDefinition) -> SavePolicyDefinition:
    for path in (*definition.include, *definition.exclude):
        normalize_workspace_relative_path(path, field_name=f"save_policy.{definition.name}")
    return definition


def _normalize_paths(paths: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(paths, str):
        raise ValueError(f"{field_name} must be a sequence of workspace-relative paths")
    return _sorted_unique(
        normalize_workspace_relative_path(path, field_name=f"{field_name}[]") for path in paths
    )


def _sorted_unique(paths: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(paths)))


def _selects_curated_path(paths: Sequence[str]) -> bool:
    return any(
        path == DEFAULT_CURATED_EXCLUDE or path.startswith(f"{DEFAULT_CURATED_EXCLUDE}/")
        for path in paths
    )


def _selects_known_1m_path(paths: Sequence[str]) -> bool:
    return any(
        path == known_path or path.startswith(f"{known_path}/")
        for path in paths
        for known_path in KNOWN_1M_CURATED_PATHS
    )
