from pathlib import Path

import pandas as pd
import pytest

# Import from wherever this QA script/module lives.
# If it is currently a script file under src/qa/qa_export.py, import accordingly:
# from src.qa.qa_export import ExportConfig, Thresholds, generate_qa_exports
from src.ingestion.qa_export import ExportConfig, Thresholds, generate_qa_exports

from src.qa.qa_enforcer import build_metrics_from_dataframes, enforce_or_exit, Thresholds as EnforcerThresholds


def test_generate_qa_exports_flags_duplicates_and_ohlc(tmp_path: Path):
    # Build tiny deterministic dataset
    df = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "timeframe": ["1Min", "1Min", "1Min"],
            "ts_utc": pd.to_datetime(
                [
                    "2025-11-03 14:30:00+00:00",
                    "2025-11-03 14:30:00+00:00",  # duplicate key
                    "2025-11-03 14:31:00+00:00",
                ],
                utc=True,
            ),
            "open": [100.0, 100.0, 100.0],
            "high": [100.2, 100.2, 99.0],  # violation: high < open/close
            "low": [99.8, 99.8, 99.5],
            "close": [100.1, 100.1, 100.2],
            "volume": [10, 10, 10],
            "source": ["alpaca", "alpaca", "alpaca"],
        }
    )

    pq = tmp_path / "tiny.parquet"
    df.to_parquet(pq, index=False)

    cfg = ExportConfig(
        dataset_name="bars_1m",
        bar_interval="1Min",
        parquet_glob=str(pq),             # point directly at the temp parquet file
        start_ts=pd.Timestamp("2025-11-03", tz="UTC"),
        end_ts=pd.Timestamp("2025-11-04", tz="UTC"),
        calendar="XNYS",
        thresholds=Thresholds(
            min_coverage_pct=0.0,          # disable coverage complaints for this unit test
            max_duplicate_rows=0,
            max_duplicate_keys=0,
            max_ohlc_violations=0,
            max_gap_count_per_symbol=10**9,  # don't care about gaps here
        ),
        out_root=tmp_path,                # avoid writing into repo artifacts
        run_id="unit_test_run",
    )

    by_sym, glob, status = generate_qa_exports(cfg)

    # Per-symbol assertions
    row = by_sym.loc[by_sym["symbol"] == "AAPL"].iloc[0]
    assert int(row["duplicate_keys"]) == 1
    assert int(row["ohlc_violation_count"]) == 1

    # Global assertions
    g = glob.iloc[0]
    assert int(g["total_duplicate_keys"]) == 1
    assert int(g["total_ohlc_violation_count"]) == 1
    assert status == "FAIL"  # because max_* thresholds are 0

    # Optional: verify your enforcer fails in strict mode
    metrics = build_metrics_from_dataframes(by_symbol_df=by_sym, global_df=glob)
    enforcer_thr = EnforcerThresholds(max_duplicate_keys=0, max_ohlc_violations=0)

    with pytest.raises(SystemExit):
        enforce_or_exit(metrics, strict=True, thresholds=enforcer_thr)