## Universe Selection Criteria

Document:
- Selection logic (liquidity + large-cap bias)
- Exclusion rules
- Intended expansion strategy


## 📡 Alpaca Market Data Client

The project includes a reusable Alpaca historical market data client:

```
src/ingestion/alpaca_client.py
```

### Features

* Auth via `.env`
* Supports:

  * `symbol`
  * `start`
  * `end`
  * `timeframe` (`1Day`, `1Min`)
  * `feed` (default: `iex`)
* Handles pagination automatically
* Implements exponential backoff for:

  * HTTP 429 (rate limit)
  * HTTP 5xx (server errors)
  * network timeouts
* Returns results as a pandas DataFrame

### Example Usage

```python
from src.ingestion.alpaca_client import AlpacaMarketDataClient

client = AlpacaMarketDataClient.from_env()

df = client.fetch_bars(
    symbol="AAPL",
    start="2025-01-01T00:00:00Z",
    end="2025-02-01T00:00:00Z",
    timeframe="1Day"
)

print(df.head())
```

---

## Architectural diagram


```
Alpaca API
     ↓
Alpaca Client (retry + pagination)
     ↓
Normalization Layer
     ↓
Partitioned Parquet
     ↓
DuckDB Analytics
```


## Current Capabilities

###  Alpaca Historical Market Data Client

* Auth via `.env`
* Supports:

  * `symbol`
  * `start`
  * `end`
  * `timeframe` (`1Day`, `1Min`)
  * `feed` (default: `iex`)
* Handles:

  * Pagination
  * Rate limiting (HTTP 429)
  * 5xx retries with exponential backoff
* Returns pandas DataFrame

---

###  Windowed Daily Backfill Pipeline

* Iterates over 50-ticker universe
* Fetches daily bars in monthly windows
* Normalizes to canonical schema
* Enforces UTC timestamps
* Deterministic deduplication on:

  ```
  (symbol, ts_utc, timeframe)
  ```
* Writes partitioned Parquet to:

  ```
  data/curated/bars_daily/symbol=XYZ/year=YYYY/
  ```
* Safe to rerun (idempotent)

---

###  Partitioned Parquet Storage

* Implemented using `pyarrow.write_to_dataset`
* Uses `delete_matching` behavior for clean partition overwrites
* DuckDB-compatible direct query over glob paths

---

###  DuckDB Analytics Validation

Example query:

```python
import duckdb
con = duckdb.connect()

df = con.execute("""
  SELECT symbol,
         MIN(ts_utc) AS min_ts,
         MAX(ts_utc) AS max_ts,
         COUNT(*) AS row_count
  FROM 'data/curated/bars_daily/**/*.parquet'
  GROUP BY symbol
  ORDER BY symbol
""").df()

print(df.head())
```

---

## Architecture Overview

```
Alpaca API
    ↓
AlpacaMarketDataClient
    ↓
Normalization Layer (UTC + dedupe)
    ↓
Partitioned Parquet (symbol/year)
    ↓
DuckDB Analytics
```

---



