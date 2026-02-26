import pandas as pd

from src.ingestion.normalize import normalize_bars

def test_normalize_bars_standardizes_schema_and_sorts():
    #unsorted timestamps, mixed casing, string numerics
    df = pd.DataFrame(
        {
            "timestamp": [
                "2025-11-03 14:31:00+00:00",
                "2025-11-03 14:30:00+00:00",
            ],
            "open": ["100.5", "100.0"],
            "high": ["101.0", "100.8"],
            "low": ["99.9", "99.7"],
            "close": ["100.7", "100.2"],
            "volume": ["10", "20"],

        }
    )
    
    out = normalize_bars(
        df=df,
        symbol="AAPL",
        source="alpaca",
        timeframe="1Min",
    )

    # Expected canonical columns exist
    expected_cols = {
        "symbol",
        "ts_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "timeframe",
    }
    
    assert expected_cols.issubset(set(out.columns))
    
    #Symbol, source, timeframe injectedf
    assert (out["symbol"] == "AAPL").all()
    assert (out["source"] == "alpaca").all()
    assert (out["timeframe"] == "1Min").all()
    
    # Numeric dtype conversion
    assert pd.api.types.is_numeric_dtype(out["open"])
    assert pd.api.types.is_numeric_dtype(out["high"])
    assert pd.api.types.is_numeric_dtype(out["low"])
    assert pd.api.types.is_numeric_dtype(out["close"])

    # Sorted by timestamp
    assert out.loc[0, "ts_utc"] < out.loc[1, "ts_utc"]

    # Timestamps timezone-aware UTC
    assert out["ts_utc"].dt.tz is not None

test_normalize_bars_standardizes_schema_and_sorts()