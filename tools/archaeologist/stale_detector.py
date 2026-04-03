"""Detect files that have not been modified for a long time."""
from __future__ import annotations

import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from tools.archaeologist.models import StaleFile

# File extensions / dirs to always skip
_EXCLUDE_DIRS = {
    "node_modules", ".venv", "bin/venv", "deploy-offline",
    "__pycache__", ".next", ".git",
}
_EXCLUDE_EXTENSIONS = {".lock"}
_EXCLUDE_FILENAMES = {"package.json", "tsconfig.json"}


def _should_exclude(rel_path: str, extra_patterns: Optional[List[str]] = None) -> bool:
    """Return True if the file should be skipped."""
    parts = Path(rel_path).parts
    for part in parts:
        if part in _EXCLUDE_DIRS:
            return True
        if extra_patterns:
            for pat in extra_patterns:
                if pat in part:
                    return True

    name = Path(rel_path).name
    suffix = Path(rel_path).suffix

    if suffix in _EXCLUDE_EXTENSIONS:
        return True
    if name in _EXCLUDE_FILENAMES:
        return True
    # Skip generated / config JSON files
    if suffix == ".json":
        return True
    return False


def _last_modify_ts(repo_path: str, file_path: str) -> Optional[int]:
    """Get the unix timestamp of the last commit that modified `file_path`."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%at", "--diff-filter=M", "--", file_path],
            capture_output=True, text=True, cwd=repo_path, timeout=30,
        )
        ts = result.stdout.strip()
        if ts:
            return int(ts)
    except (subprocess.TimeoutExpired, ValueError):
        pass

    # Fallback: first commit touching the file (for files never modified after creation)
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%at", "--", file_path],
            capture_output=True, text=True, cwd=repo_path, timeout=30,
        )
        ts = result.stdout.strip()
        if ts:
            return int(ts)
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def find_stale_files(
    repo_path: str,
    days_threshold: int = 180,
    exclude_patterns: Optional[List[str]] = None,
) -> List[StaleFile]:
    """Return files whose last git-modification is older than *days_threshold* days."""
    repo = Path(repo_path).resolve()

    # List tracked files
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=str(repo), timeout=60,
    )
    if result.returncode != 0:
        return []

    cutoff = datetime.now() - timedelta(days=days_threshold)
    cutoff_ts = int(cutoff.timestamp())
    stale: List[StaleFile] = []

    for line in result.stdout.strip().splitlines():
        rel = line.strip()
        if not rel:
            continue
        if _should_exclude(rel, exclude_patterns):
            continue
        # Only scan actual source files
        if not (repo / rel).is_file():
            continue

        ts = _last_modify_ts(str(repo), rel)
        if ts is None:
            continue
        if ts < cutoff_ts:
            mod_date = date.fromtimestamp(ts)
            days = (date.today() - mod_date).days
            stale.append(StaleFile(path=rel, last_modified_date=mod_date, days_stale=days))

    stale.sort(key=lambda f: f.days_stale, reverse=True)
    return stale
