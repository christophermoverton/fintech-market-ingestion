# M7 Release Readiness - Research Mart Usability, CLI, and Workflow Integration

## Milestone Summary

M7 builds on v0.6.0 dividend research workflows by making derived dividend
research artifacts easier to build, inspect, validate, and compose from CLI
commands, Python APIs, notebook-style scripts, and pipeline-style scripts.

M7 principle:

```text
Derived research marts should be easy to build, inspect, validate, and compose
from CLI, notebooks, and pipelines without becoming canonical data sources or
mutating ingestion outputs.
```

## Completed Issues

* #47 Research mart builder CLI
* #48 Validation and inspection CLI
* #49 Event-window join CLI
* #50 Derived event-window output writer and metadata
* #51 Notebook-style quickstart
* #52 Pipeline-style workflow
* #53 CLI/API parity and smoke tests
* #54 Documentation and release readiness

## Artifact Boundary Checklist

* Curated dividend snapshot remains canonical.
* Research mart remains derived.
* Event-window outputs remain derived.
* Validation and inspection are read-only.
* Examples write under configured output roots.
* No live Alpaca credentials are required for M7 examples or tests.
* No scheduler dependencies are required.
* Derived outputs are not adjusted prices, total-return series, reinvestment
  outputs, or backtest cash-flow outputs.

## Validation Commands

Run before release:

```bash
ruff check src tests examples
pytest tests -q
python scripts/validate.py
python -m build
```

## Manual Smoke Commands

Run the notebook-style synthetic quickstart:

```bash
python examples/dividend_research_mart_quickstart.py \
  --output-root artifacts/examples/dividend_research_mart_quickstart
```

Run the scheduler-free pipeline-style workflow:

```bash
python examples/dividend_research_pipeline_workflow.py \
  --output-root artifacts/examples/dividend_research_pipeline_workflow
```

After generating a synthetic snapshot and bars file, representative local CLI
commands are:

```bash
python -m src.cli.build_dividend_research_mart \
  --snapshot-root artifacts/examples/dividend_research_mart_quickstart/data/curated/corporate_actions/dividends \
  --research-root artifacts/examples/dividend_research_mart_quickstart/data/research/corporate_actions/dividends
```

```bash
python -m src.cli.validate_dividend_research_mart \
  --research-root artifacts/examples/dividend_research_mart_quickstart/data/research/corporate_actions/dividends
```

```bash
python -m src.cli.join_dividend_event_windows \
  --dividend-source research-mart \
  --research-root artifacts/examples/dividend_research_mart_quickstart/data/research/corporate_actions/dividends \
  --bars-path artifacts/examples/dividend_research_mart_quickstart/data/local/daily_bars.parquet \
  --pre-window-days 1 \
  --post-window-days 1 \
  --output-root artifacts/examples/dividend_research_mart_quickstart/data/research/corporate_actions/dividend_event_windows/manual_smoke
```

These commands are local examples and do not require Alpaca credentials.

## Release Checklist

* README updated.
* Detailed dividend docs updated.
* Changelog updated.
* Release readiness doc added.
* Full tests green.
* Build succeeds.
* No generated artifacts accidentally committed.
* No `.pytest_tmp*` or local temp artifacts committed.
* No credentials or secrets.
* No absolute Windows paths in docs.
* No claims of adjusted-price support.
* No claims of total-return reconstruction support.
* No claims of dividend reinvestment support.
* No claims of backtest cash-flow behavior support.

## Non-Goals

M7 does not add:

* adjusted prices
* total-return reconstruction
* dividend reinvestment
* backtest cash-flow behavior
* database, registry, dashboard, or service dependencies
* scheduler dependencies such as Airflow, Prefect, or Dagster
* live Alpaca calls in tests or examples
