# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] — Dividend Research Workflows — 2025-05-20

### Added

- **Point-in-Time Dividend Research Semantics** (Issue #42)
  - `ex_date` as the default dividend event-study anchor.
  - Immutable dividend research semantics constants in `src.ingestion.dividend_research_semantics`.
  - Comprehensive date field semantics and lookahead boundaries.
  - Explicit adjusted-return non-goals documentation.

- **Partitioned Dividend Research Mart** (Issue #40)
  - Derived research-mart layout under `data/research/corporate_actions/dividends/`.
  - Partitioned by `symbol` and `year` (derived from `ex_date`).
  - Research mart writer, reader, and snapshot-to-mart helpers in `src.ingestion.corporate_actions_research_mart`.
  - Metadata tracking for dataset role and source traceability.

- **Dividend-to-Bars Event-Window Join Helpers** (Issue #41)
  - Primary join helper: `join_dividend_events_to_bars()` in `src.ingestion.dividend_event_window`.
  - Calendar-day pre/post event windows around `ex_date`.
  - `event_day_offset` for daily bar event studies.
  - Convenience helpers for snapshot and research-mart sources.
  - Clear `event_*` and `bar_*` output naming.

- Documentation updates across `README.md` and `docs/corporate_actions_dividends.md`.
- Comprehensive test coverage for all three research workflow components.

### Preserved

- Existing deterministic dividend snapshot artifacts remain unchanged.
- Existing canonical dividend output paths remain unchanged.
- Existing bar storage and writers remain unchanged.
- All existing tests pass without modification.

### Not Included

- No adjusted price series.
- No total-return reconstruction.
- No dividend reinvestment modeling.
- No automatic backtest cash-flow treatment.
- No live-data or credential-dependent CI tests.

### Validation

- `pytest tests -q` — 90 tests passing
- `ruff check src tests` — zero lint errors
- `python scripts/validate.py` — all phases passing
- `python -m build` — sdist and wheel artifacts produced
- Artifact inspection — no live data, credentials, or generated live artifacts committed
- Repository hygiene — LF line endings, no accidentally tracked outputs, no local paths, no credential files

---

## [0.5.1] — Corporate Actions Dividend Ingestion Patch — 2025-05-18

### Added

- Support for nested Alpaca dividend response shapes (`corporate_actions.cash_dividends`, `corporate_actions.stock_dividends`).
- Missing cash-dividend currency defaults to `USD` with explicit metadata counters.
- Metadata fields for nested response detection and currency defaulting.

### Preserved

- Flat/list response compatibility.
- Existing deterministic snapshot contract.
- All existing functionality.

---

## Earlier Releases

For earlier release history, see commit history on GitHub.
