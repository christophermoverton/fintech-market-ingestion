# M11 Merge and Release Readiness

Milestone 11 final merge-readiness report for
`feature/m11-colab-data-sessions-archive-restore-ux` targeting `main`.

## Milestone Scope

M11 improves Colab notebook ergonomics and fintech-side readiness workflows for
StratLake handoff while preserving canonical-data boundaries.

Completed issues in this milestone:

- #83
- #84
- #85
- #86
- #87
- #88
- #89
- #90
- #91

## Branch and Git State

Recorded merge-readiness branch checks:

- active branch: `feature/m11-colab-data-sessions-archive-restore-ux`
- target branch: `main`
- fetched remotes: `git fetch origin`
- recent history reviewed with `git log --oneline --decorate --max-count=20`
- milestone diff reviewed with `git diff --name-status main...HEAD`
- working tree clean at final readiness validation stage

## Final Checklist

- [x] Colab profile docs reviewed.
- [x] `fintech-init-project --colab-profile` command surface validated.
- [x] Pre-restore `fintech-notebook-doctor` checks reviewed.
- [x] Restore-first `validate` / `inspect` / `restore` docs reviewed.
- [x] Post-restore dataset-doctor examples reviewed.
- [x] QA recipe reviewed.
- [x] Handoff report generation and deterministic behavior reviewed.
- [x] End-of-session session-save versus archive-pack distinction reviewed.
- [x] Docs/path hygiene passes.
- [x] Examples avoid accidental notebook CWD reliance.
- [x] Docs avoid Drive-as-canonical wording.
- [x] Docs avoid hidden sync, Google API/OAuth behavior, or automatic restore.
- [x] Docs avoid implying automatic StratLake execution.
- [x] Live credentials required only for explicitly optional live-data paths.

## Version and Build Metadata

- package version updated to `0.11.0` in `pyproject.toml`
- M11 release entry added to `CHANGELOG.md`
- README release highlights updated with M11 summary

## Validation Evidence

All commands below were run from the project virtual environment using the
`python` command.

### Required Validation Commands

```bash
git diff --check
python scripts/check_repo_hygiene.py
python scripts/validate.py
python examples/project_session_quickstart.py --output-root .pytest_tmp_m11_merge_readiness_quickstart
python -m src.cli.init_project --help
python -m src.cli.notebook_doctor --help
python -m src.cli.backup_data --help
python -m src.ingestion.qa_export --help
python -m src.cli.stratlake_handoff_report --help
python -m src.cli.save_session --help
python -m src.cli.restore_session --help
git status --short --ignored .pytest_tmp*
git ls-files .pytest_tmp*
```

Result summary:

- all required command checks passed
- `scripts/validate.py` passed (including full test suite and Ruff checks over
	`src tests examples`)
- merge-readiness quickstart executed successfully
- `.pytest_tmp_m11_merge_readiness_quickstart/` exists locally as ignored output
- `git ls-files .pytest_tmp*` returned no tracked temp output

Non-blocking note:

- local `git status --ignored .pytest_tmp*` printed warnings for some
	permission-denied temp directories outside this readiness run; these were
	not tracked and did not block readiness checks.

## Architecture Boundaries Preserved

- local partitioned Parquet remains canonical working data
- mounted Google Drive remains filesystem persistence/archive storage only
- archive packs remain derived/non-canonical transfer artifacts
- handoff reports remain derived/non-canonical diagnostic metadata
- notebook doctor remains read-only
- no hidden sync, Google API/OAuth, automatic Drive mount behavior,
	restore-on-import, background sync, or StratLake execution behavior added

## Final Readiness Assessment

M11 is ready for PR to `main` pending normal reviewer approval.

## Release Identity

- Canonical package version: `0.11.0`.
- Release tag: `v0.11.0-colab-notebook-ergonomics-qa-doctor-stratlake-handoff`.
- Release title: `v0.11.0 - Colab Notebook Ergonomics, QA, Doctor, and StratLake Handoff`.
- Release branch: `feature/m11-colab-data-sessions-archive-restore-ux`.
- Target branch: `main`.

## PR Draft

### Title

`M11 — Colab Notebook Ergonomics, Archive Restore, QA, and StratLake Handoff`

### Body

```markdown
## Summary

Implements Milestone 11, improving Colab/notebook ergonomics for fintech-market-ingestion as the upstream data provider for StratLake Trade Engine.

## Major Changes

- Added reusable Colab data-session profile documentation.
- Added `fintech-init-project --colab-profile`.
- Added read-only `fintech-notebook-doctor`.
- Added restore-first archive backup pack workflow docs.
- Added post-restore QA validation recipe.
- Added derived/non-canonical StratLake handoff report.
- Added deterministic handoff report behavior.
- Added M11 end-to-end Colab fintech-to-StratLake workflow guide.
- Added M11 release-readiness checklist.
- Fixed CI hygiene for handoff report files.
- Completed final M11 merge/release-readiness validation and version/docs alignment.

## Completed Issues

Closes #83
Closes #84
Closes #85
Closes #86
Closes #87
Closes #88
Closes #89
Closes #90
Closes #91

## Validation

- `git diff --check`
- `python scripts/check_repo_hygiene.py`
- `python scripts/validate.py`
- `python examples/project_session_quickstart.py --output-root .pytest_tmp_m11_merge_readiness_quickstart`
- `python -m src.cli.init_project --help`
- `python -m src.cli.notebook_doctor --help`
- `python -m src.cli.backup_data --help`
- `python -m src.ingestion.qa_export --help`
- `python -m src.cli.stratlake_handoff_report --help`
- `python -m src.cli.save_session --help`
- `python -m src.cli.restore_session --help`
- `git status --short --ignored .pytest_tmp*`
- `git ls-files .pytest_tmp*`

## Architecture Boundaries Preserved

- Local partitioned Parquet remains canonical working data.
- Drive remains mounted filesystem persistence/archive storage only.
- Archive packs and handoff reports remain derived/non-canonical.
- Notebook doctor is read-only.
- No hidden sync, Google API/OAuth, Drive mounting, restore automation, background sync, or StratLake execution was added.
- Fintech validates/source-prepares curated data; StratLake owns downstream feature/research workflows.

## StratLake Reference

This fintech milestone is intended to pair with StratLake’s upcoming/parallel notebook milestone, likely StratLake M44, focused on notebook session ergonomics, Google Drive archive restore/use, local runtime roots, restored MarketLake root validation, and downstream feature/research workflow readiness.

Fintech M11 provides:

- local curated data root
- archive restore pattern
- QA evidence
- handoff report

StratLake M44 or equivalent should consume:

- `CURATED_ROOT` as `MARKETLAKE_ROOT` / `--marketlake-root`
- fintech handoff report as diagnostic metadata only
- local restored Parquet as source MarketLake data

StratLake should not treat Drive backup packs or fintech handoff metadata as canonical. It should validate its own requested universe/date/timeframe and preserve StratLake’s artifact-driven research boundaries.
```
