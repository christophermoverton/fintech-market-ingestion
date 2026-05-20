# Cross-Platform Contributor Validation

## Purpose

This guide helps contributors reproduce the M5 GitHub Actions validation path
from a clean checkout on Windows, macOS, and Linux. The checks are designed to
be deterministic and credential-free: they do not require Alpaca credentials,
do not call the live Alpaca API, and do not publish packages.

## Supported Validation Surfaces

- Windows PowerShell
- macOS shell
- Linux shell
- GitHub Actions in `.github/workflows/ci.yml`

The M5 CI source-validation matrix runs:

- Ubuntu on Python 3.10, 3.11, and 3.12
- Windows on Python 3.12
- macOS on Python 3.12

The wheel smoke matrix runs on Ubuntu, Windows, and macOS with Python 3.12.

## Clean Checkout Setup

Clone the repository, switch to the M5 branch, and run all commands from the
repository root:

```bash
git clone https://github.com/christophermoverton/fintech-market-ingestion.git
cd fintech-market-ingestion
git switch feature/m5-cross-platform-ci-validation-hardening
```

Use repository-relative paths in docs, configs, scripts, and examples. Do not
commit local absolute paths, generated outputs, caches, virtual environments, or
credential files.

## Python and Virtual Environment Setup

Use a supported Python version. Python 3.12 is the common cross-platform CI
target, while Ubuntu also validates Python 3.10 and 3.11.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS and Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

If your shell has multiple Python installations, confirm the active interpreter
before installing dependencies:

```bash
python --version
python -m pip --version
```

## Editable Development Install

Install the package and development tools with the active interpreter:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Prefer `python -m pip` over bare `pip` so installation uses the same Python that
will run validation.

## Run Local Validation

Run the M5 local validation wrapper:

```bash
python scripts/validate.py
```

The wrapper runs:

- repository hygiene checks
- full pytest suite
- focused M3 corporate-actions regression tests
- Ruff lint check
- Ruff format check
- `py_compile` smoke check for the corporate-actions CLI
- module CLI help smoke check
- installed console-script help smoke check

This command mirrors the source-validation behavior used by CI after editable
install.

## Run Repository Hygiene Checks

Run the hygiene validator directly when you want a fast source-control safety
check:

```bash
python scripts/check_repo_hygiene.py
```

It validates tracked files for:

- LF line endings in normalized text files
- forbidden generated or local-only outputs tracked by Git
- obvious local absolute paths
- obvious credential files

The hygiene check inspects tracked files only. Ignored local build outputs can
exist while you work, but they must not be committed.

## Run Wheel Smoke Validation

Build local package artifacts and smoke-test the generated wheel:

```bash
python -m build
python scripts/smoke_test_wheel.py
```

The wheel smoke helper locates exactly one wheel under `dist/`, installs it with
the active Python interpreter, then runs:

```bash
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

This validates the package build and installed console script without publishing
to TestPyPI or PyPI.

## CLI Smoke Checks

The corporate-actions CLI supports both invocation styles:

```bash
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

Use the module invocation when PATH is confusing. The validation wrapper and
wheel smoke helper also handle installed console-script lookup through Python's
scripts path when needed.

## Cleanup Generated Outputs

Package builds, tests, and Python execution can create local outputs. These
outputs are ignored and should not be committed.

PowerShell cleanup:

```powershell
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force *.egg-info -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force .pytest_cache, .ruff_cache -ErrorAction SilentlyContinue
```

macOS and Linux cleanup:

```bash
rm -rf dist build *.egg-info .pytest_cache .ruff_cache
find . -type d -name __pycache__ -prune -exec rm -rf {} +
```

After cleanup, inspect the working tree:

```bash
git status --porcelain
```

## Generated-Output Expectations

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
- caches such as `.pytest_cache/`, `.ruff_cache/`, and `__pycache__/`
- notebook checkpoints

## Credential and Network Boundaries

CI-safe validation does not require Alpaca credentials, does not call the live
Alpaca API, and does not add network-dependent tests.

Live ingestion is different. It requires local Alpaca credentials supplied
through local environment variables or a local `.env` file. Never commit
credential values, token files, or local environment files.

## Windows Troubleshooting

If PowerShell blocks virtual environment activation, enable script execution for
your user account or activate the environment from a shell that permits local
activation scripts.

If `fintech-ingest-corporate-actions` is not found after install, run:

```powershell
python scripts/validate.py
```

The wrapper handles common Windows console-script PATH friction by resolving the
active Python scripts directory. You can also use module invocations when PATH is
confusing:

```powershell
python -m src.cli.ingest_corporate_actions --help
```

Avoid adding local machine paths to docs, configs, examples, or tests. Use
repository-relative paths instead.

## macOS/Linux Troubleshooting

Make sure `python` is the interpreter from the active virtual environment:

```bash
python --version
python -m pip --version
```

Use `python -m pip` instead of bare `pip` to avoid installing into a different
environment. If installed scripts are stale or point at the wrong interpreter,
recreate `.venv` and reinstall with:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

After local builds, run the cleanup commands above and check `git status
--porcelain` before committing.

## Publishing Boundary

Ordinary CI does not publish packages. Local validation and wheel smoke checks
do not publish packages.

TestPyPI publishing remains manual and gated through
`.github/workflows/publish-package.yml`. Real PyPI publishing remains out of
scope unless separately approved.
