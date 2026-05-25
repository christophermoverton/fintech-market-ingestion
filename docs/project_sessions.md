# Project Sessions

Project sessions are a portable metadata contract for notebook and cloud
workflows built on top of the existing `fintech-init-project` workspace model.
A session manifest describes an initialized workspace, package/runtime metadata,
workspace-relative project paths, selected persistence adapter settings, and an
explicit save policy.

The manifest is intentionally small. It is JSON, deterministic, and designed to
move between local folders, notebook runtimes, and mounted filesystems without
recording machine-local absolute paths in durable fields.

## What a Project Session Is

- A description of the current project workspace layout.
- A portable record of relative paths such as `configs/`, `data/curated/`,
  `data/research/`, `artifacts/`, `reports/`, and `notebooks/`.
- A place to declare persistence intent, such as adapter name and destination,
  without performing sync or restore work.
- A save-policy record that defaults to metadata-only behavior and excludes
  curated data unless explicitly opted in by a later workflow.

## What a Project Session Is Not

- It is not a server, database, remote metadata service, or background sync
  process.
- It is not a second canonical artifact registry.
- It is not an ingestion, backfill, or QA execution command.
- It does not require Alpaca credentials, Google credentials, Google Drive,
  Colab, notebooks, or network access.

## Persistence Boundary

The M9 principle is that project sessions should make notebook and cloud
workflows easy to resume, persist, and export without making Google Drive,
notebooks, or derived backups the canonical source of truth.

The local workspace remains the primary runtime view. Persistence copies, mounted
paths, Drive folders, exported manifests, and future save/restore bundles are
secondary transport or recovery aids. They should not redefine which curated
datasets, research outputs, reports, or artifacts are canonical.

## Current Manifest Contract

The initial manifest schema records:

- `schema_version`
- `session_id`
- `session_name`
- `created_at_utc`
- package `name` and `version`
- workspace `root_semantics` and workspace-relative `paths`
- persistence `adapter`, `destination`, and runtime-only settings
- save-policy `mode`, `include`, `exclude`, and `include_curated_data`

Durable paths are workspace-relative wherever possible. Absolute local paths and
Windows drive-qualified paths are rejected in durable path fields unless a later
workflow stores them under an explicit runtime-only section.

## Session-Aware Bootstrap

Project-session creation is opt-in during workspace bootstrap:

```bash
fintech-init-project --root . --notebooks --with-session --session-name demo
```

This preserves the normal `fintech-init-project` behavior and additionally
writes:

```text
artifacts/sessions/<session_id>/session_manifest.json
```

The generated manifest is metadata only. Session initialization does not copy
curated data, does not copy research data, does not run save/restore behavior,
and does not execute persistence adapters. Google Drive behavior is not
implemented by session-aware bootstrap.

Each `--with-session` bootstrap represents a new portable project session and
creates a new timestamped manifest by default. Existing session manifests are
not overwritten; if the same computed manifest path already exists, the write is
reported as skipped. Explicit session reuse, selection, and restore behavior are
deferred to later M9 save/restore work.

## Current Deferrals

This contract layer does not yet implement Google Drive mount handling,
save/restore commands, background sync, or expanded curated-data policy
enforcement. Those behaviors belong to later M9 issues and should build on this
manifest contract without changing ingestion or backfill semantics.

## Local Persistence Foundation

M9.3 adds a small persistence adapter interface and a local filesystem adapter
for explicit project-session file transport. The adapter copies, reads, lists,
and creates directories only when called directly. It does not run in the
background, discover canonical artifacts, or decide which files should be saved.

Save plans provide the inspectable selection step before copying. A save plan
walks explicit workspace-relative include paths, removes excluded paths, records
file-only entries, and serializes deterministic JSON with sorted entries and
stable formatting. An empty include list produces an empty plan; no files are
selected by default.

This foundation is local and CI-safe. It does not implement Google Drive,
save/restore CLI behavior, session restore, background sync, remote metadata,
or a canonical artifact registry. Persisted copies remain transport artifacts,
not the source of truth.
