# Corporate Actions Dividend Ingestion

M3 adds a separate corporate-actions data domain to the project. Dividend ingestion uses Alpaca corporate-action records and does not reuse OHLCV bar, trade, or quote contracts.

## Data Domains

Bars, trades, and quotes are price/volume market data. Existing daily and 1-minute ingestion writes OHLCV records under paths such as:

```text
data/curated/bars_daily/
data/curated/bars_1m/
```

Corporate actions are event-based issuer or security events. M3 currently supports dividend events only:

```text
cash_dividend
stock_dividend
```

The Alpaca client accepts both the older flat response shape and newer nested
dividend response shapes. Supported nested keys are:

```text
corporate_actions.cash_dividends
corporate_actions.stock_dividends
cash_dividends
stock_dividends
```

Nested `cash_dividends` rows normalize to `corporate_action_type = cash_dividend`. Nested `stock_dividends` rows normalize to `corporate_action_type = stock_dividend`. Cash-dividend groups are flattened
before stock-dividend groups, and API order is preserved within each group until
the repository's normal deterministic output ordering is applied.

Dividend records are normalized and persisted separately under:

```text
data/curated/corporate_actions/dividends/
```

## Point-in-Time Research Semantics

Dividend records are event evidence. They are useful for research joins and event studies, but they are not adjusted prices, total-return series, or dividend-reinvestment outputs.

Default event-study anchor:

```text
ex_date
```

Use `ex_date` as the default anchor when studying market reaction around dividend entitlement because it is the common event-study boundary for price and bar behavior. Use another field only when the research question explicitly requires that anchor and the field was known at the decision timestamp.

### Dividend Date Fields

| Field | Purpose | Research caution |
| --- | --- | --- |
| `declaration_date` | company announcement date | usable only once known |
| `ex_date` | entitlement and common event-study anchor | default anchor for price and bar event studies |
| `record_date` | shareholder eligibility record date | not usually the trading anchor |
| `payable_date` | cash-flow payment timing | not usually a price-event anchor |
| `process_date` | ingestion and source as-of provenance | not the corporate event date |

### Point-in-Time Usage Guidance

Point-in-time research should only use fields that were known as of the research timestamp. That means:

* `declaration_date` can support announcement-reaction studies only after the announcement is observable.
* `ex_date` is the default anchor for event-window joins against bars or trades.
* `record_date` is mainly entitlement and accounting context, not a price-event anchor.
* `payable_date` is payment timing, not a market-entry signal.
* `process_date` is useful for source provenance and ingestion as-of checks, but it should not be treated as the corporate event date.

Lookahead boundaries to avoid:

* Do not use `payable_date` as a signal before it is known.
* Do not treat future-corrected dividend rows as if they were available historically.
* Do not build labels or signals from dividend fields that would not have been visible at the decision timestamp.

### Adjusted-Return Boundaries

Current repository state does not implement:

```text
adjusted prices
total-return series
dividend reinvestment
automatic backtest cash-flow treatment
```

Dividend records remain canonical event evidence. Any future adjusted-return dataset should be defined as a separate derived artifact with explicit inputs, point-in-time/as-of policy, and no mutation of canonical dividend artifacts or bar data.

### Future Work Boundary

M7 adds the derived research mart, event-window joins, local CLIs, examples, and
metadata-backed derived event-window outputs. Future adjusted-return work should
remain a separate derived dataset with explicit input artifacts, deterministic
metadata, and no mutation of raw bars or canonical dividend artifacts.

If you need these semantics programmatically, see `src.ingestion.dividend_research_semantics` for the current constants.

## Live CLI Usage

Live ingestion requires Alpaca credentials in the environment or `.env` file:

```text
ALPACA_API_KEY_ID
ALPACA_API_SECRET_KEY
ALPACA_DATA_BASE_URL
ALPACA_FEED
```

Credentials are required only for live API usage. The unit tests and example script use fixed sample data and do not call Alpaca.

Run dividend corporate-actions ingestion with:

```bash
fintech-ingest-corporate-actions \
  --symbols AAPL MSFT SPY \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --types cash_dividend stock_dividend \
  --output-root data/curated/corporate_actions/dividends
```

The existing module invocation is still supported:

```bash
python -m src.cli.ingest_corporate_actions \
  --symbols AAPL MSFT SPY \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --types cash_dividend stock_dividend \
  --output-root data/curated/corporate_actions/dividends
```

Supported arguments:

