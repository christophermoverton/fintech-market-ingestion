from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ingestion.corporate_actions_normalization import (  # noqa: E402
    normalize_corporate_action_payload,
)
from src.ingestion.corporate_actions_research_mart import (  # noqa: E402
    inspect_dividend_research_mart,
    read_dividend_research_mart,
    validate_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (  # noqa: E402
    write_dividend_corporate_actions,
)
from src.ingestion.dividend_event_window import (  # noqa: E402
    join_dividend_events_to_bars_result,
    write_dividend_event_window_output,
)

DEFAULT_PIPELINE_OUTPUT_ROOT = Path("artifacts/examples/dividend_research_pipeline_workflow")
STAGE_ORDER = [
    "create_synthetic_dividend_snapshot",
    "build_research_mart",
    "validate_research_mart",
    "create_synthetic_daily_bars",
    "join_event_windows",
    "write_event_window_output",
]


@dataclass(frozen=True)
class WorkflowContext:
    output_root: Path
    snapshot_root: Path
    research_root: Path
    bars_path: Path
    event_window_output_root: Path
    summary_path: Path


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    rows: int | None
    outputs: dict[str, str]
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "rows": self.rows,
            "outputs": self.outputs,
            "metadata": self.metadata,
        }


def build_workflow_context(
    output_root: Path | str = DEFAULT_PIPELINE_OUTPUT_ROOT,
) -> WorkflowContext:
    root = Path(output_root)
    return WorkflowContext(
        output_root=root,
        snapshot_root=root / "data" / "curated" / "corporate_actions" / "dividends",
        research_root=root / "data" / "research" / "corporate_actions" / "dividends",
        bars_path=root / "data" / "local" / "daily_bars.parquet",
        event_window_output_root=(
            root / "data" / "research" / "corporate_actions" / "dividend_event_windows" / "pipeline"
        ),
        summary_path=root / "workflow_summary.json",
    )


def run_pipeline_workflow(
    output_root: Path | str = DEFAULT_PIPELINE_OUTPUT_ROOT,
) -> dict[str, Any]:
    context = build_workflow_context(output_root)
    stage_results = [
        create_synthetic_dividend_snapshot(context),
        build_research_mart(context),
        validate_research_mart(context),
        create_synthetic_daily_bars(context),
        join_event_windows(context),
        write_event_window_output(context),
    ]
    return write_workflow_summary(context, stage_results)


def create_synthetic_dividend_snapshot(context: WorkflowContext) -> StageResult:
    records = [
        normalize_corporate_action_payload(payload, source="synthetic_pipeline")
        for payload in _synthetic_dividend_payloads()
    ]
    result = write_dividend_corporate_actions(
        records,
        root_dir=context.snapshot_root,
        ingest_start_date="2024-01-01",
        ingest_end_date="2024-12-31",
        source="synthetic_pipeline",
        action_types=["cash_dividend", "stock_dividend"],
    )
    return StageResult(
        name="create_synthetic_dividend_snapshot",
        status="completed",
        rows=result.written_record_count,
        outputs={
            "data_path": _path_text(result.data_path),
            "metadata_path": _path_text(result.metadata_path),
            "snapshot_root": _path_text(result.root_dir),
        },
        metadata={
            "input_record_count": result.input_record_count,
            "written_record_count": result.written_record_count,
            "duplicate_record_count": result.duplicate_record_count,
        },
    )


def build_research_mart(context: WorkflowContext) -> StageResult:
    result = write_dividend_research_mart_from_snapshot(
        snapshot_root=context.snapshot_root,
        research_root=context.research_root,
    )
    return StageResult(
        name="build_research_mart",
        status="completed",
        rows=result.written_record_count,
        outputs={
            "metadata_path": _path_text(result.metadata_path),
            "research_root": _path_text(result.root_dir),
        },
        metadata={
            "input_record_count": result.input_record_count,
            "written_record_count": result.written_record_count,
            "invalid_partition_record_count": result.invalid_partition_record_count,
        },
    )


def validate_research_mart(context: WorkflowContext) -> StageResult:
    validation = validate_dividend_research_mart(context.research_root)
    inspection = inspect_dividend_research_mart(context.research_root)
    return StageResult(
        name="validate_research_mart",
        status="completed",
        rows=inspection.row_count,
        outputs={
            "metadata_path": inspection.metadata_path,
            "research_root": inspection.research_root,
        },
        metadata={
            "valid": validation.valid,
            "error_count": len(validation.errors),
            "warning_count": len(validation.warnings),
            "symbol_count": inspection.symbol_count,
            "year_count": inspection.year_count,
            "symbols": inspection.symbols,
            "years": inspection.years,
        },
    )


def create_synthetic_daily_bars(context: WorkflowContext) -> StageResult:
    bars = _synthetic_daily_bars()
    context.bars_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(context.bars_path, index=False)
    return StageResult(
        name="create_synthetic_daily_bars",
        status="completed",
        rows=len(bars),
        outputs={"bars_path": _path_text(context.bars_path)},
        metadata={
            "symbols": sorted(str(value) for value in bars["symbol"].unique().tolist()),
            "timeframe": "1D",
        },
    )


def join_event_windows(context: WorkflowContext) -> StageResult:
    result = _join_result(context)
    return StageResult(
        name="join_event_windows",
        status="completed",
        rows=result.joined_row_count,
        outputs={},
        metadata={
            "event_count": result.event_count,
            "bar_count": result.bar_count,
            "joined_row_count": result.joined_row_count,
            "pre_window_days": 1,
            "post_window_days": 1,
            "bar_timeframe": "1D",
        },
    )


