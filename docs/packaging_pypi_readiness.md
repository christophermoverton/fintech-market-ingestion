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

Run the local packaging and quality gates with:

```bash
pytest tests -q
pytest tests/test_m3_corporate_actions_validation.py -q
ruff check src tests examples
ruff format --check src tests examples
python -m build
python -m src.cli.ingest_corporate_actions --help
fintech-ingest-corporate-actions --help
```

These checks do not require live Alpaca credentials.

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
tar tf dist/*.tar.gz
python -m zipfile --list dist/*.whl
```

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
- No publishing happens automatically.
- Do not commit credentials, tokens, or API keys.
- Future publishing must be explicitly approved.
- Prefer credential-safe publishing patterns later, once release policy is defined.

## Safety Checklist

- No `.env` files are required for the packaging checks.
- No generated data is required for the packaging checks.
- No artifacts or reports should be committed.
- No caches should be committed.
- No virtual environments should be committed.
- No credentials should be documented or stored here.