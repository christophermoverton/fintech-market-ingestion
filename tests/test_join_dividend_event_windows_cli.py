from pathlib import Path

import pandas as pd
import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from src.cli import join_dividend_event_windows as cli
from src.ingestion.corporate_actions_normalization import normalize_corporate_action_payload
from src.ingestion.corporate_actions_research_mart import (
    DEFAULT_DIVIDEND_RESEARCH_MART_ROOT,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.corporate_actions_storage import (
    DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT,
    read_dividend_corporate_actions,
    write_dividend_corporate_actions,
)
from src.ingestion.dividend_event_window import join_dividend_events_to_bars_result


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
        "process_date": "2025-01-15",
        "declaration_date": "2025-01-02",
        "ex_date": "2025-01-10",
        "record_date": "2025-01-13",
        "payable_date": "2025-01-31",
        "cash_amount": None,
        "stock_amount": "0.05",
        "currency": None,
    }
    payload.update(overrides)
    return payload


def normalized(payload):
    return normalize_corporate_action_payload(payload)


def sample_bars():
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
                "timeframe": "1D",
            }
            for day in range(8, 13)
        ]
        + [
            {
                "symbol": "MSFT",
                "ts_utc": "2025-01-10T00:00:00Z",
                "open": 20.0,
                "high": 21.0,
                "low": 19.0,
                "close": 20.5,
                "volume": 200,
                "timeframe": "1D",
            }
        ]
    )


@pytest.fixture
def dividend_snapshot(tmp_path):
    snapshot_root = tmp_path / "data" / "curated" / "corporate_actions" / "dividends"
    write_dividend_corporate_actions(
        [
            normalized(cash_dividend_payload(id="ca-aapl-1", symbol="aapl")),
            normalized(stock_dividend_payload(id="ca-msft-1", symbol="MSFT")),
        ],
        root_dir=snapshot_root,
        ingest_start_date="2025-01-01",
        ingest_end_date="2025-01-31",
        source="alpaca",
        action_types=["cash_dividend", "stock_dividend"],
    )
    return snapshot_root


@pytest.fixture
def research_mart(dividend_snapshot, tmp_path):
    research_root = tmp_path / "data" / "research" / "corporate_actions" / "dividends"
    write_dividend_research_mart_from_snapshot(dividend_snapshot, research_root)
    return research_root


@pytest.fixture
def bars_parquet_path(tmp_path):
    path = tmp_path / "bars" / "daily_bars.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_bars().to_parquet(path, index=False)
    return path


@pytest.fixture
def bars_csv_path(tmp_path):
    path = tmp_path / "bars" / "daily_bars.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_bars().to_csv(path, index=False)
    return path


def file_bytes(path):
    return path.read_bytes()


def tree_file_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_parser_defaults_and_argument_parsing(tmp_path):
    parser = cli.build_parser()
    bars_path = tmp_path / "bars.parquet"

    args = parser.parse_args(
        [
            "--dividend-source",
            "research-mart",
            "--bars-path",
            str(bars_path),
            "--pre-window-days",
            "2",
            "--post-window-days",
            "3",
            "--symbol",
            "AAPL",
            "--bar-date-field",
            "ts_utc",
            "--bar-timeframe",
            "1D",
        ]
    )

    assert args.dividend_source == "research-mart"
    assert args.snapshot_root == str(DEFAULT_DIVIDEND_CORPORATE_ACTIONS_ROOT)
    assert args.research_root == str(DEFAULT_DIVIDEND_RESEARCH_MART_ROOT)
    assert args.bars_path == str(bars_path)
    assert args.pre_window_days == 2
    assert args.post_window_days == 3
    assert args.symbol == "AAPL"
    assert args.bar_date_field == "ts_utc"
    assert args.bar_timeframe == "1D"


def test_snapshot_source_cli_join_with_synthetic_local_bars(dividend_snapshot, bars_parquet_path):
    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
    )

    assert summary["dividend_source"] == "snapshot"
    assert summary["snapshot_root"] == str(dividend_snapshot)
    assert summary["research_root"] is None
    assert summary["event_count"] == 2
    assert summary["bar_count"] == 6
    assert summary["joined_row_count"] == 4


def test_research_mart_source_cli_join_with_synthetic_local_bars(research_mart, bars_parquet_path):
    summary = cli.join_dividend_event_windows(
        dividend_source="research-mart",
        research_root=research_mart,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
    )

    assert summary["dividend_source"] == "research-mart"
    assert summary["snapshot_root"] is None
    assert summary["research_root"] == str(research_mart)
    assert summary["joined_row_count"] == 4


def test_parquet_bars_input(dividend_snapshot, bars_parquet_path):
    loaded = cli.load_bars(bars_parquet_path)

    assert loaded["symbol"].tolist() == sample_bars()["symbol"].tolist()


