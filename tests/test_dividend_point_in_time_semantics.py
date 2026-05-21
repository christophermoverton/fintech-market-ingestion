from dataclasses import FrozenInstanceError

from src.ingestion.dividend_research_semantics import (
    ADJUSTED_RETURN_NON_GOALS,
    DEFAULT_DIVIDEND_EVENT_ANCHOR,
    DIVIDEND_DATE_FIELD_SEMANTICS,
    DividendDateFieldSemantics,
    get_dividend_date_field_semantics,
)


def test_default_dividend_event_anchor_is_ex_date():
    assert DEFAULT_DIVIDEND_EVENT_ANCHOR == "ex_date"


def test_dividend_date_field_semantics_cover_expected_fields():
    assert list(DIVIDEND_DATE_FIELD_SEMANTICS) == [
        "declaration_date",
        "ex_date",
        "record_date",
        "payable_date",
        "process_date",
    ]
    assert DIVIDEND_DATE_FIELD_SEMANTICS["declaration_date"] == DividendDateFieldSemantics(
        purpose="company announcement date",
        research_caution="usable only once known",
    )
    assert DIVIDEND_DATE_FIELD_SEMANTICS["ex_date"] == DividendDateFieldSemantics(
        purpose="entitlement and common event-study anchor",
        research_caution="default anchor for price and bar event studies",
    )
    assert DIVIDEND_DATE_FIELD_SEMANTICS["record_date"] == DividendDateFieldSemantics(
        purpose="shareholder eligibility record date",
        research_caution="not usually the trading anchor",
    )
    assert DIVIDEND_DATE_FIELD_SEMANTICS["payable_date"] == DividendDateFieldSemantics(
        purpose="cash-flow payment timing",
        research_caution="not usually a price-event anchor",
    )
    assert DIVIDEND_DATE_FIELD_SEMANTICS["process_date"] == DividendDateFieldSemantics(
        purpose="ingestion and source as-of provenance",
        research_caution="not the corporate event date",
    )


def test_adjusted_return_non_goals_are_explicit():
    assert ADJUSTED_RETURN_NON_GOALS == (
        "adjusted_prices",
        "total_return_reconstruction",
        "dividend_reinvestment",
        "automatic_backtest_cash_flows",
    )


def test_semantics_helper_returns_a_copy_without_mutating_module_state():
    semantics = get_dividend_date_field_semantics()
    semantics["ex_date"] = DividendDateFieldSemantics(
        purpose="changed",
        research_caution="changed",
    )

    assert get_dividend_date_field_semantics()["ex_date"] == DividendDateFieldSemantics(
        purpose="entitlement and common event-study anchor",
        research_caution="default anchor for price and bar event studies",
    )


def test_semantics_dataclass_is_frozen():
    semantics = DIVIDEND_DATE_FIELD_SEMANTICS["ex_date"]

    try:
        semantics.purpose = "changed"  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("DividendDateFieldSemantics should be frozen")
