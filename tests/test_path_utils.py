"""Tests for src/openclaw/path_utils.py — centralized path resolution."""
import os
from pathlib import Path

import pytest


def test_get_repo_root_returns_directory_containing_src(monkeypatch):
    """get_repo_root() should return the repo root which contains a 'src' directory."""
    monkeypatch.delenv("OPENCLAW_ROOT_ENV", raising=False)
    from openclaw.path_utils import get_repo_root
    root = get_repo_root()
    assert root.is_dir(), f"get_repo_root() should return a valid directory, got: {root}"
    assert (root / "src").is_dir(), f"Repo root should contain 'src/', got: {root}"


def test_get_config_path_returns_correct_path(monkeypatch):
    """get_config_path() should return repo_root/config/<filename>."""
    monkeypatch.delenv("OPENCLAW_ROOT_ENV", raising=False)
    from openclaw.path_utils import get_config_path, get_repo_root
    repo_root = get_repo_root()
    result = get_config_path("system_state.json")
    assert result == repo_root / "config" / "system_state.json"


def test_get_data_path_returns_correct_path(monkeypatch):
    """get_data_path() should return repo_root/data/<filename>."""
    monkeypatch.delenv("OPENCLAW_ROOT_ENV", raising=False)
    from openclaw.path_utils import get_data_path, get_repo_root
    repo_root = get_repo_root()
    result = get_data_path("sqlite/trades.db")
    assert result == repo_root / "data" / "sqlite/trades.db"


def test_openclaw_root_env_override(monkeypatch, tmp_path):
    """OPENCLAW_ROOT_ENV should override the default path resolution."""
    monkeypatch.setenv("OPENCLAW_ROOT_ENV", str(tmp_path))
    # Need to reload to pick up env change since get_repo_root reads env at call time
    import importlib
    import openclaw.path_utils as path_utils_mod
    importlib.reload(path_utils_mod)
    result = path_utils_mod.get_repo_root()
    assert result == Path(str(tmp_path))
    # Cleanup: reload without override
    monkeypatch.delenv("OPENCLAW_ROOT_ENV", raising=False)
    importlib.reload(path_utils_mod)
