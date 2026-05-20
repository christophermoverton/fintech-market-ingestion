from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from src.ingestion.corporate_actions_normalization import (
    CURRENCY_POLICY,
    NormalizedDividendRecord,
    corporate_action_sort_key,
)

DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT = Path("data/curated/corporate_actions/dividends")
DIVIDEND_DATASET_FILENAME = "dividends.parquet"
DIVIDEND_METADATA_FILENAME = "metadata.json"
DIVIDEND_RECORD_COLUMNS = [
    "corporate_action_id",
    "symbol",
    "corporate_action_type",
    "source",
    "process_date",
    "declaration_date",
    "ex_date",
    "record_date",
    "payable_date",
    "cash_amount",
    "stock_amount",
    "currency",
    "source_payload_hash",
    "raw",
]
DIVIDEND_EVENT_KEY_COLUMNS = [
    "corporate_action_id",
    "symbol",
    "corporate_action_type",
    "ex_date",
    "process_date",
]


@dataclass(frozen=True)
class DividendCorporateActionsWriteResult:
    root_dir: Path
    data_path: Path
    metadata_path: Path
    input_record_count: int
    written_record_count: int
    duplicate_record_count: int
    metadata: dict[str, Any]


def write_dividend_corporate_actions(
    records: Sequence[NormalizedDividendRecord | Mapping[str, Any]],
    root_dir: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    ingest_start_date: Optional[str] = None,
    ingest_end_date: Optional[str] = None,
    source: Optional[str] = None,
    action_types: Optional[Sequence[str]] = None,
) -> DividendCorporateActionsWriteResult:
    """Write normalized dividend corporate actions to a deterministic curated dataset.

    The M3.3 persistence policy is overwrite-by-window: each call rewrites the
    deterministic Parquet file and metadata file under the corporate-actions
    dividends root. Duplicate input rows are collapsed by the stable dividend
    event key before writing.
    """
    root = Path(root_dir)
    root.mkdir(parents=True, exist_ok=True)

    normalized_records = _coerce_records(records)
    input_record_count = len(normalized_records)
    deduped_records = _deduplicate_records(normalized_records)
    ordered_records = sorted(deduped_records, key=corporate_action_sort_key)

    data_path = root / DIVIDEND_DATASET_FILENAME
    metadata_path = root / DIVIDEND_METADATA_FILENAME
    df = _records_to_dataframe(ordered_records)
    df.to_parquet(data_path, index=False)

    metadata = _build_metadata(
        records=ordered_records,
        input_record_count=input_record_count,
        ingest_start_date=ingest_start_date,
        ingest_end_date=ingest_end_date,
        source=source,
        action_types=action_types,
    )
    metadata_path.write_text(
        json.dumps(metadata, sort_keys=True, indent=2, separators=(",", ": ")) + "\n",
        encoding="utf-8",
    )

    return DividendCorporateActionsWriteResult(
        root_dir=root,
        data_path=data_path,
        metadata_path=metadata_path,
        input_record_count=input_record_count,
        written_record_count=len(ordered_records),
        duplicate_record_count=input_record_count - len(ordered_records),
        metadata=metadata,
    )


def read_dividend_corporate_actions(
    root_dir: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
) -> pd.DataFrame:
    """Read the persisted normalized dividend corporate-actions dataset."""
    data_path = Path(root_dir) / DIVIDEND_DATASET_FILENAME
    if not data_path.exists():
        return pd.DataFrame(columns=DIVIDEND_RECORD_COLUMNS)
    df = pd.read_parquet(data_path)
    return df[DIVIDEND_RECORD_COLUMNS]


def read_dividend_corporate_actions_metadata(
    root_dir: Path | str = DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
) -> dict[str, Any]:
    metadata_path = Path(root_dir) / DIVIDEND_METADATA_FILENAME
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def dividend_event_key(
    record: NormalizedDividendRecord,
) -> tuple[str, str, str, Optional[str], Optional[str]]:
    return (
        record.corporate_action_id,
        record.symbol,
        record.corporate_action_type,
        record.ex_date,
        record.process_date,
    )


