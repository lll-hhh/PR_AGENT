# Contribution Monitor

A Windows desktop dashboard for reviewing GitHub pull-request status and accepted contribution history. It can group PRs by action needed, waiting for review, and merged; show repository candidates; and summarize contribution activity.

The monitor reads GitHub data only. It does not create issues or PRs, post comments, merge changes, or sign CLAs. It uses `GH_TOKEN`/`GITHUB_TOKEN` or the existing Git Credential Manager login when available. Credentials are held in memory for requests and are not included in snapshots.

## Requirements

- Windows 10 or later
- Python 3.11 or later
- GitHub access; authenticated access is recommended to avoid low anonymous API limits

Set `PR_MONITOR_ACCOUNT` to your GitHub login before starting the app. The initial repository categories are maintained in `merge_monitor/assets/`. User refresh rules and cached snapshots are stored under `%LOCALAPPDATA%\MergeMonitor`.

## Run from source

From the `app/` directory:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
$env:PR_MONITOR_ACCOUNT = "your-github-login"
.venv\Scripts\python.exe main.py
```

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

The test suite uses mocked GitHub responses and does not require a token or network access.

## Package a Windows executable

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean Merge.spec
```

The generated files are local build artifacts and are not committed.