| Argument | Description |
| --- | --- |
| `--symbols` | One or more ticker symbols. Required. |
| `--start` | Inclusive start date for Alpaca corporate-action records. Required. |
| `--end` | Inclusive end date for Alpaca corporate-action records. Required. |
| `--types` | Dividend action types to request. Defaults to `cash_dividend stock_dividend`. |
| `--output-root` | Curated dividends dataset root. Defaults to `data/curated/corporate_actions/dividends`. |
| `--sort` | Alpaca sort order. Defaults to `asc`. |
| `--limit` | Alpaca page size limit. Defaults to `1000`. |

After an editable or wheel install, the package also exposes the console script:

```bash
fintech-ingest-corporate-actions --help
```

The command prints a JSON summary with:

```text
requested_symbols
start
end
action_types
fetched_record_count
normalized_record_count
written_record_count
duplicate_record_count
data_path
metadata_path
```

## Expected Outputs

The persistence layer writes:

```text
data/curated/corporate_actions/dividends/dividends.parquet
data/curated/corporate_actions/dividends/metadata.json
```

The Parquet file contains normalized dividend records. The metadata JSON describes the ingestion request and write behavior.

## Canonical and Derived Artifact Roles

M7 keeps ingestion outputs and research outputs deliberately separate:

* The curated dividend snapshot under `data/curated/corporate_actions/dividends/` remains the canonical ingestion output.
* The dividend research mart under `data/research/corporate_actions/dividends/` is a derived query layout.
* Dividend event-window outputs under `data/research/corporate_actions/dividend_event_windows/` are derived research artifacts.
* Validation and inspection summaries are advisory and read-only.
* CI-safe examples write only under their configured local output roots.

Derived research artifacts are designed for notebooks, local scripts, and
pipelines. They must not replace or mutate canonical dividend snapshots or bar
inputs.

## Dividend Research Mart (M7)

The deterministic snapshot under `data/curated/corporate_actions/dividends/` remains the release-safe ingestion output.

Issue #40 adds a separate derived research mart for symbol and date analysis:

```text
data/research/corporate_actions/dividends/
  symbol=<SYMBOL>/
    year=<YYYY>/
      *.parquet
data/research/corporate_actions/dividends/metadata.json
```

Research mart partition semantics:

* Partition columns: `symbol`, `year`
* Event anchor: `ex_date`
* Event anchor source: normalized dividend `ex_date`
* `year` is derived from `ex_date`
* Rows missing required partition fields (`symbol`, `ex_date`) are rejected fail-fast

The research mart is generated from canonical normalized dividend fields and does not replace or mutate the deterministic snapshot artifacts. It is intended as a query layout for downstream analytics and future event-window joins.

If partition columns are encoded in Hive directory paths, read from the dataset root so engines reconstruct partition columns during dataset scan.

The research mart still does not implement adjusted prices, total-return reconstruction, dividend reinvestment, or backtest cash-flow behavior. Dividend-to-bars joins are separate derived research views.

Build the research mart from an existing curated dividend snapshot with:

```bash
python -m src.cli.build_dividend_research_mart \
  --snapshot-root data/curated/corporate_actions/dividends \
  --research-root data/research/corporate_actions/dividends
```

After an editable or wheel install, the package also exposes:

```bash
fintech-build-dividend-research-mart \
  --snapshot-root data/curated/corporate_actions/dividends \
  --research-root data/research/corporate_actions/dividends
```

The command prints a deterministic JSON summary to stdout. Add `--summary-output path/to/summary.json` to write the same JSON summary to a file. Parent directories are created when writing the summary file.

Validate and inspect the derived research mart without mutating it:

```bash
python -m src.cli.validate_dividend_research_mart \
  --research-root data/research/corporate_actions/dividends
```

After an editable or wheel install, the validation command is also available as:

```bash
fintech-validate-dividend-research-mart \
  --research-root data/research/corporate_actions/dividends
```

Validation prints deterministic JSON with metadata, schema, row-count,
symbol/year coverage, partition, and event-anchor checks. It is read-only; the
research mart remains a derived research surface and is not canonical data. The
CLI returns exit code `0` when validation executes successfully; validation
status is reported in the JSON `valid` field. `--summary-output` writes the
same deterministic JSON to disk.

## Dividend-to-Bars Event Windows (M7)

M7 includes deterministic research helpers and CLI wrappers for joining dividend
events to bar data without mutating canonical dividend or bar datasets.

Primary helper:

```text
src.ingestion.dividend_event_window.join_dividend_events_to_bars
```

Thin convenience helpers are also available for loading dividends from canonical snapshot or research-mart roots before joining:

```text
join_dividend_snapshot_to_bars
join_dividend_research_mart_to_bars
```

Current support focuses on daily-style bar datasets using canonical bar fields (`symbol`, `ts_utc`, `open`, `high`, `low`, `close`, `volume`). Minute-specific window behavior is a future follow-up.

