# M9 - Portable Project Sessions and Google Drive Persistence

## M9 Principle

Project sessions should make notebook and cloud workflows easy to resume,
persist, and export without making Google Drive, notebooks, or derived backups
the canonical source of truth.

## Scope Summary

M9 adds a deterministic, metadata-first session workflow for local, notebook,
and mounted-filesystem environments:

- portable project-session manifests under `artifacts/sessions/<session_id>/`
- opt-in session-aware `fintech-init-project` bootstrap
- explicit local and mounted-path persistence adapters
- deterministic save plans and save/restore manifests
- conservative `fintech-save-session` and `fintech-restore-session` commands
- named save policies with curated-data and 1-minute-data guardrails
- a CI-safe notebook-style quickstart example

The milestone does not change ingestion, backfill, or Alpaca data semantics.

## Architecture Boundaries

- Canonical local project files remain the source of truth during runtime.
- Session manifests are metadata artifacts.
- Save manifests and restore manifests are audit artifacts.
- Local and Google Drive persistence adapters are transport utilities.
- Mounted-path Google Drive copies are export/restore aids only.
- No Google API client is used.
- No authentication is performed by package code.
- No Drive mounting is performed by package code.
- No background sync is performed.
- No remote metadata service, database, or canonical registry is added.
- No live market data, Alpaca credentials, or network access is required for
  M9 validation.

## Canonical vs Transport Surfaces

The local workspace created by `fintech-init-project` remains the primary
runtime view:

```text
configs/
data/
reports/
artifacts/
notebooks/
```

Persistence destinations such as `artifacts/session_exports/<session_id>` or
`/content/drive/MyDrive/fintech-market-ingestion/<session_name>` are transport
surfaces. They can help resume or export a notebook workflow, but they do not
become authoritative stores for curated data, research outputs, reports,
artifacts, or session metadata.

## Deterministic Artifact Expectations

M9 JSON artifacts should be deterministic where they are durable:

- session manifests use sorted keys, stable indentation, UTF-8 encoding, and a
  trailing newline
- durable manifest paths are workspace-relative and POSIX-style where possible
- save plans sort selected files deterministically
- save manifests record resolved policy metadata, include roots, exclude roots,
  file counts, total bytes, and file statuses
- restore manifests record planned/restored/skipped statuses, collision counts,
  and forced overwrite counts
- dry-run commands should not write files or manifests unless explicitly
  documented by a future workflow

## Focused Validation Checklist

Run the M9-focused checks before release:

```bash
ruff check src/sessions src/persistence src/cli tests examples
ruff format --check src/sessions src/persistence src/cli tests examples
```

```bash
pytest tests/test_session_manifest.py \
  tests/test_init_project.py \
  tests/test_session_save_plan.py \
  tests/test_session_save_policy.py \
  tests/test_persistence_local_adapter.py \
  tests/test_google_drive_adapter.py \
  tests/test_save_session_cli.py \
  tests/test_restore_session_cli.py -q
```

```bash
python examples/project_session_quickstart.py --output-root artifacts/examples/project_session_quickstart
python scripts/check_repo_hygiene.py
```

## Full Regression Checklist

Run the broader release checks before tagging:

```bash
pytest tests -q
python scripts/validate.py
python -m build
```

`python scripts/validate.py` should pass in an editable-installed environment
where development dependencies and console scripts are available. `python -m
build` requires the `build` package to be installed in the active environment.
If either command fails because local tooling is missing, record the exact
environment reason separately from any code failure.

## External Service Independence

M9 validation must not require:

- Alpaca credentials
- Google credentials
- network access
- Colab
- a live Google Drive mount
- live market data

The quickstart uses tiny synthetic files. Google Drive tests simulate mounted
paths with temporary directories.

## Google Drive Mounted-Path Boundaries

The Google Drive adapter works over an already-mounted filesystem path. It does
not import `google.colab`, mount Drive, authenticate, call Google APIs, or run
background sync.

Tests for `GoogleDrivePersistenceAdapter` should continue to use `tmp_path`
directories that look like mounted Drive paths. Live Drive mounts are manual
notebook concerns, not release validation requirements.

