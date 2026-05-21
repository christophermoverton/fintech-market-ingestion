from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from src.ingestion.corporate_actions_normalization import (
    NormalizedDividendRecord,
)
from src.ingestion.corporate_actions_storage import (
    DIVIDEND_DATASET_FILENAME,
    DIVIDEND_METADATA_FILENAME,
    DIVIDEND_RECORD_COLUMNS,
    read_dividend_corporate_actions,
    read_dividend_corporate_actions_metadata,
)
from src.ingestion.dividend_research_semantics import DEFAULT_DIVIDEND_EVENT_ANCHOR

DEFAULT_DIVIDEND_RESEARCH_MART_ROOT = Path("data/research/corporate_actions/dividends")
DIVIDEND_RESEARCH_MART_METADATA_FILENAME = "metadata.json"
DIVIDEND_RESEARCH_MART_PARTITION_COLUMNS = ["symbol", "year"]


@dataclass(frozen=True)
class DividendResearchMartResult:
    root_dir: Path
    metadata_path: Path
    input_record_count: int
    written_record_count: int
    invalid_partition_record_count: int
    metadata: dict[str, Any]


def write_dividend_research_mart(
    records_or_frame: Sequence[NormalizedDividendRecord | Mapping[str, Any]] | pd.DataFrame,
    root_dir: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    *,
    source_snapshot_path: Optional[Path | str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    event_anchor: str = DEFAULT_DIVIDEND_EVENT_ANCHOR,
) -> DividendResearchMartResult:
    if event_anchor != DEFAULT_DIVIDEND_EVENT_ANCHOR:
        raise ValueError(
            "Only ex_date is supported as the research mart event anchor in the current contract"
        )

    root = Path(root_dir)
    input_df = _coerce_input_to_dataframe(records_or_frame)
    input_record_count = len(input_df)
    prepared_df = _prepare_dataframe_for_research_mart(input_df)

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    prepared_df.to_parquet(
        root,
        index=False,
        partition_cols=DIVIDEND_RESEARCH_MART_PARTITION_COLUMNS,
    )

    metadata = _build_metadata(
        frame=prepared_df,
        root=root,
        source_snapshot_path=source_snapshot_path,
        start=start,
        end=end,
        input_record_count=input_record_count,
        event_anchor=event_anchor,
    )
    metadata_path = root / DIVIDEND_RESEARCH_MART_METADATA_FILENAME
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )

    return DividendResearchMartResult(
        root_dir=root,
        metadata_path=metadata_path,
        input_record_count=input_record_count,
        written_record_count=len(prepared_df),
        invalid_partition_record_count=0,
        metadata=metadata,
    )


def write_dividend_research_mart_from_snapshot(
    snapshot_root: Path | str,
    research_root: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
) -> DividendResearchMartResult:
    snapshot_root_path = Path(snapshot_root)
    snapshot_df = read_dividend_corporate_actions(snapshot_root_path)
    snapshot_metadata = read_dividend_corporate_actions_metadata(snapshot_root_path)
    snapshot_data_path = snapshot_root_path / DIVIDEND_DATASET_FILENAME

    return write_dividend_research_mart(
        snapshot_df,
        root_dir=research_root,
        source_snapshot_path=snapshot_data_path,
        start=snapshot_metadata.get("ingest_start_date"),
        end=snapshot_metadata.get("ingest_end_date"),
        event_anchor=DEFAULT_DIVIDEND_EVENT_ANCHOR,
    )


def read_dividend_research_mart(
    root_dir: Path | str = DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
) -> pd.DataFrame:
    root = Path(root_dir)
    if not root.exists():
        raise FileNotFoundError(f"Dividend research mart root does not exist: {root}")

    parquet_files = sorted(root.rglob("*.parquet"))
    if not parquet_files:
        raise FileNotFoundError(f"No parquet files found under dividend research mart root: {root}")

    df = pd.read_parquet([str(path) for path in parquet_files])
    if "year" not in df.columns or "symbol" not in df.columns:
        raise ValueError(
            "Dividend research mart dataset root read did not reconstruct required partition columns"
        )

    df["year"] = df["year"].astype(int)
    ordered = df.sort_values(
        by=[
            "symbol",
            "year",
            "ex_date",
            "process_date",
            "corporate_action_type",
            "corporate_action_id",
            "source_payload_hash",
        ],
        na_position="last",
    )
    return ordered.reset_index(drop=True)[DIVIDEND_RECORD_COLUMNS + ["year"]]


