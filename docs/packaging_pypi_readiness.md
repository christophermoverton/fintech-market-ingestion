# Packaging and PyPI Readiness

## Purpose

M4 makes the project installable, lintable, buildable, and ready for a future publishing process without publishing packages automatically or changing ingestion behavior.

## Packaging Strategy

- `pyproject.toml` is the source of modern packaging metadata.
- The build backend is `setuptools.build_meta`.
- The distribution name is `fintech-market-ingestion`.
- Existing `src.*` imports are preserved.
- Package discovery is configured to include `src*` namespaces from the repository root.

## Install for Development

The preferred contributor workflow is an editable install with the development dependency group:

```bash
python -m pip install -e ".[dev]"
```

## Dependency Model

- Runtime dependencies live in `[project.dependencies]`.
- Developer tooling lives in `[project.optional-dependencies].dev`.
- `requirements.txt` is an optional frozen-environment reproduction path, useful when a locked dependency set is needed, but not the primary contributor workflow.

## Validation Commands

After installing the development dependencies, run the local validation wrapper:

```bash
python scripts/validate.py
```

The wrapper mirrors the standard CI checks and runs repository hygiene checks,
local packaging checks, and quality gates:

```bash
python scripts/check_repo_hygiene.py
python -m pytest tests -q
python -m pytest tests/test_m3_corporate_actions_validation.py -q
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m py_compile src/cli/ingest_corporate_actions.py
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

These checks do not require live Alpaca credentials.

The hygiene check validates tracked files only. It fails on CRLF line endings in
normalized text files, generated or local-only files tracked by Git, obvious
local absolute paths, and obvious credential files such as `.env`. It does not
require network access or Alpaca credentials.

## Cross-Platform CI

The standard GitHub Actions workflow at `.github/workflows/ci.yml` runs the
same credential-free contributor validation path on pull requests and pushes to
`main` and `feature/m*` branches.

The CI matrix validates Python 3.10, 3.11, and 3.12 on Ubuntu, plus Python 3.12
on Windows and macOS. It installs the package with the editable development
dependency path:

```bash
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

The workflow invokes `python scripts/validate.py`, which runs the full tests,
the focused M3 corporate-actions regression tests, Ruff lint and format checks,
`py_compile`, and both corporate-actions CLI help smoke checks. It does not
publish packages and does not require live Alpaca credentials.

## CLI Smoke Checks

The corporate-actions ingestion CLI supports both invocation styles:

```bash
fintech-ingest-corporate-actions --help
python -m src.cli.ingest_corporate_actions --help
```

The installed console script delegates to the same `main()` implementation used by the module path.

## Package Build Validation

Validate source and wheel artifacts locally with:

```bash
python -m build
python scripts/smoke_test_wheel.py
tar tf dist/*.tar.gz
python -m zipfile --list dist/*.whl
```

The wheel smoke helper expects exactly one `.whl` file under `dist/`, installs
that wheel with the active Python interpreter, and runs both corporate-actions
CLI help checks. It does not publish packages and does not require live Alpaca
credentials.

On PowerShell, the artifact inspection step can also use `Expand-Archive` or `python -m zipfile --list` if `tar` is not preferred.

After inspection, clean generated outputs so the repository stays source-only:

```bash
rm -rf dist build *.egg-info
```

PowerShell alternative:

```powershell
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force *.egg-info -ErrorAction SilentlyContinue
```

## TestPyPI and PyPI Boundary

- M4 validates local packaging readiness only.
- Publishing is manual and starts with TestPyPI.
- Do not commit credentials, tokens, or API keys.
- Real PyPI publishing must be explicitly approved separately.
- Prefer credential-safe publishing patterns later, once release policy is defined.

## Secure Publishing Workflow

The manual GitHub Actions workflow at `.github/workflows/publish-package.yml` validates, builds, uploads package artifacts for review, and publishes to TestPyPI only.

The workflow trigger is manual:

```text
workflow_dispatch target=testpypi
```

The workflow has two stages:

- `validate-and-build` installs the package with `.[dev]`, runs tests, runs M3 regression validation, runs Ruff checks, runs CLI smoke checks, builds the source distribution and wheel, inspects artifact contents, and uploads `dist/` as a workflow artifact.
- `publish-testpypi` downloads the built artifacts and publishes them to TestPyPI.

The selected publishing approach is Trusted Publishing/OIDC. The workflow grants `id-token: write` only to the TestPyPI publishing job and does not store token values in YAML.

### TestPyPI Trusted Publishing Setup

Before the workflow can publish to TestPyPI, configure a trusted publisher in TestPyPI for this project:

- Repository owner: `christophermoverton`
- Repository name: `fintech-market-ingestion`
- Workflow filename: `publish-package.yml`
- Environment name: `testpypi`

If the TestPyPI project does not exist yet, create the project or follow TestPyPI's pending-publisher flow before running the workflow.

### Token Fallback

Trusted Publishing/OIDC is preferred. If token-based publishing is required as a fallback, create the token outside the repository and add it only as a GitHub Actions repository secret:

```text
Repository Settings -> Secrets and variables -> Actions -> New repository secret
```

Recommended secret name for TestPyPI:

```text
TEST_PYPI_API_TOKEN
```

Optional future secret name for real PyPI, only after explicit approval:

```text
PYPI_API_TOKEN
```

Never paste token values into source files, docs, issues, comments, workflow YAML, or logs. The current workflow does not reference token secrets because it is configured for Trusted Publishing.

### Real PyPI Boundary

The workflow does not include a real PyPI target. TestPyPI must be validated first. Real PyPI publishing should be added only after explicit release approval and should prefer Trusted Publishing/OIDC or a protected environment with required reviewers.

## Safety Checklist

- No `.env` files are required for the packaging checks.
- No generated data is required for the packaging checks.
- No artifacts or reports should be committed.
- No caches should be committed.
- No virtual environments should be committed.
- No credentials should be documented or stored here.
