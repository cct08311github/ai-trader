"""Tests for openclaw.config_manager — centralized config loading."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from openclaw.config_manager import (
    CapitalConfig,
    ConfigManager,
    DailyPMState,
    WatchlistConfig,
    get_config,
    reset_config,
)


@pytest.fixture()
def cfg_dir(tmp_path: Path) -> Path:
    """Create a temp config directory with sample JSON files."""
    d = tmp_path / "config"
    d.mkdir()
    return d


@pytest.fixture()
def cfg(cfg_dir: Path) -> ConfigManager:
    return ConfigManager(config_dir=cfg_dir)


# ── locked_symbols ──────────────────────────────────────────────────────────


class TestLockedSymbols:
    def test_returns_empty_set_when_file_missing(self, cfg: ConfigManager):
        assert cfg.locked_symbols() == set()

    def test_returns_locked_symbols_uppercased(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["2330", "2317"]})
        )
        assert cfg.locked_symbols() == {"2330", "2317"}

    def test_handles_corrupted_json(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text("{bad json")
        assert cfg.locked_symbols() == set()

    def test_case_insensitive_uppercasing(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["abc", "DEF"]})
        )
        result = cfg.locked_symbols()
        assert "ABC" in result
        assert "DEF" in result


# ── watchlist ───────────────────────────────────────────────────────────────


class TestWatchlist:
    def test_returns_defaults_when_file_missing(self, cfg: ConfigManager):
        wl = cfg.watchlist()
        assert isinstance(wl, WatchlistConfig)
        assert wl.manual_watchlist == []
        assert wl.max_system_candidates == 10

    def test_loads_watchlist(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "watchlist.json").write_text(
            json.dumps({
                "manual_watchlist": ["2330", "2317"],
                "max_system_candidates": 5,
            })
        )
        wl = cfg.watchlist()
        assert wl.manual_watchlist == ["2330", "2317"]
        assert wl.max_system_candidates == 5


# ── capital ─────────────────────────────────────────────────────────────────


class TestCapital:
    def test_returns_defaults_when_file_missing(self, cfg: ConfigManager):
        cap = cfg.capital()
        assert isinstance(cap, CapitalConfig)
        assert cap.total_capital_twd == 1_000_000.0

    def test_loads_capital(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "capital.json").write_text(
            json.dumps({"total_capital_twd": 500_000, "max_single_position_pct": 0.15})
        )
        cap = cfg.capital()
        assert cap.total_capital_twd == 500_000.0
        assert cap.max_single_position_pct == 0.15


# ── daily_pm_state ──────────────────────────────────────────────────────────


class TestDailyPMState:
    def test_returns_defaults_when_file_missing(self, cfg: ConfigManager):
        state = cfg.daily_pm_state()
        assert isinstance(state, DailyPMState)
        assert state.approved is False

    def test_loads_pm_state(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "daily_pm_state.json").write_text(
            json.dumps({"date": "2026-03-28", "approved": True, "confidence": 0.9})
        )
        state = cfg.daily_pm_state()
        assert state.date == "2026-03-28"
        assert state.approved is True
        assert state.confidence == 0.9

    def test_is_not_cached(self, cfg: ConfigManager, cfg_dir: Path):
        """daily_pm_state should always reload (use_cache=False)."""
        (cfg_dir / "daily_pm_state.json").write_text(
            json.dumps({"date": "2026-03-28", "approved": False})
        )
        assert cfg.daily_pm_state().approved is False

        (cfg_dir / "daily_pm_state.json").write_text(
            json.dumps({"date": "2026-03-28", "approved": True})
        )
        assert cfg.daily_pm_state().approved is True


# ── is_pm_approved_today ────────────────────────────────────────────────────


class TestIsPMApprovedToday:
    def test_false_when_file_missing(self, cfg: ConfigManager):
        assert cfg.is_pm_approved_today() is False

    def test_false_when_wrong_date(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "daily_pm_state.json").write_text(
            json.dumps({"date": "1999-01-01", "approved": True})
        )
        assert cfg.is_pm_approved_today() is False


# ── cache and invalidate ────────────────────────────────────────────────────


class TestCaching:
    def test_cached_values_are_reused(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["2330"]})
        )
        assert cfg.locked_symbols() == {"2330"}

        # Overwrite the file — cached value should still be returned
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["9999"]})
        )
        assert cfg.locked_symbols() == {"2330"}

    def test_invalidate_specific_key(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["2330"]})
        )
        cfg.locked_symbols()

        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["9999"]})
        )
        cfg.invalidate("locked_symbols.json")
        assert cfg.locked_symbols() == {"9999"}

    def test_invalidate_all(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["2330"]})
        )
        cfg.locked_symbols()

        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["9999"]})
        )
        cfg.invalidate()
        assert cfg.locked_symbols() == {"9999"}


# ── raw accessor ────────────────────────────────────────────────────────────


class TestRawAccessor:
    def test_loads_arbitrary_json(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "foo.json").write_text(json.dumps({"bar": 42}))
        assert cfg.raw("foo.json") == {"bar": 42}

    def test_returns_empty_dict_for_missing_file(self, cfg: ConfigManager):
        assert cfg.raw("nonexistent.json") == {}


# ── singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_config_returns_same_instance(self, cfg_dir: Path):
        reset_config()
        a = get_config(config_dir=cfg_dir)
        b = get_config()
        assert a is b
        reset_config()

    def test_reset_config_creates_new_instance(self, cfg_dir: Path):
        reset_config()
        a = get_config(config_dir=cfg_dir)
        reset_config()
        b = get_config(config_dir=cfg_dir)
        assert a is not b
        reset_config()


# ── thread safety ───────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_reads_do_not_crash(self, cfg: ConfigManager, cfg_dir: Path):
        (cfg_dir / "locked_symbols.json").write_text(
            json.dumps({"locked": ["2330"]})
        )
        errors = []

        def reader():
            try:
                for _ in range(50):
                    cfg.locked_symbols()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
