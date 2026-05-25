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

Durable paths are workspace-relative wherever possible. Absolute local paths are
rejected in durable path fields unless a later workflow stores them under an
explicit runtime-only section.

## Current Deferrals

This contract layer does not yet implement session-aware bootstrap, Google Drive
mount handling, save/restore commands, background sync, or expanded curated-data
policy enforcement. Those behaviors belong to later M9 issues and should build
on this manifest contract without changing ingestion or backfill semantics.
