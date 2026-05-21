import json
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.dividend_event_window import (
    DIVIDEND_EVENT_WINDOW_DATASET_FILENAME,
    DIVIDEND_EVENT_WINDOW_DATASET_ROLE,
    DIVIDEND_EVENT_WINDOW_METADATA_FILENAME,
    join_dividend_events_to_bars,
    join_dividend_events_to_bars_result,
    read_dividend_event_window_output,
    write_dividend_event_window_output,
)


def sample_dividends() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "corporate_action_id": "ca-1",
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
                "source_payload_hash": "hash-1",
                "raw": "{}",
            }
        ]
    )


def sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "ts_utc": f"2025-01-{day:02d}T00:00:00Z",
                "open": 10.0 + day,
                "high": 11.0 + day,
                "low": 9.0 + day,
                "close": 10.5 + day,
                "volume": 100 + day,
            }
            for day in range(9, 12)
        ]
    )


@pytest.fixture
def event_window_result():
    return join_dividend_events_to_bars_result(
        sample_dividends(),
        sample_bars(),
        pre_window_days=1,
        post_window_days=1,
    )


def read_metadata(root):
    return json.loads((root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).read_text(encoding="utf-8"))


def test_event_window_output_writer_persists_parquet_and_metadata(event_window_result, tmp_path):
    root = tmp_path / "data" / "research" / "event_windows" / "run-1"

    result = write_dividend_event_window_output(event_window_result, output_root=root)

    assert result.data_path == root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME
    assert result.metadata_path == root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME
    assert result.data_path.exists()
    assert result.metadata_path.exists()
    assert len(pd.read_parquet(result.data_path)) == event_window_result.joined_row_count


def test_event_window_output_metadata_contains_required_contract_fields(
    event_window_result, tmp_path
):
    root = tmp_path / "data" / "research" / "event_windows" / "run-1"
    dividend_path = tmp_path / "data" / "research" / "dividends"
    bar_path = tmp_path / "bars" / "bars.parquet"

    result = write_dividend_event_window_output(
        event_window_result,
        output_root=root,
        source_dividend_path=dividend_path,
        source_bar_path=bar_path,
        pre_window_days=1,
        post_window_days=1,
        symbol_filter="AAPL",
    )
    metadata = result.metadata

    assert metadata["dataset"] == "corporate_actions_dividend_event_windows"
    assert metadata["dataset_role"] == DIVIDEND_EVENT_WINDOW_DATASET_ROLE
    assert metadata["source_dividend_path"].endswith("data/research/dividends")
    assert metadata["source_bar_path"].endswith("bars/bars.parquet")
    assert metadata["event_anchor"] == "ex_date"
    assert metadata["pre_window_days"] == 1
    assert metadata["post_window_days"] == 1
    assert metadata["bar_timeframe"] == "1D"
    assert metadata["symbol_filter"] == "AAPL"
    assert metadata["event_count"] == event_window_result.event_count
    assert metadata["bar_count"] == event_window_result.bar_count
    assert metadata["joined_row_count"] == event_window_result.joined_row_count
    assert metadata["row_count"] == event_window_result.joined_row_count
    assert metadata["data_file"] == DIVIDEND_EVENT_WINDOW_DATASET_FILENAME
    assert metadata["metadata_file"] == DIVIDEND_EVENT_WINDOW_METADATA_FILENAME
    assert metadata["format"] == "parquet"
    assert metadata["schema_fields"] == event_window_result.frame.columns.tolist()
    assert metadata["created_by"] == "write_dividend_event_window_output"


def test_event_window_output_metadata_is_deterministic(event_window_result, tmp_path):
    root = tmp_path / "data" / "research" / "event_windows" / "run-1"

    write_dividend_event_window_output(event_window_result, output_root=root)
    metadata_text = (root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME).read_text(encoding="utf-8")

    assert (
        metadata_text
        == json.dumps(json.loads(metadata_text), sort_keys=True, indent=2, separators=(",", ": "))
        + "\n"
    )