Event-window semantics:

* Default anchor field: `ex_date`
* `window_start = event_date - pre_window_days`
* `window_end = event_date + post_window_days`
* Include bars where `window_start <= bar_date <= window_end`
* `event_day_offset = bar_date - event_date` in calendar days

`event_day_offset` interpretation:

* negative: pre-event bars
* zero: event-date bars
* positive: post-event bars

The helpers use calendar-day offsets (not trading-calendar offsets). Output rows are deterministic and include prefixed event and bar fields plus derived fields such as `event_date_field`, `event_date`, `event_day_offset`, and `bar_timeframe`.

Join local dividend events to local bar data from the CLI:

```bash
python -m src.cli.join_dividend_event_windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-path data/research/corporate_actions/dividend_event_windows/event_windows.parquet
```

After an editable or wheel install, the console script is:

```bash
fintech-join-dividend-event-windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-path data/research/corporate_actions/dividend_event_windows/event_windows.parquet
```

The command is local and credential-free. It accepts CSV or Parquet bar inputs,
can read dividends from the curated snapshot or derived research mart, and can
optionally write CSV or Parquet joined rows as derived research output. It does
not mutate canonical dividend snapshots, research marts, or bar inputs. Direct
output format is inferred from `.parquet`, `.pq`, or `.csv`, or can be supplied
with `--output-format`. Add `--summary-output path/to/summary.json` to write the
same deterministic JSON summary printed to stdout.

Issue #50 adds a derived event-window output contract for runs that should carry
metadata alongside joined rows:

```bash
python -m src.cli.join_dividend_event_windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-root data/research/corporate_actions/dividend_event_windows/example_run
```

The installed console-script equivalent is:

```bash
fintech-join-dividend-event-windows \
  --dividend-source research-mart \
  --research-root data/research/corporate_actions/dividends \
  --bars-path data/local/synthetic_bars.parquet \
  --pre-window-days 2 \
  --post-window-days 2 \
  --output-root data/research/corporate_actions/dividend_event_windows/example_run
```

The contract layout is:

```text
data/research/corporate_actions/dividend_event_windows/<run_or_workflow_id>/
  event_windows.parquet
  metadata.json
```

Metadata links the derived output to the dividend input path, bar input path,
event-window configuration, row counts, and schema. These outputs remain derived
research artifacts and are not canonical data.

Event-window metadata includes:

```text
dataset
dataset_role = derived_research_event_window
source_dividend_path
source_bar_path
event_anchor
pre_window_days
post_window_days
bar_timeframe
symbol_filter
event_count
bar_count
joined_row_count
row_count
schema_fields
data_file
metadata_file
format
created_by
```

The writer rejects output roots that overlap curated dividend snapshots, derived
dividend research marts, source dividend inputs, source bar inputs, or paths
containing `canonical`.

Safety boundaries enforced by the CLI and writer:

* Output roots cannot overlap curated dividend snapshots.
* Output roots cannot overlap derived dividend research marts.
* Output roots cannot overlap source dividend inputs.
* Output roots cannot overlap source bar inputs.
* Paths containing `canonical` are rejected.
* Examples do not call Alpaca and do not require credentials.
* No scheduler dependencies are introduced.

Python API entry points:

```python
from src.ingestion.corporate_actions_research_mart import (
    inspect_dividend_research_mart,
    validate_dividend_research_mart,
    write_dividend_research_mart_from_snapshot,
)
from src.ingestion.dividend_event_window import (
    join_dividend_events_to_bars_result,
    read_dividend_event_window_output,
    write_dividend_event_window_output,
)
```

Example Python composition:

```python
mart_result = write_dividend_research_mart_from_snapshot(
    snapshot_root="data/curated/corporate_actions/dividends",
    research_root="data/research/corporate_actions/dividends",
)
inspection = inspect_dividend_research_mart(mart_result.root_dir)
validation = validate_dividend_research_mart(mart_result.root_dir)

join_result = join_dividend_events_to_bars_result(
    dividends,
    bars,
    pre_window_days=2,
    post_window_days=2,
)
output_result = write_dividend_event_window_output(
    join_result,
    output_root="data/research/corporate_actions/dividend_event_windows/example_run",
    source_dividend_path=mart_result.root_dir,
    source_bar_path="data/local/synthetic_bars.parquet",
    pre_window_days=2,
    post_window_days=2,
)
loaded_event_windows = read_dividend_event_window_output(output_result.root_dir)
```

For a notebook-style quickstart that uses only synthetic local data:

