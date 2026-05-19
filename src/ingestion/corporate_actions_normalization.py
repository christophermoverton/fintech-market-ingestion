from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Mapping, Optional, Sequence

from src.ingestion.alpaca_corporate_actions_client import (
    SUPPORTED_DIVIDEND_ACTION_TYPES,
    CorporateActionRecord,
)


@dataclass(frozen=True)
class NormalizedDividendRecord:
    """Normalized dividend corporate-action event ready for later persistence."""

    corporate_action_id: str
    symbol: str
    corporate_action_type: str
    source: str
    process_date: Optional[str]
    declaration_date: Optional[str]
    ex_date: Optional[str]
    record_date: Optional[str]
    payable_date: Optional[str]
    cash_amount: Optional[float]
    stock_amount: Optional[float]
    currency: Optional[str]
    source_payload_hash: str
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "corporate_action_id": self.corporate_action_id,
            "symbol": self.symbol,
            "corporate_action_type": self.corporate_action_type,
            "source": self.source,
            "process_date": self.process_date,
            "declaration_date": self.declaration_date,
            "ex_date": self.ex_date,
            "record_date": self.record_date,
            "payable_date": self.payable_date,
            "cash_amount": self.cash_amount,
            "stock_amount": self.stock_amount,
            "currency": self.currency,
            "source_payload_hash": self.source_payload_hash,
            "raw": dict(self.raw),
        }


def hash_source_payload(payload: Mapping[str, Any]) -> str:
    """Hash a source payload with stable JSON encoding."""
    payload_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def normalize_corporate_action_payload(
    payload: Mapping[str, Any],
    source: str = "alpaca",
) -> NormalizedDividendRecord:
    """Normalize a raw Alpaca dividend corporate-action payload."""
    raw = dict(payload)
    corporate_action_id = _required_string(raw, "id", display_name="corporate action ID")
    symbol = _required_string(raw, "symbol")
    corporate_action_type = _required_string(raw, "type", display_name="corporate action type")
    _validate_supported_type(corporate_action_type)

    return NormalizedDividendRecord(
        corporate_action_id=corporate_action_id,
        symbol=symbol,
        corporate_action_type=corporate_action_type,
        source=_normalize_source(source),
        process_date=_optional_date(raw, "process_date"),
        declaration_date=_optional_date(raw, "declaration_date"),
        ex_date=_optional_date(raw, "ex_date"),
        record_date=_optional_date(raw, "record_date"),
        payable_date=_optional_date(raw, "payable_date"),
        cash_amount=_optional_float(raw, "cash_amount"),
        stock_amount=_optional_float(raw, "stock_amount"),
        currency=_optional_string(raw, "currency"),
        source_payload_hash=hash_source_payload(raw),
        raw=raw,
    )


def normalize_corporate_action_record(
    record: CorporateActionRecord | Mapping[str, Any],
    source: str = "alpaca",
) -> NormalizedDividendRecord:
    """Normalize either a client CorporateActionRecord or a raw payload mapping."""
    if isinstance(record, CorporateActionRecord):
        return normalize_corporate_action_payload(record.as_dict(), source=source)
    return normalize_corporate_action_payload(record, source=source)


def normalize_corporate_action_records(
    records: Sequence[CorporateActionRecord | Mapping[str, Any]],
    source: str = "alpaca",
) -> List[NormalizedDividendRecord]:
    """Normalize and deterministically order dividend corporate-action records.

    M3.2 preserves duplicate source records. Deduplication, if needed, belongs with
    the persistence/upsert behavior in a later milestone.
    """
    normalized = [normalize_corporate_action_record(record, source=source) for record in records]
    return sorted(normalized, key=corporate_action_sort_key)


def corporate_action_sort_key(record: NormalizedDividendRecord) -> tuple[str, str, str, str]:
    event_date = record.ex_date or record.process_date or ""
    return (
        record.symbol,
        event_date,
        record.corporate_action_type,
        record.corporate_action_id,
    )


def _required_string(
    payload: Mapping[str, Any],
    field: str,
    display_name: Optional[str] = None,
) -> str:
    value = payload.get(field)
    if value is None:
        raise ValueError(f"Missing required {display_name or field}")
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"Missing required {display_name or field}")
    return normalized


def _optional_string(payload: Mapping[str, Any], field: str) -> Optional[str]:
    value = payload.get(field)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_date(payload: Mapping[str, Any], field: str) -> Optional[str]:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    normalized = str(value).strip()
    if not normalized:
        return None

    try:
        return date.fromisoformat(normalized).isoformat()
    except ValueError as e:
        raise ValueError(f"Malformed date field {field}: {value!r}") from e


def _optional_float(payload: Mapping[str, Any], field: str) -> Optional[float]:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Malformed numeric field {field}: {value!r}") from e


def _validate_supported_type(corporate_action_type: str) -> None:
    if corporate_action_type not in SUPPORTED_DIVIDEND_ACTION_TYPES:
        supported = ", ".join(sorted(SUPPORTED_DIVIDEND_ACTION_TYPES))
        raise ValueError(
            f"Unsupported dividend corporate action type: {corporate_action_type}. Supported: {supported}"
        )


def _normalize_source(source: str) -> str:
    normalized = str(source).strip()
    if not normalized:
        raise ValueError("source is required")
    return normalized


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
