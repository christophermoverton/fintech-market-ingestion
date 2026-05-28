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

This contract layer still defers Google Drive mount handling, background sync,
and broader data lifecycle or retention policy enforcement. Future behavior
should build on the manifest contract, mounted-path adapters, explicit
save/restore commands, and current curated-data guardrails without changing
ingestion or backfill semantics. Persisted copies remain transport or export
artifacts, not canonical data.

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

This foundation is local and CI-safe. It now underpins explicit save/restore
CLI workflows and a Google Drive mounted-path adapter, while remaining a
transport utility only. It does not call Google Drive APIs, authenticate,
mount Drive, run background sync, manage remote metadata, or provide a
canonical artifact registry. Persisted copies remain transport artifacts, not
the source of truth.

## Google Drive Mounted-Path Adapter

M9.4 adds a Google Drive adapter that works only over an already-mounted
filesystem path, such as `/content/drive/MyDrive/...` in Colab. It reuses the
same explicit persistence operations as the local adapter and remains a
transport utility only. It does not mount Drive, authenticate, call Google APIs,
run background sync, or make Drive copies canonical.

See [google_drive_persistence.md](google_drive_persistence.md) for mounted-path
usage and boundaries.

## Explicit Save And Restore

M9.5 adds explicit save and restore commands. They are dry-run friendly and use
the persistence adapters as transport utilities only.

Save selected local paths to a local destination:

```bash
fintech-save-session \
  --root . \
  --session-id <session_id> \
  --adapter local \
  --destination artifacts/session_exports/<session_id> \
  --include configs artifacts reports
```

Save selected paths to an already-mounted Google Drive path:

```bash
fintech-save-session \
  --root . \
  --session-id <session_id> \
  --adapter google-drive \
  --destination "/content/drive/MyDrive/fintech-market-ingestion/<session_name>" \
  --include configs artifacts reports
```

Preview a restore without writing files:

```bash
fintech-restore-session \
  --root . \
  --adapter local \
  --source artifacts/session_exports/<session_id> \
  --dry-run
```

Restore and allow overwrites only when explicitly requested:

```bash
fintech-restore-session \
  --root . \
  --adapter local \
  --source artifacts/session_exports/<session_id> \
  --force
```

Save writes `session_save_manifest.json` under the destination root when files
are copied. Restore writes
`artifacts/restores/<restore_id>/restore_manifest.json` when restore is
executed. Dry-run mode does not write files or manifests.

Restore refuses to overwrite existing local files unless `--force` is passed,
and it never deletes local files. Curated data under `data/curated` is excluded
from save plans by default; saving it requires the explicit
`--include-curated-data` flag and an include path that selects it. Persisted
copies remain transport artifacts, not canonical data.
Restore manifests distinguish normal restores from forced overwrites using
`restored` and `restored_overwrite` file statuses, with
`overwritten_file_count` reporting forced replacements.

## Save Policies

M9.6 adds named save policies for explicit session persistence:

| Policy | Intent |
| --- | --- |
| `metadata_only` | Save lightweight session metadata and configs only. |
| `artifacts_and_reports` | Save `artifacts/`, `reports/`, and `configs/` while excluding curated data. |
| `research_outputs` | Save `data/research/` plus artifacts, reports, and configs while excluding curated data. |
| `corporate_actions` | Save curated corporate-action outputs without broadly selecting OHLCV bars. Requires `--include-curated-data`. |
| `curated_daily_bars` | Save curated daily bars only. Requires `--include-curated-data`. |
| `curated_1m_bars` | Save curated 1-minute bars only. Requires both `--include-curated-data` and `--include-1m-data`. |
| `all_selected` | Honor explicit `--include` paths with curated and 1-minute guardrails. |

`fintech-save-session` defaults to `all_selected`, preserving explicit include
behavior. A policy can be combined with extra `--include` paths, and resolved
include/exclude roots are printed by the CLI and recorded in
`session_save_manifest.json`.
User-provided `--exclude` roots are additive and do not remove the default
curated-data guardrail unless `--include-curated-data` is explicitly provided.

Curated data remains excluded by default. `--include-curated-data` is required
before curated paths can be saved. Known curated 1-minute paths such as
`data/curated/bars_1m` require the additional `--include-1m-data` flag because
these datasets can be large. Run `--dry-run` before saving large datasets to
inspect selected roots, file count, and total bytes.

## Notebook / Colab Quickstart

For a CI-safe notebook-style walkthrough that requires no credentials, network
access, live market data, Colab runtime, or Google Drive mount, run:

```bash
python examples/project_session_quickstart.py --output-root artifacts/examples/project_session_quickstart
```

The quickstart writes only under the configured `--output-root`. It initializes
a workspace with `--with-session`, locates the generated
`artifacts/sessions/<session_id>/session_manifest.json`, writes tiny synthetic
files under `configs/`, `reports/`, `artifacts/quickstart/`, and
`data/research/`, saves locally with `--policy artifacts_and_reports`, and runs
a restore dry-run into a fresh check root.

For Colab notebooks, first define the data-session profile in
[notebook_pip_install_guide.md](notebook_pip_install_guide.md). The equivalent
profile-driven shell flow is:

```python
!fintech-init-project \
  --root "{FINTECH_ROOT}" \
  --notebooks \
  --with-session \
  --session-name colab-demo

!fintech-save-session \
  --root "{FINTECH_ROOT}" \
  --session-id "<session_id>" \
  --policy artifacts_and_reports \
  --adapter google-drive \
  --destination "{SESSION_EXPORT_ROOT}" \
  --dry-run

!fintech-restore-session \
  --root "{FINTECH_ROOT / 'restore_dry_run_check'}" \
  --adapter google-drive \
  --source "{SESSION_EXPORT_ROOT}" \
  --dry-run
```

Optional mounted-path Google Drive export should start as a dry-run:

```bash
python examples/project_session_quickstart.py \
  --output-root /content/fintech-market-ingestion-demo \
  --google-drive-root /content/drive/MyDrive/fintech-market-ingestion/demo
```

Add `--write-google-drive` only when that path is already mounted and you
intend to copy files. The package does not mount Drive, import `google.colab`,
authenticate, call Google APIs, or perform background sync.

### Troubleshooting

- Missing Google Drive root: mount Drive in Colab first, or use a local path
  with explicit create-root behavior where the command supports it.
- Restore refuses to overwrite files: rerun with `--dry-run` to inspect
  collisions, then use `--force` only when replacement is intentional.
- Unexpected large save plan: use `metadata_only` or `artifacts_and_reports`;
  curated data requires `--include-curated-data`, and 1-minute curated data
  requires `--include-1m-data`.
- Missing session ID: inspect
  `artifacts/sessions/<session_id>/session_manifest.json` under the workspace
  created by `fintech-init-project --with-session`.
