import pytest

from src.ingestion.alpaca_corporate_actions_client import CorporateActionRecord
from src.ingestion.corporate_actions_normalization import (
    NormalizedDividendRecord,
    hash_source_payload,
    normalize_corporate_action_payload,
    normalize_corporate_action_record,
    normalize_corporate_action_records,
)


def cash_dividend_payload(**overrides):
    payload = {
        "id": "ca-cash-1",
        "symbol": "AAPL",
        "type": "cash_dividend",
        "process_date": "2025-01-15",
        "declaration_date": "2025-01-02",
        "ex_date": "2025-01-10",
        "record_date": "2025-01-13",
        "payable_date": "2025-01-31",
        "cash_amount": "0.25",
        "stock_amount": None,
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


def stock_dividend_payload(**overrides):
    payload = {
        "id": "ca-stock-1",
        "symbol": "MSFT",
        "type": "stock_dividend",
        "process_date": "2025-02-15",
        "declaration_date": "2025-02-01",
        "ex_date": "2025-02-10",
        "record_date": "2025-02-12",
        "payable_date": "2025-02-28",
        "cash_amount": None,
        "stock_amount": "0.05",
        "currency": None,
    }
    payload.update(overrides)
    return payload


def test_cash_dividend_normalization_from_raw_dictionary():
    payload = cash_dividend_payload()

    record = normalize_corporate_action_payload(payload)

    assert isinstance(record, NormalizedDividendRecord)
    assert record.corporate_action_id == "ca-cash-1"
    assert record.symbol == "AAPL"
    assert record.corporate_action_type == "cash_dividend"
    assert record.source == "alpaca"
    assert record.process_date == "2025-01-15"
    assert record.declaration_date == "2025-01-02"
    assert record.ex_date == "2025-01-10"
    assert record.record_date == "2025-01-13"
    assert record.payable_date == "2025-01-31"
    assert record.cash_amount == 0.25
    assert record.stock_amount is None
    assert record.currency == "USD"
    assert record.source_payload_hash == hash_source_payload(payload)
    assert record.raw == payload


def test_cash_dividend_cash_amount_falls_back_to_rate():
    payload = cash_dividend_payload(
        id="aapl-dividend-2024-02",
        ex_date="2024-02-09",
        record_date="2024-02-12",
        payable_date="2024-02-15",
        process_date="2024-02-15",
        rate=0.24,
        cash_amount=None,
    )

    record = normalize_corporate_action_payload(payload)

    assert record.cash_amount == 0.24
    assert record.raw["rate"] == 0.24
    assert record.source_payload_hash == hash_source_payload(payload)


def test_cash_dividend_cash_amount_takes_precedence_over_rate():
    payload = cash_dividend_payload(cash_amount="0.26", rate=0.24)

    record = normalize_corporate_action_payload(payload)

    assert record.cash_amount == 0.26


def test_stock_dividend_normalization_from_raw_dictionary():
    payload = stock_dividend_payload()

    record = normalize_corporate_action_payload(payload)

    assert record.corporate_action_id == "ca-stock-1"
    assert record.symbol == "MSFT"
    assert record.corporate_action_type == "stock_dividend"
    assert record.cash_amount is None
    assert record.stock_amount == 0.05
    assert record.currency is None


def test_cash_dividend_missing_currency_defaults_to_usd_without_mutating_raw_payload():
    payload = cash_dividend_payload(currency=None)

    record = normalize_corporate_action_payload(payload)

    assert record.currency == "USD"
    assert record.raw["currency"] is None
    assert record.source_payload_hash == hash_source_payload(payload)


def test_cash_dividend_provided_currency_is_preserved():
    payload = cash_dividend_payload(currency="CAD")

    record = normalize_corporate_action_payload(payload)

    assert record.currency == "CAD"
    assert record.raw["currency"] == "CAD"


def test_nested_response_context_and_raw_payload_are_preserved():
    payload = cash_dividend_payload(
        currency=None,
        _alpaca_dividend_response_key="cash_dividends",
        _alpaca_nested_response=True,
        _alpaca_original_payload={"id": "ca-cash-1", "symbol": "AAPL"},
    )

    record = normalize_corporate_action_payload(payload)

    assert record.corporate_action_type == "cash_dividend"
    assert record.raw == payload
    assert record.raw["_alpaca_dividend_response_key"] == "cash_dividends"
    assert record.raw["_alpaca_original_payload"] == {"id": "ca-cash-1", "symbol": "AAPL"}
    assert record.source_payload_hash == hash_source_payload(payload)


def test_normalization_from_corporate_action_record():
    payload = cash_dividend_payload(id="ca-record-1")
    source_record = CorporateActionRecord.from_payload(payload)

    record = normalize_corporate_action_record(source_record, source="alpaca_corporate_actions")

    assert record.corporate_action_id == "ca-record-1"
    assert record.symbol == "AAPL"
    assert record.source == "alpaca_corporate_actions"
    assert record.raw == payload


def test_multiple_record_normalization_uses_deterministic_ordering():
    records = [
        stock_dividend_payload(symbol="MSFT", ex_date="2025-01-03", id="ca-3"),
        cash_dividend_payload(symbol="AAPL", ex_date="2025-01-10", id="ca-2"),
        cash_dividend_payload(symbol="AAPL", ex_date="2025-01-05", id="ca-1"),
        cash_dividend_payload(symbol="AAPL", ex_date=None, process_date="2025-01-04", id="ca-0"),
    ]

    normalized = normalize_corporate_action_records(records)

    assert [record.corporate_action_id for record in normalized] == ["ca-0", "ca-1", "ca-2", "ca-3"]


def test_missing_optional_date_fields_are_nullable():
    payload = cash_dividend_payload(
        declaration_date=None,
        record_date=None,
        payable_date=None,
    )

    record = normalize_corporate_action_payload(payload)

    assert record.declaration_date is None
    assert record.record_date is None
    assert record.payable_date is None


def test_missing_optional_amount_fields_are_nullable():
    cash_record = normalize_corporate_action_payload(cash_dividend_payload(stock_amount=None))
    stock_record = normalize_corporate_action_payload(stock_dividend_payload(cash_amount=None))

    assert cash_record.stock_amount is None
    assert stock_record.cash_amount is None


def test_unsupported_corporate_action_type_fails_fast():
    payload = cash_dividend_payload(type="forward_split")

    with pytest.raises(ValueError, match="Unsupported dividend corporate action type"):
        normalize_corporate_action_payload(payload)


def test_missing_symbol_fails_fast():
    payload = cash_dividend_payload(symbol=" ")

    with pytest.raises(ValueError, match="Missing required symbol"):
        normalize_corporate_action_payload(payload)


def test_missing_corporate_action_id_fails_fast():
    payload = cash_dividend_payload(id="")

    with pytest.raises(ValueError, match="Missing required corporate action ID"):
        normalize_corporate_action_payload(payload)


def test_missing_or_blank_corporate_action_type_fails_fast():
    payload = cash_dividend_payload(type=" ")

    with pytest.raises(ValueError, match="Missing required corporate action type"):
        normalize_corporate_action_payload(payload)


def test_malformed_date_field_fails_fast():
    payload = cash_dividend_payload(ex_date="2025-99-99")

    with pytest.raises(ValueError, match="Malformed date field ex_date"):
        normalize_corporate_action_payload(payload)


def test_deterministic_source_payload_hash_uses_stable_json():
    left = {"symbol": "AAPL", "id": "ca-1", "type": "cash_dividend"}
    right = {"type": "cash_dividend", "id": "ca-1", "symbol": "AAPL"}

    assert hash_source_payload(left) == hash_source_payload(right)
    assert hash_source_payload(left) != hash_source_payload({**left, "cash_amount": 0.25})


def test_duplicate_records_are_preserved_for_later_persistence_layer():
    payload = cash_dividend_payload(id="ca-dupe-1")

    normalized = normalize_corporate_action_records([payload, payload])

    assert [record.corporate_action_id for record in normalized] == ["ca-dupe-1", "ca-dupe-1"]