def _coerce_input_to_dataframe(
    records_or_frame: Sequence[NormalizedDividendRecord | Mapping[str, Any]] | pd.DataFrame,
) -> pd.DataFrame:
    if isinstance(records_or_frame, pd.DataFrame):
        frame = records_or_frame.copy(deep=True)
    else:
        rows = [_coerce_record_to_row(record) for record in records_or_frame]
        frame = pd.DataFrame(rows, columns=DIVIDEND_RECORD_COLUMNS)

    missing_columns = [col for col in DIVIDEND_RECORD_COLUMNS if col not in frame.columns]
    if missing_columns:
        raise ValueError(
            "Dividend research mart input is missing required canonical field(s): "
            f"{missing_columns}"
        )

    return frame[DIVIDEND_RECORD_COLUMNS].copy(deep=True)


def _coerce_record_to_row(
    record: NormalizedDividendRecord | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(record, NormalizedDividendRecord):
        row = record.as_dict()
    else:
        row = dict(record)

    if isinstance(row.get("raw"), Mapping):
        row["raw"] = json.dumps(
            row["raw"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        )
    return row


def _prepare_dataframe_for_research_mart(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy(deep=True)
    prepared["symbol"] = prepared["symbol"].map(_normalize_partition_symbol)
    ex_date_series = prepared["ex_date"].map(_parse_iso_date)

    invalid_mask = prepared["symbol"].isna() | ex_date_series.isna()
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        raise ValueError(
            "Dividend research mart write rejected due to missing required partition fields "
            f"(symbol/ex_date). invalid_record_count={invalid_count}"
        )

    prepared["year"] = ex_date_series.map(lambda value: value.year)
    prepared = prepared.sort_values(
        by=[
            "symbol",
            "year",
            "ex_date",
            "process_date",
            "corporate_action_type",
            "corporate_action_id",
            "source_payload_hash",
        ],
        na_position="last",
    )
    return prepared.reset_index(drop=True)


def _build_metadata(
    frame: pd.DataFrame,
    root: Path,
    source_snapshot_path: Optional[Path | str],
    start: Optional[str],
    end: Optional[str],
    input_record_count: int,
    event_anchor: str,
) -> dict[str, Any]:
    years = sorted(int(value) for value in frame["year"].unique().tolist())
    symbols = sorted(str(value) for value in frame["symbol"].unique().tolist())

    return {
        "dataset": "corporate_actions_dividends_research_mart",
        "dataset_role": "research_mart",
        "source_dataset_role": "deterministic_snapshot",
        "path": _relative_path_if_possible(root),
        "format": "parquet",
        "metadata_file": DIVIDEND_RESEARCH_MART_METADATA_FILENAME,
        "source_snapshot_path": _relative_path_if_possible(source_snapshot_path),
        "source_snapshot_metadata_file": DIVIDEND_METADATA_FILENAME,
        "partition_columns": DIVIDEND_RESEARCH_MART_PARTITION_COLUMNS,
        "event_anchor": event_anchor,
        "event_anchor_source": "normalized.ex_date",
        "ingest_start_date": start,
        "ingest_end_date": end,
        "input_record_count": input_record_count,
        "row_count": len(frame),
        "written_record_count": len(frame),
        "invalid_partition_record_count": 0,
        "symbol_count": len(symbols),
        "year_count": len(years),
        "symbols": symbols,
        "years": years,
        "schema_fields": DIVIDEND_RECORD_COLUMNS + ["year"],
        "created_by": "write_dividend_research_mart",
    }


def _normalize_partition_symbol(value: Any) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None


def _parse_iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _relative_path_if_possible(path: Optional[Path | str]) -> Optional[str]:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate).replace("\\", "/")

    cwd = Path.cwd()
    try:
        return str(candidate.relative_to(cwd)).replace("\\", "/")
    except ValueError:
        return str(candidate).replace("\\", "/")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
