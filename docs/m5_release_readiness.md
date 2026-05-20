# M5 Release Readiness Checklist

## Milestone

M5 — Cross-Platform CI and Contributor Validation Hardening

## Branch

`feature/m5-cross-platform-ci-validation-hardening`

## Release Tag Candidate

`v0.5.0-cross-platform-ci-validation-hardening`

## M5 Principle

Cross-platform compatibility should make packaging, validation, and CLI
workflows reproducible from a clean checkout on Windows, macOS, and Linux
without weakening ingestion contracts or publishing safety.

## Scope Included

M5 adds:

- cross-platform CI matrix
- local validation wrapper
- wheel build/install smoke checks
- repository hygiene validation
- cross-platform contributor documentation

Implemented issue scope:

- Issue #30: Cross-platform CI matrix
- Issue #31: Python validation wrapper
- Issue #32: Wheel install and console-script smoke checks
- Issue #33: Path, line-ending, and generated-output safety checks
- Issue #34: Cross-platform contributor setup documentation

## CI Matrix Expectations

The ordinary CI workflow lives at `.github/workflows/ci.yml`. It does not
publish packages and does not require live Alpaca credentials.

### Source Validation Matrix

The source-validation job runs `python scripts/check_repo_hygiene.py`, installs
the package with development dependencies, then runs `python scripts/validate.py`
on:

- `ubuntu-latest` / Python 3.10
- `ubuntu-latest` / Python 3.11
- `ubuntu-latest` / Python 3.12
- `windows-latest` / Python 3.12
- `macos-latest` / Python 3.12

### Wheel Smoke Matrix

The wheel-smoke job installs build tooling, runs `python -m build`, and runs
`python scripts/smoke_test_wheel.py` on:

- Wheel smoke / `ubuntu-latest` / Python 3.12
- Wheel smoke / `windows-latest` / Python 3.12
- Wheel smoke / `macos-latest` / Python 3.12

## Local Validation Commands

Run from the repository root:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
python scripts/check_repo_hygiene.py
python scripts/validate.py
python -m build
python scripts/smoke_test_wheel.py
```

These checks are credential-free and do not call the live Alpaca API.

## Repository Hygiene Checks

`python scripts/check_repo_hygiene.py` validates tracked files for:

- LF line endings in normalized tracked text files
- forbidden tracked generated or local-only files
- obvious local absolute paths
- credential-file avoidance

Generated outputs may exist locally while validating, but they must not be
tracked or committed.

## Wheel Install and Console-Script Smoke Checks

Wheel smoke validation builds local package artifacts, locates exactly one wheel
under `dist/`, installs it with the active Python interpreter, and runs:

```bash
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

This proves both supported CLI invocation styles after wheel install. It does
not publish to TestPyPI or PyPI.

## M3 Corporate-Actions Regression Checks

M5 must preserve M3 behavior:

- dividend ingestion remains corporate-action event evidence
- dividend data is not forced into OHLCV bars, trades, or quotes
- M3 schemas remain unchanged
- storage contracts remain unchanged
- deterministic ordering remains unchanged
- duplicate handling remains unchanged
- CLI semantics remain unchanged
- tests do not require Alpaca credentials
- tests do not call the live Alpaca API

Focused regression validation remains:

```bash
python -m pytest tests/test_m3_corporate_actions_validation.py -q
```

## M4 Packaging and Publishing Boundary Checks

M5 must preserve M4 packaging and publishing boundaries:

- editable install remains supported with `python -m pip install -e ".[dev]"`
- package build remains local validation
- wheel smoke checks do not publish
- ordinary CI does not publish
- TestPyPI remains manual and gated through `.github/workflows/publish-package.yml`
- real PyPI publishing remains out of scope unless separately approved
- no publishing tokens or credentials are committed

## Generated-Output Safety Checks

Do not commit:

- `.env`
- `.venv/`
- `venv/`
- `data/`
- `artifacts/`
- `reports/`
- `dist/`
- `build/`
- `*.egg-info`
- `.pytest_cache/`
- `.ruff_cache/`
- `__pycache__/`
- notebook checkpoints

PowerShell cleanup:

```powershell
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force *.egg-info -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force .pytest_cache, .ruff_cache -ErrorAction SilentlyContinue
```

POSIX cleanup:

```bash
rm -rf dist build *.egg-info .pytest_cache .ruff_cache
find . -type d -name __pycache__ -prune -exec rm -rf {} +
```

Then verify:

```bash
git status --porcelain
```

## Documentation Checks

- `README.md` links to `docs/cross_platform_contributor_validation.md`.
- `README.md` links to this M5 release-readiness checklist.
- `docs/cross_platform_contributor_validation.md` documents Windows,
  macOS, and Linux setup.
- `docs/packaging_pypi_readiness.md` remains aligned with M5 validation scripts.
- Documentation uses repository-relative paths only.
- Documentation does not include credentials, tokens, or local machine paths.
- Documentation distinguishes CI-safe validation from live ingestion.
- Documentation preserves TestPyPI and PyPI publishing boundaries.

## Pre-Merge Validation Checklist

- Run local validation:

  ```bash
  python scripts/validate.py
  ```

- Run repository hygiene checks:

  ```bash
  python scripts/check_repo_hygiene.py
  ```

- Run wheel smoke checks:

  ```bash
  python -m build
  python scripts/smoke_test_wheel.py
  ```

- Clean generated outputs.
- Inspect `git status --porcelain`.
- Confirm README and docs links resolve.
- Confirm the remote CI source-validation matrix is green.
- Confirm the remote CI wheel-smoke matrix is green.
- Confirm no generated outputs or credentials are tracked.
- Confirm no M3 or M4 boundary changes are included.

## Post-Merge Validation Checklist

- Pull latest `main`.
- Recreate or refresh the virtual environment if needed.
- Run M5 local validation:

  ```bash
  python -m pip install -U pip
  python -m pip install -e ".[dev]"
  python scripts/validate.py
  ```

- Confirm GitHub Actions is green on `main`.
- Confirm no generated outputs are committed.
- Create the release tag candidate only after post-merge validation passes.

## Publishing Boundary

Ordinary CI does not publish packages. Wheel smoke checks do not publish
packages. TestPyPI remains manual and gated through
`.github/workflows/publish-package.yml`.

Real PyPI publishing remains out of scope unless separately approved. No
publishing credentials, tokens, or local credential files should be committed.

## Safety Checks

- No `.env` files are required for validation.
- No live Alpaca credentials are required for validation.
- No live Alpaca API calls are made by validation.
- No network-dependent tests are added.
- No generated data is committed.
- No generated artifacts or reports are committed.
- No caches are committed.
- No virtual environment is committed.
- M3 dividend corporate-actions contracts remain separate from OHLCV bar,
  trade, and quote contracts.
- Existing `python -m ...` CLI usage remains supported.
- Installed console-script usage remains supported.
- TestPyPI remains manual and gated.
- Real PyPI publishing requires separate approval.

## Non-Goals Confirmed

- No ingestion behavior changes.
- No M3 corporate-actions schema changes.
- No storage-contract changes.
- No deterministic-ordering changes.
- No duplicate-handling changes.
- No CLI semantic changes.
- No live Alpaca validation requirement.
- No network-dependent tests.
- No automatic TestPyPI publishing.
- No real PyPI publishing.
- No credentials, tokens, or local machine paths.
- No generated outputs committed.
