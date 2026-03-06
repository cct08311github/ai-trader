"""Tests for ticker_watcher.py — dual-source merge (Task 8)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_load_manual_watchlist_reads_new_key(tmp_path, monkeypatch):
    """_load_manual_watchlist reads 'manual_watchlist' key first."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "watchlist.json"
    cfg_path.write_text(json.dumps({
        "manual_watchlist": ["2330", "2317", "2454"],
        "universe": ["9999"],  # should be ignored
    }))
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert result == ["2330", "2317", "2454"]


def test_load_manual_watchlist_backward_compat_universe(tmp_path, monkeypatch):
    """_load_manual_watchlist falls back to 'universe' key."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "watchlist.json"
    cfg_path.write_text(json.dumps({
        "universe": ["2881", "2882"],
        "max_active": 5,
    }))
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert result == ["2881", "2882"]


def test_load_manual_watchlist_fallback_when_file_missing(tmp_path, monkeypatch):
    """_load_manual_watchlist returns fallback when config file doesn't exist."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "nonexistent.json"
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert result == list(tw._FALLBACK_UNIVERSE)


def test_load_manual_watchlist_empty_list_uses_fallback(tmp_path, monkeypatch):
    """_load_manual_watchlist falls back when manual_watchlist is empty."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "watchlist.json"
    cfg_path.write_text(json.dumps({"manual_watchlist": []}))
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert result == list(tw._FALLBACK_UNIVERSE)


def test_load_manual_watchlist_strips_whitespace(tmp_path, monkeypatch):
    """_load_manual_watchlist strips whitespace from symbols."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "watchlist.json"
    cfg_path.write_text(json.dumps({"manual_watchlist": [" 2330 ", "2317\t"]}))
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert result == ["2330", "2317"]


def test_load_manual_watchlist_returns_list_not_tuple(tmp_path, monkeypatch):
    """_load_manual_watchlist returns List[str], not tuple."""
    from openclaw import ticker_watcher as tw

    cfg_path = tmp_path / "watchlist.json"
    cfg_path.write_text(json.dumps({"manual_watchlist": ["2330"]}))
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_path)

    result = tw._load_manual_watchlist()
    assert isinstance(result, list)
