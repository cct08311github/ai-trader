"""Tests for structured file-operation error logging (Issue #222).

Verifies that:
- FileNotFoundError logs at DEBUG level (expected on first run)
- json.JSONDecodeError logs at WARNING level (corruption needs attention)
- PermissionError logs at ERROR level
- Return values / fallback behaviour are unchanged

Note: risk_engine._is_symbol_locked and sentinel._locked_symbols now delegate
to ConfigManager, so logging is emitted by openclaw.config_manager.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from openclaw.config_manager import get_config, reset_config

# ── risk_engine ───────────────────────────────────────────────────────────────

import openclaw.risk_engine as risk_engine_mod
from openclaw.risk_engine import _is_symbol_locked, _get_daily_pm_approval

_CM_LOGGER = "openclaw.config_manager"


class TestIsSymbolLockedLogging:
    def test_file_not_found_logs_debug_and_returns_false(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)  # no locked_symbols.json
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = _is_symbol_locked("2330")
            assert result is False
            debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
            assert any("not found" in r.message.lower() for r in debug_msgs)
            warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert not warn_msgs
        finally:
            reset_config()

    def test_json_decode_error_logs_warning_and_returns_false(self, caplog, tmp_path):
        bad_file = tmp_path / "locked_symbols.json"
        bad_file.write_text("NOT VALID JSON {{{{", encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger=_CM_LOGGER):
                result = _is_symbol_locked("2330")
            assert result is False
            warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert any("corrupted" in r.message.lower() or "locked_symbols" in r.message for r in warn_msgs)
        finally:
            reset_config()

    def test_permission_error_logs_error_and_returns_false(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            # Patch Path.read_text to raise OSError (PermissionError is a subclass)
            with patch.object(Path, "read_text", side_effect=OSError("denied")):
                with caplog.at_level(logging.ERROR, logger=_CM_LOGGER):
                    result = _is_symbol_locked("2330")
            assert result is False
            err_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert err_msgs
        finally:
            reset_config()

    def test_valid_file_no_log_noise(self, caplog, tmp_path):
        good_file = tmp_path / "locked_symbols.json"
        good_file.write_text(json.dumps({"locked": ["2330"]}), encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = _is_symbol_locked("2330")
            assert result is True
            assert not caplog.records
        finally:
            reset_config()


class TestGetDailyPmApprovalLogging:
    def test_file_not_found_logs_debug_and_returns_false(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)  # no daily_pm_state.json
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = _get_daily_pm_approval()
            assert result is False
            debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
            assert debug_msgs
            warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert not warn_msgs
        finally:
            reset_config()

    def test_json_decode_error_logs_warning_and_returns_false(self, caplog, tmp_path):
        bad_file = tmp_path / "daily_pm_state.json"
        bad_file.write_text("[[[[BROKEN", encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger=_CM_LOGGER):
                result = _get_daily_pm_approval()
            assert result is False
            warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert warn_msgs
        finally:
            reset_config()


# ── sentinel ──────────────────────────────────────────────────────────────────

import openclaw.sentinel as sentinel_mod
from openclaw.sentinel import _locked_symbols


class TestSentinelLockedSymbolsLogging:
    def test_file_not_found_logs_debug_and_returns_empty_set(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)  # no locked_symbols.json
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = _locked_symbols()
            assert result == set()
            debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
            assert debug_msgs
            warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert not warn_msgs
        finally:
            reset_config()

    def test_json_decode_error_logs_warning_and_returns_empty_set(self, caplog, tmp_path):
        bad_file = tmp_path / "locked_symbols.json"
        bad_file.write_text("NOT JSON", encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger=_CM_LOGGER):
                result = _locked_symbols()
            assert result == set()
            warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert warn_msgs
        finally:
            reset_config()

    def test_permission_error_logs_error_and_returns_empty_set(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with patch.object(Path, "read_text", side_effect=OSError("denied")):
                with caplog.at_level(logging.ERROR, logger=_CM_LOGGER):
                    result = _locked_symbols()
            assert result == set()
            err_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert err_msgs
        finally:
            reset_config()


# ── daily_pm_review ───────────────────────────────────────────────────────────

import openclaw.daily_pm_review as dpr_mod
from openclaw.daily_pm_review import get_daily_pm_approval, get_daily_pm_state


class TestDailyPmReviewLogging:
    def test_approval_file_not_found_logs_debug(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)  # no daily_pm_state.json
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = get_daily_pm_approval()
            assert result is False
            debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
            assert debug_msgs
            warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert not warn_msgs
        finally:
            reset_config()

    def test_approval_json_decode_error_logs_warning(self, caplog, tmp_path):
        bad = tmp_path / "daily_pm_state.json"
        bad.write_text("{BROKEN", encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger=_CM_LOGGER):
                result = get_daily_pm_approval()
            assert result is False
            warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert warn_msgs
        finally:
            reset_config()

    def test_state_file_not_found_logs_debug_and_returns_default(self, caplog, tmp_path, monkeypatch):
        monkeypatch.setattr(dpr_mod, "_STATE_PATH", str(tmp_path / "missing.json"))
        with caplog.at_level(logging.DEBUG, logger="daily_pm_review"):
            result = get_daily_pm_state()
        assert result["approved"] is False
        assert result["date"] is None
        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert debug_msgs
        warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warn_msgs

    def test_state_json_decode_error_logs_warning_and_returns_default(self, caplog, tmp_path, monkeypatch):
        bad = tmp_path / "daily_pm_state.json"
        bad.write_text("NOTJSON", encoding="utf-8")
        monkeypatch.setattr(dpr_mod, "_STATE_PATH", str(bad))
        with caplog.at_level(logging.WARNING, logger="daily_pm_review"):
            result = get_daily_pm_state()
        assert result["approved"] is False
        warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warn_msgs


# ── system_state_store ────────────────────────────────────────────────────────

import openclaw.system_state_store as sss_mod
from openclaw.system_state_store import read_system_state


class TestSystemStateStoreLogging:
    def test_file_not_found_logs_debug_and_returns_safe_default(self, caplog, tmp_path):
        missing = str(tmp_path / "system_state.json")
        with caplog.at_level(logging.DEBUG, logger="openclaw.system_state_store"):
            result = read_system_state(missing)
        assert result["trading_enabled"] is False
        assert result["simulation_mode"] is True
        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert debug_msgs
        warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warn_msgs

    def test_json_decode_error_logs_warning_and_returns_safe_default(self, caplog, tmp_path):
        bad = tmp_path / "system_state.json"
        bad.write_text("{{{BAD", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="openclaw.system_state_store"):
            result = read_system_state(str(bad))
        assert result["trading_enabled"] is False
        warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warn_msgs

    def test_permission_error_logs_error_and_returns_safe_default(self, caplog):
        def _raise(*a, **kw):
            raise PermissionError("denied")

        with patch("builtins.open", _raise):
            with caplog.at_level(logging.ERROR, logger="openclaw.system_state_store"):
                result = read_system_state("/any/path.json")
        assert result["trading_enabled"] is False
        err_msgs = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert err_msgs

    def test_valid_file_no_log_noise(self, caplog, tmp_path):
        state_file = tmp_path / "system_state.json"
        state_file.write_text(
            json.dumps({"trading_enabled": True, "simulation_mode": False}),
            encoding="utf-8",
        )
        with caplog.at_level(logging.DEBUG, logger="openclaw.system_state_store"):
            result = read_system_state(str(state_file))
        assert result["trading_enabled"] is True
        assert not caplog.records


# ── agent_orchestrator ────────────────────────────────────────────────────────

import openclaw.agent_orchestrator as ao_mod
from openclaw.agent_orchestrator import _pm_review_just_completed


class TestPmReviewJustCompletedLogging:
    def test_file_not_found_logs_debug_and_returns_none(self, caplog, tmp_path):
        reset_config()
        get_config(config_dir=tmp_path)  # no daily_pm_state.json
        try:
            with caplog.at_level(logging.DEBUG, logger=_CM_LOGGER):
                result = _pm_review_just_completed()
            assert result is None
            debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
            assert debug_msgs
            warn_msgs = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert not warn_msgs
        finally:
            reset_config()

    def test_json_decode_error_logs_warning_and_returns_none(self, caplog, tmp_path):
        bad = tmp_path / "daily_pm_state.json"
        bad.write_text("BAD{{{", encoding="utf-8")
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger=_CM_LOGGER):
                result = _pm_review_just_completed()
            assert result is None
            warn_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert warn_msgs
        finally:
            reset_config()
