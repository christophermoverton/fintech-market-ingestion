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

Dividend records are normalized and persisted separately under:

```text
data/curated/corporate_actions/dividends/
```

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

`raw` preserves the source Alpaca payload as stable JSON text in the persisted table. `source_payload_hash` is a deterministic hash of the raw source payload.

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

## Non-Goals

M3 dividend ingestion does not implement total-return analytics, dividend-adjusted prices, or portfolio cash-flow modeling. Those are downstream future use cases, not current project features.
