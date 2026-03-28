"""Tests for ticker_watcher.py — dual-source merge (Task 8)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from openclaw.config_manager import ConfigManager, reset_config


@pytest.fixture(autouse=True)
def _config_dir(tmp_path, monkeypatch):
    """Provide a temp config dir for ConfigManager."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    cfg = ConfigManager(config_dir=cfg_dir)
    import openclaw.config_manager as cm_mod
    monkeypatch.setattr(cm_mod, "_instance", cfg)
    # Store cfg_dir on request so tests can access it
    _config_dir._dir = cfg_dir
    yield cfg_dir
    reset_config()


def test_load_manual_watchlist_reads_new_key(_config_dir):
    """_load_manual_watchlist reads 'manual_watchlist' key first."""
    from openclaw import ticker_watcher as tw

    (_config_dir / "watchlist.json").write_text(json.dumps({
        "manual_watchlist": ["2330", "2317", "2454"],
        "universe": ["9999"],  # should be ignored
    }))

    result = tw._load_manual_watchlist()
    assert result == ["2330", "2317", "2454"]


def test_load_manual_watchlist_backward_compat_universe(_config_dir):
    """_load_manual_watchlist falls back to 'universe' key."""
    from openclaw import ticker_watcher as tw

    (_config_dir / "watchlist.json").write_text(json.dumps({
        "universe": ["2881", "2882"],
        "max_active": 5,
    }))

    result = tw._load_manual_watchlist()
    assert result == ["2881", "2882"]


def test_load_manual_watchlist_fallback_when_file_missing(_config_dir):
    """_load_manual_watchlist returns fallback when config file doesn't exist."""
    from openclaw import ticker_watcher as tw

    result = tw._load_manual_watchlist()
    assert result == list(tw._FALLBACK_UNIVERSE)


def test_load_manual_watchlist_empty_list_uses_fallback(_config_dir):
    """_load_manual_watchlist falls back when manual_watchlist is empty."""
    from openclaw import ticker_watcher as tw

    (_config_dir / "watchlist.json").write_text(json.dumps({"manual_watchlist": []}))

    result = tw._load_manual_watchlist()
    assert result == list(tw._FALLBACK_UNIVERSE)


def test_load_manual_watchlist_strips_whitespace(_config_dir):
    """_load_manual_watchlist strips whitespace from symbols."""
    from openclaw import ticker_watcher as tw

    (_config_dir / "watchlist.json").write_text(json.dumps({"manual_watchlist": [" 2330 ", "2317\t"]}))

    result = tw._load_manual_watchlist()
    assert result == ["2330", "2317"]


def test_load_manual_watchlist_returns_list_not_tuple(_config_dir):
    """_load_manual_watchlist returns List[str], not tuple."""
    from openclaw import ticker_watcher as tw

    (_config_dir / "watchlist.json").write_text(json.dumps({"manual_watchlist": ["2330"]}))

    result = tw._load_manual_watchlist()
    assert isinstance(result, list)
