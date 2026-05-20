# M4 Release Readiness Checklist

## Milestone

M4 — Python Packaging, PyPI Readiness, and Ruff Quality Gates

## Branch

`feature/m4-python-packaging-pypi-ruff-quality`

## Release Principle

Packaging should make the project installable, lintable, and publish-ready without changing ingestion semantics or weakening deterministic validation.

## Scope Included

- M4.1 Modern Python packaging metadata
- M4.2 Ruff linting and formatting configuration
- M4.3 Wheel and source distribution build validation
- M4.4 Console script entry point
- M4.5 Packaging and PyPI-readiness documentation
- M4.6 Deterministic validation and release readiness
- M4.7 Secure TestPyPI publishing workflow

M4 adds:

- Modern Python packaging metadata in `pyproject.toml`
- Editable install support with the current `src.*` import layout preserved
- Runtime and development dependency separation
- Ruff lint and format configuration
- Package build validation for wheel and source distribution artifacts
- Package artifact inspection guidance
- Installed `fintech-ingest-corporate-actions` console script
- Packaging and PyPI-readiness documentation
- Manual GitHub Actions workflow for secure TestPyPI publishing

## Validation Commands

Run the focused M4 release-readiness sequence from the repository root:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"

pytest tests -q
pytest tests/test_m3_corporate_actions_validation.py -q

ruff check src tests examples
ruff format --check src tests examples

python -m py_compile src/cli/ingest_corporate_actions.py
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help

python -m build
```

These checks do not require live Alpaca credentials and do not publish packages.

## Optional Wheel Smoke Check

After `python -m build`, the generated wheel can be smoke-tested locally:

```bash
python -m pip install dist/*.whl
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

## Package Artifact Inspection

Inspect wheel and source distribution contents before any future publishing step:

```bash
tar tf dist/*.tar.gz
python -m zipfile --list dist/*.whl
```

PowerShell alternative:

```powershell
Get-ChildItem dist\*.tar.gz | ForEach-Object { tar tf $_.FullName }
Get-ChildItem dist\*.whl | ForEach-Object { python -m zipfile --list $_.FullName }
```

Artifact contents should be limited to source files, package metadata, license/readme content, and expected source-distribution test files. They must not include generated datasets, local artifacts, reports, caches, virtual environments, build outputs, credentials, or `.env` files.

## Package Artifact Safety Checks

- No `.env` files are included.
- No credentials, tokens, API keys, or secrets are included.
- No generated data under `data/` is included.
- No generated artifacts under `artifacts/` are included.
- No reports under `reports/` are included.
- No `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, or notebook checkpoints are included.
- No `.venv/` or `venv/` directories are included.
- No `dist/`, `build/`, or local `*.egg-info/` outputs are tracked.
- Generated build outputs are cleaned after validation unless intentionally inspecting them.

## M3 Corporate-Actions Regression Checks

- Dividend data remains modeled as corporate-action event evidence.
- Dividend data is not forced into OHLCV bar, trade, or quote contracts.
- No OHLCV contract changes are introduced by packaging work.
- Existing module invocation remains supported:

  ```bash
  python -m src.cli.ingest_corporate_actions --help
  ```

- Installed console script invocation remains supported:

  ```bash
  fintech-ingest-corporate-actions --help
  ```

- The installed console script delegates to `src.cli.ingest_corporate_actions:main`.
- M3 validation does not require `ALPACA_API_KEY_ID` or `ALPACA_API_SECRET_KEY`.
- Tests do not call the live Alpaca API.
- M3 corporate-actions schemas, storage contracts, deterministic ordering, duplicate handling, and CLI semantics remain unchanged.

## Documentation Checks

- `README.md` points to `docs/packaging_pypi_readiness.md`.
- `README.md` points to this M4 release-readiness checklist.
- `docs/packaging_pypi_readiness.md` documents setup, validation, build inspection, cleanup, CLI smoke checks, and publishing boundaries.
- `docs/corporate_actions_dividends.md` documents both CLI invocation styles.
- `docs/m3_release_readiness.md` remains accurate for M3 regression validation.
- No local absolute paths are introduced.
- No credentials, tokens, API keys, or secrets are documented.

## Publishing Boundary

M4 validates local package readiness and provides a controlled manual TestPyPI publishing path. It does not publish to real PyPI and does not add publishing credentials.

- `.github/workflows/publish-package.yml` is manually triggered with `target=testpypi`.
- The workflow validates, builds, uploads artifacts, and publishes to TestPyPI only.
- Trusted Publishing/OIDC is the preferred publishing approach.
- The workflow uses `id-token: write` only in the TestPyPI publish job.
- Token-based publishing is fallback only.
- Future publishing must be explicitly approved.
- Future publishing should prefer credential-safe patterns.
- Credentials and tokens must not be committed to the repository.
- Real PyPI publishing is out of scope for M4.7 and is not enabled in the workflow.

If token-based publishing is required later, add token values only as GitHub Actions repository secrets:

- `TEST_PYPI_API_TOKEN` for TestPyPI fallback publishing
- `PYPI_API_TOKEN` only for future real PyPI publishing after explicit approval

Never paste token values into source files, docs, issues, comments, workflow YAML, or logs.

## Safety Checks

- No PyPI or TestPyPI credentials are committed.
- No live Alpaca credentials are required for tests.
- No network-dependent tests are added.
- No generated data is committed.
- No generated artifacts or reports are committed.
- No `.env` file is committed.
- No `dist/`, `build/`, or `*.egg-info/` output is committed.
- No virtual environment is committed.
- M3 dividend corporate-actions contracts remain separate from OHLCV bar contracts.
- Existing `python -m ...` CLI usage remains supported.
- Installed console-script usage remains supported.
- TestPyPI must be validated before real PyPI.
- Real PyPI publishing requires explicit approval.

## Non-Goals Confirmed

- No automatic PyPI or TestPyPI publishing.
- No real PyPI publishing.
- No credentials, tokens, API keys, or secrets.
- No live Alpaca validation requirement.
- No ingestion behavior changes.
- No package runtime behavior changes.
- No weakening of M3 deterministic validation.
- No M3 corporate-actions schema, storage, ordering, duplicate-handling, or CLI semantic changes.