def test_event_window_output_repeated_writes_are_deterministic(event_window_result, tmp_path):
    root = tmp_path / "data" / "research" / "event_windows" / "run-1"

    first = write_dividend_event_window_output(event_window_result, output_root=root)
    first_metadata = first.metadata_path.read_bytes()
    first_data = first.data_path.read_bytes()
    second = write_dividend_event_window_output(event_window_result, output_root=root)

    assert second.metadata_path.read_bytes() == first_metadata
    assert second.data_path.read_bytes() == first_data


def test_read_dividend_event_window_output_roundtrip(event_window_result, tmp_path):
    root = tmp_path / "data" / "research" / "event_windows" / "run-1"

    write_dividend_event_window_output(event_window_result, output_root=root)
    loaded = read_dividend_event_window_output(root)

    pd.testing.assert_frame_equal(loaded, event_window_result.frame)


def test_event_window_output_writer_rejects_curated_output_root(event_window_result, tmp_path):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=tmp_path / "data" / "curated" / "event_windows",
        )


def test_event_window_output_writer_rejects_canonical_path_part(event_window_result, tmp_path):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=tmp_path / "data" / "canonical" / "event_windows",
        )


def test_event_window_output_writer_rejects_source_dividend_overlap(event_window_result, tmp_path):
    source_dividend_path = tmp_path / "data" / "research" / "dividends"

    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=source_dividend_path / "event_windows",
            source_dividend_path=source_dividend_path,
        )


def test_event_window_output_writer_rejects_source_bar_overlap(event_window_result, tmp_path):
    source_bar_path = tmp_path / "bars" / "bars.parquet"

    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=source_bar_path,
            source_bar_path=source_bar_path,
        )


def test_event_window_output_writer_rejects_default_dividend_research_mart_overlap_without_source_path(
    event_window_result,
):
    with pytest.raises(ValueError, match="derived research path.*research mart"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=Path("data/research/corporate_actions/dividends/run-1"),
        )


def test_event_window_output_writer_allows_default_event_window_output_root(
    event_window_result, tmp_path
):
    output_root = (
        tmp_path / "data" / "research" / "corporate_actions" / "dividend_event_windows" / "run-1"
    )

    result = write_dividend_event_window_output(
        event_window_result,
        output_root=output_root,
    )

    assert result.data_path == output_root / DIVIDEND_EVENT_WINDOW_DATASET_FILENAME
    assert result.metadata_path == output_root / DIVIDEND_EVENT_WINDOW_METADATA_FILENAME
    assert result.data_path.exists()
    assert result.metadata_path.exists()


def test_join_dividend_events_to_bars_result_still_returns_frame_without_writing():
    result = join_dividend_events_to_bars_result(
        sample_dividends(),
        sample_bars(),
        pre_window_days=1,
        post_window_days=1,
    )

    assert result.joined_row_count == 3
    assert result.frame.equals(
        join_dividend_events_to_bars(
            sample_dividends(), sample_bars(), pre_window_days=1, post_window_days=1
        )
    )


def test_event_window_output_writer_does_not_mutate_source_inputs(event_window_result, tmp_path):
    frame_before = event_window_result.frame.copy(deep=True)

    write_dividend_event_window_output(
        event_window_result,
        output_root=tmp_path / "data" / "research" / "event_windows" / "run-1",
    )

    pd.testing.assert_frame_equal(event_window_result.frame, frame_before)


def test_event_window_output_writer_rejects_existing_file_output_root(
    event_window_result, tmp_path
):
    existing_file = tmp_path / "not_a_directory.txt"
    existing_file.write_text("some content", encoding="utf-8")

    with pytest.raises(ValueError, match="output root.*directory path"):
        write_dividend_event_window_output(
            event_window_result,
            output_root=existing_file,
        )

    assert existing_file.exists()
    assert existing_file.read_text(encoding="utf-8") == "some content"


def test_event_window_output_writer_requires_no_live_credentials(
    monkeypatch, event_window_result, tmp_path
):
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    result = write_dividend_event_window_output(
        event_window_result,
        output_root=tmp_path / "data" / "research" / "event_windows" / "run-1",
    )

    assert result.row_count == event_window_result.joined_row_count