def test_csv_bars_input(dividend_snapshot, bars_csv_path):
    loaded = cli.load_bars(bars_csv_path)

    assert loaded["symbol"].tolist() == sample_bars()["symbol"].tolist()


def test_output_writing_to_parquet(dividend_snapshot, bars_parquet_path, tmp_path):
    output_path = tmp_path / "data" / "research" / "event_windows" / "joined.parquet"

    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        output_path=output_path,
    )
    loaded = pd.read_parquet(output_path)

    assert summary["output_format"] == "parquet"
    assert len(loaded) == summary["joined_row_count"]


def test_output_writing_to_csv(dividend_snapshot, bars_parquet_path, tmp_path):
    output_path = tmp_path / "data" / "research" / "event_windows" / "joined.csv"

    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        output_path=output_path,
    )
    loaded = pd.read_csv(output_path)

    assert summary["output_format"] == "csv"
    assert len(loaded) == summary["joined_row_count"]


def test_event_window_output_safety_allows_safe_research_output_path(
    dividend_snapshot, research_mart, bars_parquet_path, tmp_path
):
    output_path = (
        tmp_path
        / "data"
        / "research"
        / "corporate_actions"
        / "dividend_event_windows"
        / "joined.parquet"
    )

    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        research_root=research_mart,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        output_path=output_path,
    )

    assert summary["output_path"] == str(output_path)
    assert summary["joined_row_count"] == 4
    assert output_path.exists()


def test_summary_output_writes_same_deterministic_json(
    dividend_snapshot, bars_parquet_path, tmp_path, capsys
):
    summary_output = tmp_path / "summary.json"

    exit_code = cli.main(
        [
            "--dividend-source",
            "snapshot",
            "--snapshot-root",
            str(dividend_snapshot),
            "--bars-path",
            str(bars_parquet_path),
            "--pre-window-days",
            "1",
            "--post-window-days",
            "1",
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert stdout == summary_output.read_text(encoding="utf-8")
    assert stdout.endswith("\n")


def test_join_cli_writes_contract_output_with_metadata(
    dividend_snapshot, research_mart, bars_parquet_path, tmp_path
):
    output_root = tmp_path / "data" / "research" / "event_windows" / "run-1"

    summary = cli.join_dividend_event_windows(
        dividend_source="research-mart",
        snapshot_root=dividend_snapshot,
        research_root=research_mart,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        output_root=output_root,
    )
    metadata = pd.read_json(output_root / "metadata.json", typ="series").to_dict()
    loaded = pd.read_parquet(output_root / "event_windows.parquet")

    assert summary["output_root"] == str(output_root)
    assert summary["output_path"] is None
    assert summary["output_format"] == "parquet"
    assert summary["metadata_path"] == str(output_root / "metadata.json")
    assert summary["data_path"] == str(output_root / "event_windows.parquet")
    assert summary["dataset_role"] == "derived_research_event_window"
    assert metadata["source_dividend_path"].endswith("data/research/corporate_actions/dividends")
    assert metadata["source_bar_path"].endswith("bars/daily_bars.parquet")
    assert len(loaded) == summary["joined_row_count"]


def test_join_cli_rejects_output_path_and_output_root_together(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    with pytest.raises(ValueError, match="--output-path and --output-root cannot be used together"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=tmp_path / "data" / "research" / "joined.parquet",
            output_root=tmp_path / "data" / "research" / "event_windows" / "run-1",
        )


def test_summary_output_parent_directories_are_created(
    dividend_snapshot, bars_parquet_path, tmp_path, capsys
):
    summary_output = tmp_path / "nested" / "summaries" / "summary.json"

    cli.main(
        [
            "--dividend-source",
            "snapshot",
            "--snapshot-root",
            str(dividend_snapshot),
            "--bars-path",
            str(bars_parquet_path),
            "--summary-output",
            str(summary_output),
        ]
    )
    stdout = capsys.readouterr().out

    assert summary_output.exists()
    assert summary_output.read_text(encoding="utf-8") == stdout


def test_optional_symbol_filter_is_applied_to_events_and_bars(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    output_path = tmp_path / "data" / "research" / "event_windows" / "aapl.parquet"

    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        symbol="AAPL",
        output_path=output_path,
    )
    loaded = pd.read_parquet(output_path)

    assert summary["event_count"] == 1
    assert summary["bar_count"] == 5
    assert summary["joined_row_count"] == 3
    assert loaded["event_symbol"].unique().tolist() == ["AAPL"]
    assert loaded["bar_symbol"].unique().tolist() == ["AAPL"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pre_window_days": -1}, "pre_window_days must be >= 0"),
        ({"post_window_days": -1}, "post_window_days must be >= 0"),
    ],
)
def test_negative_window_validation_returns_clear_error(
    dividend_snapshot, bars_parquet_path, kwargs, message
):
    with pytest.raises(ValueError, match=message):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            **kwargs,
        )


def test_missing_bar_date_field_returns_clear_error(dividend_snapshot, bars_parquet_path):
    with pytest.raises(ValueError, match="bars is missing required column: missing_date"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            bar_date_field="missing_date",
        )


def test_cli_api_parity_rows_match_direct_join_result(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    output_path = tmp_path / "data" / "research" / "event_windows" / "joined.parquet"

    cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
        pre_window_days=1,
        post_window_days=1,
        output_path=output_path,
    )
    direct = join_dividend_events_to_bars_result(
        read_dividend_corporate_actions(dividend_snapshot),
        pd.read_parquet(bars_parquet_path),
        pre_window_days=1,
        post_window_days=1,
    )

    pd.testing.assert_frame_equal(pd.read_parquet(output_path), direct.frame)


def test_input_files_are_unchanged_after_cli_execution(
    dividend_snapshot, research_mart, bars_parquet_path, tmp_path
):
    snapshot_before = tree_file_bytes(dividend_snapshot)
    research_before = tree_file_bytes(research_mart)
    bars_before = file_bytes(bars_parquet_path)

    cli.join_dividend_event_windows(
        dividend_source="research-mart",
        research_root=research_mart,
        bars_path=bars_parquet_path,
        output_path=tmp_path / "data" / "research" / "event_windows" / "joined.parquet",
    )

    assert tree_file_bytes(dividend_snapshot) == snapshot_before
    assert tree_file_bytes(research_mart) == research_before
    assert file_bytes(bars_parquet_path) == bars_before


def test_cli_requires_no_live_credentials(monkeypatch, dividend_snapshot, bars_parquet_path):
    for env_name in [
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ]:
        monkeypatch.delenv(env_name, raising=False)

    summary = cli.join_dividend_event_windows(
        dividend_source="snapshot",
        snapshot_root=dividend_snapshot,
        bars_path=bars_parquet_path,
    )

    assert summary["event_count"] == 2


def test_unsafe_output_path_under_curated_is_rejected(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=tmp_path / "data" / "curated" / "event_windows" / "joined.parquet",
        )


def test_unsafe_output_path_equal_to_bars_path_is_rejected(dividend_snapshot, bars_parquet_path):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=bars_parquet_path,
        )


