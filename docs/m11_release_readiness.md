# M11 Release Readiness

Checklist for M11 Colab fintech-to-StratLake lifecycle documentation quality.

- [ ] Colab profile docs reviewed.
- [ ] `fintech-init-project --colab-profile` smoke check reviewed.
- [ ] Pre-restore `fintech-notebook-doctor` smoke check reviewed.
- [ ] Restore-first `validate` / `inspect` / `restore` docs reviewed.
- [ ] Post-restore dataset doctor examples reviewed.
- [ ] QA recipe reviewed.
- [ ] Handoff report generation reviewed.
- [ ] End-of-session session-save versus archive-pack distinction reviewed.
- [ ] Docs/path hygiene passes.
- [ ] Examples avoid accidental notebook CWD reliance.
- [ ] Docs avoid Drive-as-canonical wording.
- [ ] Docs avoid hidden sync, Google API/OAuth behavior, or automatic restore.
- [ ] Docs avoid implying automatic StratLake execution.
- [ ] Live credentials required only for explicitly optional live-data paths.

## Validation Commands

```bash
git diff --check
python scripts/check_repo_hygiene.py
python scripts/validate.py
python examples/project_session_quickstart.py --output-root .pytest_tmp_issue89_quickstart
```

## Command Surface Checks

```bash
python -m src.cli.init_project --help
python -m src.cli.notebook_doctor --help
python -m src.cli.backup_data --help
python -m src.ingestion.qa_export --help
python -m src.cli.stratlake_handoff_report --help
python -m src.cli.save_session --help
python -m src.cli.restore_session --help
```