```bash
python examples/dividend_research_mart_quickstart.py \
  --output-root artifacts/examples/dividend_research_mart_quickstart
```

The quickstart is a plain Python script organized into notebook-style sections.
It demonstrates snapshot -> research mart -> validation -> event-window join ->
derived output metadata without calling Alpaca or mutating canonical repository
data. It writes a synthetic curated snapshot, derived research mart, synthetic
bars, contract-style event-window output, and `summary.json` under the configured
output root.

For a scheduler-free pipeline-style workflow using small stage functions:

```bash
python examples/dividend_research_pipeline_workflow.py \
  --output-root artifacts/examples/dividend_research_pipeline_workflow
```

The pipeline example uses synthetic local data only, writes only under the
configured output root, and demonstrates snapshot -> research mart -> validation
-> event-window join -> derived output metadata -> workflow summary. It differs
from the quickstart by organizing the same public APIs into small stage
functions with a `workflow_summary.json`, without adding Airflow, Prefect,
Dagster, or any scheduler dependency.

As with the rest of dividend research support, these joins are derived research views only. They do not implement adjusted prices, total-return reconstruction, dividend reinvestment, or backtest cash-flow logic.

## Normalized Schema

Normalized dividend records include:

```text
corporate_action_id
symbol
corporate_action_type
source
process_date
declaration_date
ex_date
record_date
payable_date
cash_amount
stock_amount
currency
source_payload_hash
raw
```

`raw` preserves the source Alpaca payload as stable JSON text in the persisted
table. For nested Alpaca dividend groups, `raw` also records the Alpaca dividend
group key so downstream QA can distinguish `cash_dividends` from
`stock_dividends`, plus `_alpaca_original_payload` with the exact nested event
payload before the client inferred `corporate_action_type`. `source_payload_hash`
is a deterministic hash of the raw source payload.

For `cash_dividend` records, normalized `cash_amount` uses Alpaca `cash_amount`
when present. If `cash_amount` is absent or null and Alpaca provides `rate`, the
normalizer uses `rate` as the cash amount while preserving the original payload
unchanged in `raw`.

## Currency Policy

Cash-dividend currency behavior is explicit. If Alpaca provides `currency`, the
normalized row preserves that value. If Alpaca omits `currency` for a
`cash_dividend`, the normalizer defaults the normalized `currency` field to
`USD`. The original source payload remains preserved in `raw`, so a missing
source currency is still auditable.

This default is intended for Alpaca US-equity cash-dividend evidence. It does
not change downstream StratLake behavior and does not implement adjusted prices,
total-return reconstruction, or dividend reinvestment.

## Metadata Fields

`metadata.json` includes:

```text
dataset
path
format
data_file
source
sources
ingest_start_date
ingest_end_date
action_types
record_count
written_record_count
duplicate_record_count
duplicate_handling
event_key
currency_policy
currency_missing_for_cash_dividend_count
currency_defaulted_for_cash_dividend_count
nested_response_detected
nested_cash_dividend_count
nested_stock_dividend_count
```

The event key used for duplicate handling is:

```text
corporate_action_id
symbol
corporate_action_type
ex_date
process_date
```

Repeated writes overwrite the deterministic dataset file for the requested run. Duplicate input records are collapsed by the event key before persistence.

`currency_policy` is currently:

```text
cash_dividend_missing_currency_defaults_to_USD
```

When cash-dividend currency is omitted by Alpaca, both
`currency_missing_for_cash_dividend_count` and
`currency_defaulted_for_cash_dividend_count` record the affected row count.
Nested response counters record how many persisted rows came from Alpaca's
nested dividend group keys.

## CI-Safe Example

Run the sample-data example without Alpaca credentials:

```bash
python examples/corporate_actions_dividend_ingestion_example.py
```

By default, the example writes to:

```text
artifacts/examples/corporate_actions_dividends/
```

Expected files:

```text
artifacts/examples/corporate_actions_dividends/dividends.parquet
artifacts/examples/corporate_actions_dividends/metadata.json
```

You can override the output root:

```bash
python examples/corporate_actions_dividend_ingestion_example.py \
  --output-root artifacts/examples/corporate_actions_dividends
```

The example uses an injected fake client with fixed local sample records. It exercises the same pipeline function used by the live CLI, but it does not read credentials and does not make network calls.

Manual live validation, such as a small AAPL Q1 run, is optional and outside
ordinary CI. Do not commit downloaded live Alpaca payloads or generated live
artifacts.

## Non-Goals

M3 dividend ingestion does not implement total-return analytics, dividend-adjusted prices, or portfolio cash-flow modeling. Those are downstream future use cases, not current project features.
