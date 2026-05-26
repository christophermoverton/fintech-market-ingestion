# M10 - Archive Backup Packs And Colab Restore

## M10 Principle

Archive backup packs make Colab and notebook workflows faster to resume without
making Google Drive, archive shards, or manifests a second source of truth.
Local partitioned Parquet remains the canonical working dataset after restore.

## Scope Summary

M10 adds deterministic backup-pack workflows for local filesystem paths:

- manifest contract for derived archive backup packs;
- deterministic ZIP shard writer with dry-run planning;
- local restore workflow with explicit overwrite policies;
- read-only validation and inspection APIs;
- thin CLI wrappers for pack, restore, validate, and inspect;
- Colab restore-to-local-first documentation;
- deterministic round-trip validation using synthetic fixtures.

The milestone does not change ingestion, feature, QA, analysis, or canonical
Parquet dataset layouts.

## Architecture Boundaries

- Local runtime storage is the active working layer.
- Local partitioned Parquet remains canonical working data.
- Archive backup packs are derived, non-canonical transfer artifacts.
- Mounted Google Drive is archival/checkpoint storage only.
- Package code treats Drive as an ordinary mounted filesystem path.
- No Google Drive API client is used.
- No OAuth, credentials, network access, or Drive mounting is required.
- No background sync, daemon, remote metadata service, object-store abstraction,
  or automatic repair is added.
- No live market data is required for M10 validation.

## Deterministic Artifact Expectations

Archive backup pack artifacts should be deterministic where durable:

- `manifest.json` uses sorted keys, stable ordering, UTF-8 encoding, and a
  trailing newline;
- manifest paths are portable relative POSIX-style paths;
- source file inventory is sorted by relative path;
- included datasets are sorted;
- shard names and shard metadata are sorted by shard index;
- ZIP shard members are written in deterministic order with fixed ZIP metadata;
- fixed `backup_id` and `created_at_utc` values yield equivalent manifest JSON
  and shard checksums for equivalent inputs;
- serialized manifests must not include machine-local absolute paths.

## Focused Validation Checklist

Run the M10-focused checks before release:

```bash
python -m ruff format --check src tests examples
python -m ruff check src tests examples
python scripts/check_repo_hygiene.py
```

```bash
pytest tests/test_archive_backup_manifest.py -q
pytest tests/test_archive_backup_writer.py -q
pytest tests/test_archive_backup_restore.py -q
pytest tests/test_archive_backup_validation.py -q
pytest tests/test_backup_data_cli.py -q
pytest tests/test_archive_backup_roundtrip.py -q
```

The round-trip test creates local synthetic partitioned Parquet-like fixtures,
packs them into deterministic archive shards, validates and inspects the pack,
restores into a separate local root, and compares restored checksums against
the original source files.

## Full Regression Checklist

Run the broader repository validation before tagging:

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

M10 validation must not require:

- Alpaca credentials;
- Google credentials;
- network access;
- Colab;
- a live Google Drive mount;
- live market data.

Tests use temporary local directories that model workspaces, backup roots, and
restore roots. Files use a `.parquet` extension but contain small deterministic
bytes so no Parquet engine is required for archive-pack validation.

## Colab Workflow Validation

The documented Colab workflow should keep this order:

1. Mount Drive manually only if the notebook needs it.
2. Work under local runtime storage such as `/content/fintech-market-ingestion`.
3. Validate and inspect the Drive-hosted backup pack.
4. Restore into local runtime storage such as `data/curated`.
5. Run local ingestion, feature, QA, or analysis workflows.
6. Create a fresh backup pack to mounted Drive when the session is complete.

The docs should not promote Drive-mounted folders as active Parquet working
roots, and they should not imply that backup packs are canonical datasets.

## Release Checklist

- README links to the archive manifest contract, Colab workflow guide, and this
  M10 release-readiness checklist.
- `docs/archive_backup_pack_manifest.md` documents manifest, writer, restore,
  validation, inspection, and CLI contracts.
- `docs/colab_archive_backup_restore.md` documents restore-to-local-first Colab
  usage with mounted Drive as archival storage.
- Focused M10 tests pass.
- Ruff check and format checks pass.
- Repository hygiene passes.
- `python scripts/validate.py` passes or any local tooling issue is recorded.
- Generated artifacts, `.pytest_tmp*`, build outputs, and credentials are not
  committed.

## Release Identity

- Canonical package version: `0.10.0`.
- Release tag:
  `v0.10.0-archive-backup-packs-colab-restore`.
- Release title:
  `v0.10.0 - Archive Backup Packs and Colab Restore Workflow`.
- Release branch:
  `release/m10-archive-backup-packs-colab-restore`.
- Completed issue set: #72, #73, #74, #75, #76, #77, #78, #79, #81, and #82.

## Final M10 Release Snapshot

- Focused M10 validation: passing on the release branch.
- Full regression validation: `pytest tests -q` passing with 419 tests.
- Package build validation: `python -m build --outdir
  .pytest_cache/issue82_build_dist` produced wheel and sdist artifacts for
  version `0.10.0`.
- Repository hygiene: passing.
- Local validation wrapper note: `python scripts/validate.py` requires an
  editable-installed interpreter with console scripts available. In the local
  Codex validation interpreter, it stopped before running checks because
  `fintech-ingest-corporate-actions` was unavailable.
- Boundary preserved: archive backup packs remain derived/non-canonical,
  restored local Parquet remains canonical working data, and mounted Google
  Drive remains ordinary filesystem archival storage.

## Non-Goals Preserved

M10 does not add:

- Google Drive API integration;
- Google authentication;
- automatic Drive mounting;
- background sync;
- remote metadata services;
- object-store abstractions;
- archive-pack repair;
- CLI-only behavior without Python APIs;
- live Alpaca calls;
- network access;
- credential handling;
- changes to canonical Parquet layout.

## Suggested Release Note Summary

M10 adds deterministic archive backup packs for local partitioned Parquet data,
including manifest contracts, sharded ZIP writing, local restore, validation and
inspection APIs, CLI wrappers, Colab workflow documentation, and synthetic
round-trip validation while preserving local workspace canonicality and avoiding
external service dependencies.
