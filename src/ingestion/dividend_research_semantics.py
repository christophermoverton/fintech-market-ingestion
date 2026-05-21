from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DividendDateFieldSemantics:
    purpose: str
    research_caution: str


DEFAULT_DIVIDEND_EVENT_ANCHOR = "ex_date"

DIVIDEND_DATE_FIELD_SEMANTICS = {
    "declaration_date": DividendDateFieldSemantics(
        purpose="company announcement date",
        research_caution="usable only once known",
    ),
    "ex_date": DividendDateFieldSemantics(
        purpose="entitlement and common event-study anchor",
        research_caution="default anchor for price and bar event studies",
    ),
    "record_date": DividendDateFieldSemantics(
        purpose="shareholder eligibility record date",
        research_caution="not usually the trading anchor",
    ),
    "payable_date": DividendDateFieldSemantics(
        purpose="cash-flow payment timing",
        research_caution="not usually a price-event anchor",
    ),
    "process_date": DividendDateFieldSemantics(
        purpose="ingestion and source as-of provenance",
        research_caution="not the corporate event date",
    ),
}

ADJUSTED_RETURN_NON_GOALS = (
    "adjusted_prices",
    "total_return_reconstruction",
    "dividend_reinvestment",
    "automatic_backtest_cash_flows",
)


def get_dividend_date_field_semantics() -> dict[str, DividendDateFieldSemantics]:
    return dict(DIVIDEND_DATE_FIELD_SEMANTICS)
