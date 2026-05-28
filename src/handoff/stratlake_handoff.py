"""Build deterministic StratLake handoff reports from local curated datasets."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from src.sessions.session_paths import workspace_relative_path

HANDOFF_REPORT_SCHEMA_VERSION = 1
HANDOFF_REPORT_TYPE = "stratlake_marketlake_handoff"
DEFAULT_OUTPUT_PATH = "artifacts/handoff/stratlake_marketlake_handoff.json"

_DATASET_TIMEFRAMES: dict[str, str | None] = {
    "bars_daily": "1D",
    "bars_1m": "1Min",
    "corporate_actions": None,
}
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_stratlake_handoff_report(
    *,
    root: Path | str,
    curated_root: Path | str,
    qa_root: Path | str | None = "artifacts/qa",
    include_row_counts: bool = False,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    workspace_root = Path(root).expanduser().resolve(strict=False)
    curated_runtime_root = _resolve_under_root(workspace_root, curated_root)
    if not curated_runtime_root.exists() or not curated_runtime_root.is_dir():
        raise FileNotFoundError(f"Curated root does not exist: {curated_runtime_root}")

    curated_root_rel = workspace_relative_path(workspace_root, curated_runtime_root)

    datasets: dict[str, dict[str, Any]] = {}
    all_symbols: set[str] = set()
    all_dates: list[str] = []
    timeframe_values: set[str] = set()

    for dataset_name in sorted(_DATASET_TIMEFRAMES):
        dataset_runtime_path = curated_runtime_root / dataset_name
        if not dataset_runtime_path.exists() or not dataset_runtime_path.is_dir():
            continue

        summary = _summarize_dataset(
            workspace_root=workspace_root,
            dataset_name=dataset_name,
            dataset_runtime_path=dataset_runtime_path,
            curated_root_rel=curated_root_rel,
            timeframe=_DATASET_TIMEFRAMES[dataset_name],
            include_row_counts=include_row_counts,
        )
        datasets[dataset_name] = summary
        all_symbols.update(summary["symbols"])
        if summary["date_min"] is not None:
            all_dates.append(summary["date_min"])
        if summary["date_max"] is not None:
            all_dates.append(summary["date_max"])
        if summary["timeframe"] is not None:
            timeframe_values.add(str(summary["timeframe"]))

    qa_summary = _summarize_qa(
        workspace_root=workspace_root,
        qa_root=qa_root,
    )

    date_min, date_max = _min_max_dates(all_dates)

    return {
        "schema_version": HANDOFF_REPORT_SCHEMA_VERSION,
        "report_type": HANDOFF_REPORT_TYPE,
        # Default None keeps report JSON deterministic for unchanged filesystem inputs.
        "generated_at_utc": generated_at_utc,
        "non_canonical": True,
        "curated_root": curated_root_rel,
        "curated_root_runtime_path": curated_runtime_root.as_posix(),
        "stratlake_marketlake_root": curated_root_rel,
        "available_datasets": sorted(datasets.keys()),
        "timeframes": sorted(timeframe_values),
        "symbols": sorted(all_symbols),
        "date_min": date_min,
        "date_max": date_max,
        "datasets": datasets,
        "qa": qa_summary,
        "notes": [
            "This report is derived and non-canonical.",
            "Use stratlake_marketlake_root as StratLake MARKETLAKE_ROOT or --marketlake-root.",
            "StratLake should still validate its requested universe/date/timeframe.",
        ],
    }


def write_stratlake_handoff_report(
    report: dict[str, Any],
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_stratlake_handoff_report_json(report), encoding="utf-8")
    return path


def dumps_stratlake_handoff_report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, sort_keys=True, indent=2, separators=(",", ": ")) + "\n"


def _summarize_dataset(
    *,
    workspace_root: Path,
    dataset_name: str,
    dataset_runtime_path: Path,
    curated_root_rel: str,
    timeframe: str | None,
    include_row_counts: bool,
) -> dict[str, Any]:
    parquet_files = list(_iter_parquet_files(dataset_runtime_path))

    symbol_values: set[str] = set()
    date_values: set[str] = set()
    for parquet_file in parquet_files:
        rel = parquet_file.relative_to(dataset_runtime_path)
        symbol = _partition_value(rel, "symbol")
        if symbol:
            symbol_values.add(symbol)

        partition_date = _partition_value(rel, "date")
        if partition_date and _DATE_PATTERN.match(partition_date):
            date_values.add(partition_date)

    date_min, date_max = _min_max_dates(sorted(date_values))
    row_count = _dataset_row_count(dataset_runtime_path) if include_row_counts else None

    dataset_rel_path = _relative_child_path(curated_root_rel, dataset_name)
    return {
        "dataset_path": dataset_rel_path,
        "dataset_runtime_path": dataset_runtime_path.as_posix(),
        "timeframe": timeframe,
        "symbols": sorted(symbol_values),
        "date_min": date_min,
        "date_max": date_max,
        "file_count": len(parquet_files),
        "row_count": row_count,
    }


def _summarize_qa(
    *,
    workspace_root: Path,
    qa_root: Path | str | None,
) -> dict[str, Any]:
    if qa_root is None:
        return {
            "status": "unknown",
            "qa_root": None,
            "qa_root_runtime_path": None,
            "latest_run_id": None,
            "latest_run_path": None,
            "latest_run_runtime_path": None,
            "artifacts": [],
        }

    qa_runtime_root = _resolve_under_root(workspace_root, qa_root)
    qa_root_rel = workspace_relative_path(workspace_root, qa_runtime_root)

    if not qa_runtime_root.exists() or not qa_runtime_root.is_dir():
        return {
            "status": "unknown",
            "qa_root": qa_root_rel,
            "qa_root_runtime_path": qa_runtime_root.as_posix(),
            "latest_run_id": None,
            "latest_run_path": None,
            "latest_run_runtime_path": None,
            "artifacts": [],
        }

    # "Latest" is selected by deterministic lexical directory ordering.
    run_dirs = sorted(path for path in qa_runtime_root.iterdir() if path.is_dir() and not _is_hidden(path))
    if not run_dirs:
        return {
            "status": "unknown",
            "qa_root": qa_root_rel,
            "qa_root_runtime_path": qa_runtime_root.as_posix(),
            "latest_run_id": None,
            "latest_run_path": None,
            "latest_run_runtime_path": None,
            "artifacts": [],
        }

    latest_run = run_dirs[-1]
    artifact_names = sorted(path.name for path in latest_run.iterdir() if path.is_file())
    status = _derive_qa_status(latest_run)

    return {
        "status": status,
        "qa_root": qa_root_rel,
        "qa_root_runtime_path": qa_runtime_root.as_posix(),
        "latest_run_id": latest_run.name,
        "latest_run_path": workspace_relative_path(workspace_root, latest_run),
        "latest_run_runtime_path": latest_run.as_posix(),
        "artifacts": artifact_names,
    }


def _derive_qa_status(latest_run: Path) -> str:
    global_summary = latest_run / "qa_summary_global.csv"
    if not global_summary.exists():
        return "available"

    try:
        summary_df = pd.read_csv(global_summary)
    except Exception:
        return "available"

    if summary_df.empty or "overall_status" not in summary_df.columns:
        return "available"

    raw_status = str(summary_df["overall_status"].iloc[0]).strip().upper()
    if raw_status == "PASS":
        return "passed"
    if raw_status == "FAIL":
        return "failed"
    if raw_status in {"WARN", "WARNING"}:
        return "warning"
    return "available"


def _dataset_row_count(dataset_runtime_path: Path) -> int | None:
    try:
        import duckdb
    except Exception:
        return None

    glob_path = str(dataset_runtime_path / "**" / "*.parquet").replace("\\", "/")
    if "'" in glob_path:
        glob_path = glob_path.replace("'", "''")

    con = duckdb.connect(database=":memory:")
    try:
        result = con.execute(f"SELECT COUNT(*) AS row_count FROM read_parquet('{glob_path}')").fetchone()
    except Exception:
        return None
    finally:
        con.close()

    if result is None:
        return None
    return int(result[0])


def _iter_parquet_files(dataset_runtime_path: Path):
    for path in sorted(dataset_runtime_path.rglob("*.parquet")):
        if not path.is_file():
            continue
        if any(part.startswith(".") for part in path.relative_to(dataset_runtime_path).parts):
            continue
        yield path


def _partition_value(path: Path, key: str) -> str | None:
    prefix = f"{key}="
    for part in path.parts:
        if part.startswith(prefix):
            value = part[len(prefix) :].strip()
            return value or None
    return None


def _min_max_dates(values: list[str]) -> tuple[str | None, str | None]:
    if not values:
        return None, None
    sorted_values = sorted(values)
    return sorted_values[0], sorted_values[-1]


def _relative_child_path(base: str, child: str) -> str:
    if base.endswith("/"):
        return f"{base}{child}"
    return f"{base}/{child}"


def _resolve_under_root(workspace_root: Path, path: Path | str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    candidate = candidate.resolve(strict=False)
    workspace_relative_path(workspace_root, candidate)
    return candidate


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)