## Curated-Data Guardrail Validation

Save policies should preserve conservative defaults:

- `metadata_only`, `artifacts_and_reports`, and `research_outputs` exclude
  `data/curated`
- curated policies require `--include-curated-data`
- known 1-minute curated paths require `--include-1m-data` in addition to
  curated-data opt-in
- `all_selected` honors explicit include roots but still applies curated and
  1-minute guardrails
- CLI output and save manifests show policy name, include roots, exclude roots,
  curated-data inclusion, and 1-minute-data inclusion

## Save/Restore Safety Validation

Save behavior should remain explicit:

- save commands build an inspectable plan before copying
- `--dry-run` copies no files and writes no manifests
- curated data is excluded by default
- source files are not mutated by persistence adapters

Restore behavior should remain conservative:

- `--dry-run` writes no files
- existing workspace files are not overwritten unless `--force` is passed
- forced overwrites are reported as `restored_overwrite`
- restore manifests include `overwritten_file_count`
- restore never deletes local files

## Notebook/Colab Quickstart Validation

The quickstart script should remain runnable without credentials or network:

```bash
python examples/project_session_quickstart.py --output-root artifacts/examples/project_session_quickstart
```

It should:

- write only under the configured output root
- initialize a workspace with a session manifest
- create deterministic synthetic config, report, artifact, and research files
- save locally with `--policy artifacts_and_reports`
- run a restore dry-run into a fresh check root
- leave optional Google Drive behavior behind `--google-drive-root`
- require `--write-google-drive` before copying to the mounted Drive target

## Release Checklist

- README links to M9 project-session docs and readiness notes.
- `docs/project_sessions.md` describes session, save/restore, and policy
  boundaries.
- `docs/google_drive_persistence.md` documents mounted-path-only behavior.
- `docs/notebook_pip_install_guide.md` includes notebook-oriented session
  commands.
- `examples/project_session_quickstart.py` runs with local synthetic data only.
- Focused M9 tests pass.
- Full tests pass.
- Ruff check and format checks pass.
- Repository hygiene passes.
- `python scripts/validate.py` passes or any local tooling issue is recorded.
- `python -m build` succeeds or any local tooling issue is recorded.
- Generated artifacts, `.pytest_tmp*`, build outputs, and credentials are not
  committed.

## Known Environment Notes

- Some local checkouts may have a stale virtual-environment launcher. Use the
  active Python interpreter that has the development dependencies installed.
- `python scripts/validate.py` expects editable-install console scripts to be
  available for the active interpreter.
- `python -m build` requires the `build` package; install development
  dependencies with `python -m pip install -e ".[dev]"` before package
  validation.
- Quickstart output under `artifacts/examples/project_session_quickstart` is
  generated validation output and should remain untracked.

## Non-Goals Preserved

M9 does not add:

- Google Drive API integration
- Google authentication
- automatic Drive mounting
- background sync
- remote metadata services
- databases or indexes
- canonical artifact registries
- implicit save/restore behavior
- live Alpaca calls
- network access
- credential handling
- broad data lifecycle or retention policy

## Suggested Tag/Release Note Summary

M9 adds portable project sessions, deterministic session/save/restore manifests,
local and mounted-path persistence adapters, explicit save/restore commands,
curated-data guardrails, and a notebook-friendly quickstart while preserving
local workspace canonicality and avoiding external service dependencies.

## Final M9 Release Snapshot (Issue 70)

- Release intent: finalize M9 documentation and versioning for
  `v0.9.0-portable-project-sessions-google-drive-persistence`.
- Canonical package version: `0.9.0`.
- Focused M9 validation: run and passing on the release branch.
- Full regression validation: run and passing on the release branch.
- Packaging validation: `python -m build` produces wheel and sdist artifacts.
- Repository hygiene: passing.
- Boundary preserved: persistence remains explicit transport/export behavior,
  local workspaces remain canonical, and package code does not mount Drive,
  authenticate, call Google APIs, or run background sync.