def test_unsafe_output_path_overlapping_snapshot_root_is_rejected(
    dividend_snapshot, bars_parquet_path
):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=dividend_snapshot / "joined.parquet",
        )


def test_unsafe_output_path_overlapping_research_root_is_rejected(research_mart, bars_parquet_path):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="research-mart",
            research_root=research_mart,
            bars_path=bars_parquet_path,
            output_path=research_mart / "joined.parquet",
        )


def test_snapshot_source_rejects_output_overlapping_research_root(
    dividend_snapshot, research_mart, bars_parquet_path
):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            research_root=research_mart,
            bars_path=bars_parquet_path,
            output_path=research_mart / "joined.parquet",
        )


def test_research_mart_source_rejects_output_overlapping_snapshot_root(
    dividend_snapshot, research_mart, bars_parquet_path
):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="research-mart",
            snapshot_root=dividend_snapshot,
            research_root=research_mart,
            bars_path=bars_parquet_path,
            output_path=dividend_snapshot / "joined.parquet",
        )


def test_unsafe_output_path_with_canonical_part_is_rejected(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    with pytest.raises(ValueError, match="derived research path.*curated/canonical"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=tmp_path / "data" / "canonical" / "joined.parquet",
        )


def test_output_format_without_output_path_is_rejected(dividend_snapshot, bars_parquet_path):
    with pytest.raises(ValueError, match="--output-format requires --output-path"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_format="csv",
        )


def test_unsupported_bars_format_is_rejected(dividend_snapshot, bars_parquet_path):
    with pytest.raises(ValueError, match="Unsupported bars format"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            bars_format="json",
        )


def test_unsupported_output_format_is_rejected(dividend_snapshot, bars_parquet_path, tmp_path):
    with pytest.raises(ValueError, match="Could not infer output format"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=tmp_path / "data" / "research" / "event_windows" / "joined.json",
        )


def test_explicit_unsupported_output_format_is_rejected(
    dividend_snapshot, bars_parquet_path, tmp_path
):
    with pytest.raises(ValueError, match="Unsupported output format"):
        cli.join_dividend_event_windows(
            dividend_source="snapshot",
            snapshot_root=dividend_snapshot,
            bars_path=bars_parquet_path,
            output_path=tmp_path / "data" / "research" / "event_windows" / "joined.parquet",
            output_format="json",
        )


def test_console_script_entry_point_is_declared_and_importable():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["fintech-join-dividend-event-windows"]
        == "src.cli.join_dividend_event_windows:main"
    )
    assert callable(cli.main)
