import pandas as pd
import pytest

from src.ingestion.dividend_event_window import (
    join_dividend_events_to_bars,
)


def sample_dividends() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "corporate_action_id": "ca-2",
                "symbol": "AAPL",
                "corporate_action_type": "cash_dividend",
                "ex_date": "2025-01-10",
                "declaration_date": "2025-01-02",
                "record_date": "2025-01-13",
                "payable_date": "2025-01-31",
                "process_date": "2025-01-15",
                "cash_amount": 0.25,
                "stock_amount": None,
                "currency": "USD",
                "source_payload_hash": "hash-2",
                "raw": "{}",
            },
            {
                "corporate_action_id": "ca-1",
                "symbol": "AAPL",
                "corporate_action_type": "cash_dividend",
                "ex_date": "2025-01-07",
                "declaration_date": "2025-01-01",
                "record_date": "2025-01-08",
                "payable_date": "2025-01-20",
                "process_date": "2025-01-09",
                "cash_amount": 0.2,
                "stock_amount": None,
                "currency": "USD",
                "source_payload_hash": "hash-1",
                "raw": "{}",
            },
        ]
    )


def sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-04T00:00:00Z",
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 100,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-05T00:00:00Z",
                "open": 10.1,
                "high": 11.1,
                "low": 9.1,
                "close": 10.6,
                "volume": 101,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-06T00:00:00Z",
                "open": 10.2,
                "high": 11.2,
                "low": 9.2,
                "close": 10.7,
                "volume": 102,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-07T00:00:00Z",
                "open": 10.3,
                "high": 11.3,
                "low": 9.3,
                "close": 10.8,
                "volume": 103,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-08T00:00:00Z",
                "open": 10.4,
                "high": 11.4,
                "low": 9.4,
                "close": 10.9,
                "volume": 104,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-09T00:00:00Z",
                "open": 10.5,
                "high": 11.5,
                "low": 9.5,
                "close": 11.0,
                "volume": 105,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-10T00:00:00Z",
                "open": 10.6,
                "high": 11.6,
                "low": 9.6,
                "close": 11.1,
                "volume": 106,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-11T00:00:00Z",
                "open": 10.7,
                "high": 11.7,
                "low": 9.7,
                "close": 11.2,
                "volume": 107,
                "timeframe": "1D",
            },
            {
                "symbol": "AAPL",
                "ts_utc": "2025-01-12T00:00:00Z",
                "open": 10.8,
                "high": 11.8,
                "low": 9.8,
                "close": 11.3,
                "volume": 108,
                "timeframe": "1D",
            },
            {
                "symbol": "MSFT",
                "ts_utc": "2025-01-10T00:00:00Z",
                "open": 20.0,
                "high": 21.0,
                "low": 19.0,
                "close": 20.5,
                "volume": 200,
                "timeframe": "1D",
            },
        ]
    )


def test_join_daily_bars_computes_event_day_offsets_and_preserves_fields():
    dividends = sample_dividends()
    bars = sample_bars()

    joined = join_dividend_events_to_bars(
        dividends,
        bars,
        pre_window_days=2,
        post_window_days=2,
    )

    aapl_second_event = joined[joined["event_corporate_action_id"] == "ca-2"]
    assert aapl_second_event["event_day_offset"].tolist() == [-2, -1, 0, 1, 2]
    assert (aapl_second_event["event_date_field"] == "ex_date").all()
    assert (aapl_second_event["bar_timeframe"] == "1D").all()
    assert "event_cash_amount" in joined.columns
    assert "event_stock_amount" in joined.columns
    assert "event_currency" in joined.columns
    assert "bar_open" in joined.columns
    assert "bar_high" in joined.columns
    assert "bar_low" in joined.columns
    assert "bar_close" in joined.columns
    assert "bar_volume" in joined.columns


