# Google Drive Mounted-Path Persistence

M9.4 adds a Google Drive persistence adapter for notebook and cloud workflows.
The adapter operates over an already-mounted filesystem path. It does not use
the Google Drive API, authenticate, mount Drive, or run background sync.

In Colab, mount Drive yourself first:

```python
from google.colab import drive

drive.mount("/content/drive")
```

Then choose a mounted directory for project-session transport artifacts:

```text
/content/drive/MyDrive/fintech-market-ingestion/<session_name>
```

Instantiate the adapter with that mounted path:

```python
from pathlib import Path

from src.persistence import GoogleDrivePersistenceAdapter

drive_root = Path("/content/drive/MyDrive/fintech-market-ingestion/demo")
adapter = GoogleDrivePersistenceAdapter(drive_root)
```

If you are using a local or already-mounted target that should be created when
missing, pass `create_root=True`:

```python
adapter = GoogleDrivePersistenceAdapter(drive_root, create_root=True)
```

`create_root=True` creates directories only on the local mounted filesystem. It
does not mount Google Drive and does not authenticate.

## Boundary

The adapter is a transport utility. It can explicitly create directories, copy
files into the mounted path, read files back out, check existence, and list files
under adapter-relative prefixes. It does not decide which project files should
be saved and does not make Drive copies canonical.

Use save plans to inspect selected files before any copy operation.

M9.5 adds save/restore CLIs that can use the mounted-path adapter explicitly:

```bash
fintech-save-session \
  --root . \
  --session-id <session_id> \
  --adapter google-drive \
  --destination "/content/drive/MyDrive/fintech-market-ingestion/<session_name>" \
  --include configs artifacts reports

fintech-restore-session \
  --root . \
  --adapter google-drive \
  --source "/content/drive/MyDrive/fintech-market-ingestion/<session_name>" \
  --dry-run
```

The commands still do not mount Drive, authenticate, use Google APIs, or run
background sync. Restore refuses to overwrite local files unless `--force` is
passed.

For Drive targets, start with conservative policies such as `metadata_only` or
`artifacts_and_reports`:

```bash
fintech-save-session \
  --root . \
  --session-id <session_id> \
  --policy artifacts_and_reports \
  --adapter google-drive \
  --destination "/content/drive/MyDrive/fintech-market-ingestion/<session_name>" \
  --dry-run
```

In Colab, a typical mounted-path quickstart is:

```python
from google.colab import drive

drive.mount("/content/drive")
```

Then preview the export before copying:

```bash
fintech-save-session \
  --root /content/fintech-market-ingestion-demo \
  --session-id <session_id> \
  --policy artifacts_and_reports \
  --adapter google-drive \
  --destination "/content/drive/MyDrive/fintech-market-ingestion/<session_name>" \
  --dry-run
```

Remove `--dry-run` only after reviewing the selected policy, include roots,
exclude roots, file count, and total bytes. The package still does not import
`google.colab`, mount Drive, authenticate, use Google APIs, or run sync work.

Curated 1-minute bars can be large and require both `--include-curated-data` and
`--include-1m-data`. Persisted Drive copies remain export/restore surfaces, not
canonical data.

Curated data should remain opt-in in later save policies. Drive copies are
export/restore aids, not the source of truth for curated data, research outputs,
QA artifacts, reports, or session manifests.

## Testing

The test suite simulates a mounted Drive path with temporary directories. Tests
do not require Google credentials, Colab, network access, a live Drive mount, or
Alpaca credentials/data.