def _coerce_records(
    records: Sequence[NormalizedDividendRecord | Mapping[str, Any]],
) -> list[NormalizedDividendRecord]:
    return [_coerce_record(record) for record in records]


def _coerce_record(
    record: NormalizedDividendRecord | Mapping[str, Any],
) -> NormalizedDividendRecord:
    if isinstance(record, NormalizedDividendRecord):
        return record
    return NormalizedDividendRecord(**dict(record))


def _deduplicate_records(
    records: Sequence[NormalizedDividendRecord],
) -> list[NormalizedDividendRecord]:
    by_key: dict[tuple[str, str, str, Optional[str], Optional[str]], NormalizedDividendRecord] = {}
    for record in sorted(
        records,
        key=lambda item: (*corporate_action_sort_key(item), item.source_payload_hash),
    ):
        by_key[dividend_event_key(record)] = record
    return list(by_key.values())


def _records_to_dataframe(records: Sequence[NormalizedDividendRecord]) -> pd.DataFrame:
    rows = []
    for record in records:
        row = record.as_dict()
        row["raw"] = json.dumps(
            row["raw"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=_json_default,
        )
        rows.append(row)
    return pd.DataFrame(rows, columns=DIVIDEND_RECORD_COLUMNS)


def _build_metadata(
    records: Sequence[NormalizedDividendRecord],
    input_record_count: int,
    ingest_start_date: Optional[str],
    ingest_end_date: Optional[str],
    source: Optional[str],
    action_types: Optional[Sequence[str]],
) -> dict[str, Any]:
    inferred_sources = sorted({record.source for record in records})
    inferred_action_types = sorted({record.corporate_action_type for record in records})
    requested_action_types = (
        sorted(action_types) if action_types is not None else inferred_action_types
    )
    metadata_source = source or (inferred_sources[0] if len(inferred_sources) == 1 else None)
    duplicate_count = input_record_count - len(records)
    currency_missing_for_cash_dividend_count = sum(
        1
        for record in records
        if record.corporate_action_type == "cash_dividend" and _raw_currency_missing(record.raw)
    )
    nested_cash_dividend_count = sum(
        1
        for record in records
        if record.corporate_action_type == "cash_dividend"
        and record.raw.get("_alpaca_dividend_response_key") == "cash_dividends"
    )
    nested_stock_dividend_count = sum(
        1
        for record in records
        if record.corporate_action_type == "stock_dividend"
        and record.raw.get("_alpaca_dividend_response_key") == "stock_dividends"
    )

    return {
        "dataset": "corporate_actions_dividends",
        "path": str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT).replace("\\", "/"),
        "format": "parquet",
        "data_file": DIVIDEND_DATASET_FILENAME,
        "source": metadata_source,
        "sources": inferred_sources,
        "ingest_start_date": ingest_start_date,
        "ingest_end_date": ingest_end_date,
        "action_types": requested_action_types,
        "record_count": input_record_count,
        "written_record_count": len(records),
        "duplicate_record_count": duplicate_count,
        "duplicate_handling": "deduplicate_by_event_key_keep_highest_payload_hash",
        "event_key": DIVIDEND_EVENT_KEY_COLUMNS,
        "currency_policy": CURRENCY_POLICY,
        "currency_missing_for_cash_dividend_count": currency_missing_for_cash_dividend_count,
        "currency_defaulted_for_cash_dividend_count": currency_missing_for_cash_dividend_count,
        "nested_response_detected": nested_cash_dividend_count > 0
        or nested_stock_dividend_count > 0,
        "nested_cash_dividend_count": nested_cash_dividend_count,
        "nested_stock_dividend_count": nested_stock_dividend_count,
    }


def _raw_currency_missing(raw: Mapping[str, Any]) -> bool:
    value = raw.get("currency")
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