def test_join_symbol_filter_applies_to_events_and_bars():
    dividends = pd.concat(
        [
            sample_dividends(),
            pd.DataFrame(
                [
                    {
                        "corporate_action_id": "ca-msft-1",
                        "symbol": "MSFT",
                        "corporate_action_type": "cash_dividend",
                        "ex_date": "2025-01-10",
                        "declaration_date": "2025-01-01",
                        "record_date": "2025-01-13",
                        "payable_date": "2025-01-20",
                        "process_date": "2025-01-12",
                        "cash_amount": 0.1,
                        "stock_amount": None,
                        "currency": "USD",
                        "source_payload_hash": "hash-msft",
                        "raw": "{}",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    bars = sample_bars()

    joined = join_dividend_events_to_bars(
        dividends, bars, symbol="MSFT", pre_window_days=0, post_window_days=0
    )

    assert joined["event_symbol"].unique().tolist() == ["MSFT"]
    assert joined["bar_symbol"].unique().tolist() == ["MSFT"]
    assert joined["event_corporate_action_id"].unique().tolist() == ["ca-msft-1"]


def test_join_respects_window_sizes():
    dividends = sample_dividends().iloc[[1]].copy()
    bars = sample_bars()

    joined = join_dividend_events_to_bars(dividends, bars, pre_window_days=1, post_window_days=0)

    assert joined["event_day_offset"].tolist() == [-1, 0]


def test_join_output_ordering_is_deterministic():
    dividends = sample_dividends().sample(frac=1.0, random_state=42).reset_index(drop=True)
    bars = sample_bars().sample(frac=1.0, random_state=99).reset_index(drop=True)

    joined = join_dividend_events_to_bars(dividends, bars, pre_window_days=1, post_window_days=1)

    ordering = joined[
        ["event_symbol", "event_date", "event_corporate_action_id", "bar_date"]
    ].values.tolist()
    assert ordering == sorted(ordering)


def test_join_missing_required_columns_raise_clear_errors():
    dividends = sample_dividends().drop(columns=["ex_date"])
    bars = sample_bars()

    with pytest.raises(ValueError, match="missing required column: ex_date"):
        join_dividend_events_to_bars(dividends, bars)

    with pytest.raises(ValueError, match="Unsupported event_date_field"):
        join_dividend_events_to_bars(sample_dividends(), bars, event_date_field="payable_date")

    with pytest.raises(ValueError, match="pre_window_days must be >= 0"):
        join_dividend_events_to_bars(sample_dividends(), bars, pre_window_days=-1)

    with pytest.raises(ValueError, match="post_window_days must be >= 0"):
        join_dividend_events_to_bars(sample_dividends(), bars, post_window_days=-1)

    with pytest.raises(ValueError, match="bars is missing required column: symbol"):
        join_dividend_events_to_bars(sample_dividends(), bars.drop(columns=["symbol"]))

    with pytest.raises(ValueError, match="bars is missing a date/timestamp column"):
        join_dividend_events_to_bars(sample_dividends(), bars.drop(columns=["ts_utc"]))


def test_join_empty_match_returns_deterministic_empty_frame():
    dividends = sample_dividends().assign(symbol="NVDA")
    bars = sample_bars().assign(symbol="AAPL")

    joined = join_dividend_events_to_bars(dividends, bars, pre_window_days=1, post_window_days=1)

    assert joined.empty
    assert joined.columns.tolist() == [
        "event_corporate_action_id",
        "event_symbol",
        "event_corporate_action_type",
        "event_ex_date",
        "event_declaration_date",
        "event_record_date",
        "event_payable_date",
        "event_process_date",
        "event_cash_amount",
        "event_stock_amount",
        "event_currency",
        "event_source_payload_hash",
        "event_date_field",
        "event_date",
        "event_day_offset",
        "bar_timeframe",
        "bar_symbol",
        "bar_ts",
        "bar_date",
        "bar_open",
        "bar_high",
        "bar_low",
        "bar_close",
        "bar_volume",
    ]


def test_join_does_not_mutate_input_dataframes():
    dividends = sample_dividends()
    bars = sample_bars()
    dividends_before = dividends.copy(deep=True)
    bars_before = bars.copy(deep=True)

    _ = join_dividend_events_to_bars(dividends, bars, pre_window_days=2, post_window_days=2)

    pd.testing.assert_frame_equal(dividends, dividends_before)
    pd.testing.assert_frame_equal(bars, bars_before)


def test_join_invalid_date_parsing_raises_error():
    dividends = sample_dividends().copy()
    dividends.loc[0, "ex_date"] = "not-a-date"

    with pytest.raises(ValueError, match=r"Invalid date value\(s\) in field ex_date"):
        join_dividend_events_to_bars(dividends, sample_bars())
