# M3 Release Readiness Checklist

Milestone: M3 corporate-actions dividend ingestion

Branch:

```text
feature/m3-corporate-actions-dividend-ingestion
```

M3 adds an Alpaca corporate-actions ingestion domain for dividend records. It remains separate from existing OHLCV bar ingestion and currently supports only:

```text
cash_dividend
stock_dividend
```

## Scope Included

- M3.1 Alpaca corporate-actions client support
- M3.2 dividend corporate-actions normalization
- M3.3 deterministic dividend dataset persistence
- M3.4 CLI/pipeline entry point
- M3.5 corporate-actions documentation and CI-safe example
- M3.6 deterministic release-readiness validation

## Release Checks

- Focused M3 validation passes:

  ```bash
  pytest tests/test_m3_corporate_actions_validation.py -q
  ```

- Existing M3 unit slices pass:

  ```bash
  pytest tests/test_alpaca_corporate_actions_client.py -q
  pytest tests/test_corporate_actions_normalization.py -q
  pytest tests/test_corporate_actions_storage.py -q
  pytest tests/test_ingest_corporate_actions_cli.py -q
  pytest tests/test_corporate_actions_examples.py -q
  ```

- Full test suite passes:

  ```bash
  pytest tests -q
  ```

- Changed Python files compile:

  ```bash
  python -m py_compile \
    src/ingestion/alpaca_corporate_actions_client.py \
    src/ingestion/corporate_actions_normalization.py \
    src/ingestion/corporate_actions_storage.py \
    src/cli/ingest_corporate_actions.py \
    examples/corporate_actions_dividend_ingestion_example.py \
    tests/test_m3_corporate_actions_validation.py
  ```

- Lint runs if available:

  ```bash
  ruff check src tests examples
  ```

## Determinism Checks

- Mocked end-to-end ingestion produces deterministic row ordering.
- Repeated writes with the same source records produce the same source payload hashes.
- Repeated writes do not create uncontrolled duplicate rows.
- Metadata key fields remain stable across repeated writes.
- Empty API results write an empty Parquet dataset with the expected schema and zero-count metadata.

## Safety Checks

- Tests do not call the live Alpaca API.
- Tests do not require `ALPACA_API_KEY_ID` or `ALPACA_API_SECRET_KEY`.
- The CI-safe example uses fixed local sample records and an injected fake client.
- Dividend outputs are written under:

  ```text
  data/curated/corporate_actions/dividends/
  ```

- M3 validation does not write into existing market-data paths:

  ```text
  data/curated/bars_daily/
  data/curated/bars_1m/
  data/curated/trades/
  data/curated/quotes/
  ```

## Documentation Checks

- `README.md` links to the corporate-actions dividend documentation.
- `docs/corporate_actions_dividends.md` documents live CLI usage, supported flags, output paths, normalized schema fields, metadata fields, and the CI-safe example.
- Documented CLI flags match `src.cli.ingest_corporate_actions.build_parser()`.
- Documented output paths match the storage defaults in `src.ingestion.corporate_actions_storage`.

## Non-Goals Confirmed

- No total-return analytics are implemented in M3.
- No dividend-adjusted price calculations are implemented in M3.
- No portfolio cash-flow modeling is implemented in M3.
- Supported corporate-action types are not expanded beyond `cash_dividend` and `stock_dividend`.
- Existing bar/trade/quote ingestion behavior is unchanged.