def write_event_window_output(context: WorkflowContext) -> StageResult:
    join_result = _join_result(context)
    output_result = write_dividend_event_window_output(
        join_result,
        output_root=context.event_window_output_root,
        source_dividend_path=context.research_root,
        source_bar_path=context.bars_path,
        pre_window_days=1,
        post_window_days=1,
        bar_timeframe="1D",
    )
    return StageResult(
        name="write_event_window_output",
        status="completed",
        rows=output_result.row_count,
        outputs={
            "data_path": _path_text(output_result.data_path),
            "metadata_path": _path_text(output_result.metadata_path),
            "output_root": _path_text(output_result.root_dir),
        },
        metadata={
            "dataset_role": output_result.metadata["dataset_role"],
            "joined_row_count": output_result.metadata["joined_row_count"],
        },
    )


def write_workflow_summary(
    context: WorkflowContext,
    stage_results: list[StageResult],
) -> dict[str, Any]:
    validation_stage = _stage_by_name(stage_results, "validate_research_mart")
    snapshot_stage = _stage_by_name(stage_results, "create_synthetic_dividend_snapshot")
    mart_stage = _stage_by_name(stage_results, "build_research_mart")
    bars_stage = _stage_by_name(stage_results, "create_synthetic_daily_bars")
    join_stage = _stage_by_name(stage_results, "join_event_windows")
    output_stage = _stage_by_name(stage_results, "write_event_window_output")

    summary = {
        "output_root": _path_text(context.output_root),
        "stage_order": [stage.name for stage in stage_results],
        "stage_status_values": {stage.name: stage.status for stage in stage_results},
        "stage_results": [stage.as_dict() for stage in stage_results],
        "generated_paths": {
            "snapshot_root": _path_text(context.snapshot_root),
            "research_root": _path_text(context.research_root),
            "bars_path": _path_text(context.bars_path),
            "event_window_output_root": _path_text(context.event_window_output_root),
            "workflow_summary_path": _path_text(context.summary_path),
        },
        "validation_valid": validation_stage.metadata["valid"],
        "dividend_record_count": snapshot_stage.rows,
        "research_mart_row_count": mart_stage.rows,
        "event_count": join_stage.metadata["event_count"],
        "bar_count": bars_stage.rows,
        "joined_row_count": join_stage.metadata["joined_row_count"],
        "symbols": validation_stage.metadata["symbols"],
        "years": validation_stage.metadata["years"],
        "event_window_metadata_path": output_stage.outputs["metadata_path"],
        "event_window_data_path": output_stage.outputs["data_path"],
        "no_live_credentials_required": True,
        "scheduler_dependencies": [],
    }
    context.summary_path.parent.mkdir(parents=True, exist_ok=True)
    context.summary_path.write_text(_format_summary_json(summary), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a scheduler-free synthetic dividend research pipeline workflow "
            "using local public APIs."
        )
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_PIPELINE_OUTPUT_ROOT),
        help="Output root for all generated pipeline workflow artifacts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_pipeline_workflow(args.output_root)
    print(_format_summary_json(summary), end="")
    return 0


def _join_result(context: WorkflowContext):
    dividends = read_dividend_research_mart(context.research_root)
    bars = pd.read_parquet(context.bars_path)
    return join_dividend_events_to_bars_result(
        dividends,
        bars,
        pre_window_days=1,
        post_window_days=1,
        bar_timeframe="1D",
    )


def _synthetic_dividend_payloads() -> list[dict[str, Any]]:
    return [
        {
            "id": "pipeline-cash-dividend-aapl-2024-02",
            "symbol": "AAPL",
            "type": "cash_dividend",
            "process_date": "2024-02-15",
            "declaration_date": "2024-02-01",
            "ex_date": "2024-02-09",
            "record_date": "2024-02-12",
            "payable_date": "2024-02-29",
            "cash_amount": "0.24",
            "stock_amount": None,
            "currency": "USD",
        },
        {
            "id": "pipeline-stock-dividend-msft-2024-03",
            "symbol": "MSFT",
            "type": "stock_dividend",
            "process_date": "2024-03-15",
            "declaration_date": "2024-03-01",
            "ex_date": "2024-03-08",
            "record_date": "2024-03-11",
            "payable_date": "2024-03-29",
            "cash_amount": None,
            "stock_amount": "0.05",
            "currency": None,
        },
    ]


def _synthetic_daily_bars() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol, base_date, base_price in [
        ("AAPL", pd.Timestamp("2024-02-09"), 185.0),
        ("MSFT", pd.Timestamp("2024-03-08"), 410.0),
    ]:
        for offset in [-1, 0, 1]:
            bar_date = base_date + pd.Timedelta(days=offset)
            open_price = base_price + offset
            rows.append(
                {
                    "symbol": symbol,
                    "ts_utc": bar_date.strftime("%Y-%m-%dT00:00:00Z"),
                    "open": open_price,
                    "high": open_price + 1.25,
                    "low": open_price - 1.0,
                    "close": open_price + 0.5,
                    "volume": 1_000_000 + (offset + 1) * 10_000,
                    "timeframe": "1D",
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "ts_utc"]).reset_index(drop=True)


def _stage_by_name(stage_results: list[StageResult], name: str) -> StageResult:
    for stage in stage_results:
        if stage.name == name:
            return stage
    raise KeyError(f"Missing stage result: {name}")


def _format_summary_json(summary: dict[str, Any]) -> str:
    return (
        json.dumps(
            summary,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
            allow_nan=False,
        )
        + "\n"
    )


def _path_text(path: Path | str) -> str:
    return str(Path(path)).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
