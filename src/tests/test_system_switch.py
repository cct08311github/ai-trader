"""Tests for system_switch.py — 0% → high coverage."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.error import URLError

import pytest

from openclaw.system_switch import (
    _read_trading_enabled_from_api,
    check_system_switch,
    is_auto_trading_allowed,
)


# ── _read_trading_enabled_from_api ──────────────────────────────────────────

def test_api_read_returns_true_when_enabled():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"trading_enabled": true}'
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("openclaw.system_switch.urlopen", return_value=mock_resp):
        enabled, err = _read_trading_enabled_from_api("http://fake/api")
    assert enabled is True
    assert err is None


def test_api_read_returns_false_when_disabled():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"trading_enabled": false}'
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("openclaw.system_switch.urlopen", return_value=mock_resp):
        enabled, err = _read_trading_enabled_from_api("http://fake/api")
    assert enabled is False
    assert err is None


def test_api_read_returns_none_on_url_error():
    with patch("openclaw.system_switch.urlopen", side_effect=URLError("conn refused")):
        enabled, err = _read_trading_enabled_from_api("http://fake/api")
    assert enabled is None
    assert err is not None


def test_api_read_non_object_json():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'["list", "not", "dict"]'
    mock_resp.__enter__ = lambda s: mock_resp
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("openclaw.system_switch.urlopen", return_value=mock_resp):
        enabled, err = _read_trading_enabled_from_api("http://fake/api")
    assert enabled is None
    assert "non-object" in err


# ── check_system_switch ─────────────────────────────────────────────────────

def _write_state(path: str, trading_enabled: bool) -> None:
    with open(path, "w") as f:
        json.dump({"trading_enabled": trading_enabled}, f)


def test_emergency_stop_file_blocks_trading(tmp_path, monkeypatch):
    stop_file = tmp_path / ".EMERGENCY_STOP"
    stop_file.write_text("manual halt")
    state_file = str(tmp_path / "system_state.json")
    _write_state(state_file, True)

    # Use env var override so check_system_switch finds .EMERGENCY_STOP in tmp_path
    monkeypatch.setenv("_OPENCLAW_PROJECT_ROOT", str(tmp_path))
    allowed, reason = check_system_switch(state_file)
    assert allowed is False
    assert "EMERGENCY_STOP" in reason


def test_state_file_enabled_returns_true(tmp_path):
    state_file = str(tmp_path / "system_state.json")
    _write_state(state_file, True)

    # Ensure no .EMERGENCY_STOP in the real project root (it shouldn't exist)
    allowed, reason = check_system_switch(state_file)
    assert allowed is True
    assert reason is None


def test_state_file_disabled_returns_false(tmp_path):
    state_file = str(tmp_path / "system_state.json")
    _write_state(state_file, False)

    allowed, reason = check_system_switch(state_file)
    assert allowed is False
    assert "disabled" in reason.lower()


def test_state_file_not_found_api_fallback_disabled(tmp_path):
    missing_file = str(tmp_path / "nonexistent.json")
    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(False, None)):
        allowed, reason = check_system_switch(missing_file)
    assert allowed is False


def test_state_file_not_found_api_unavailable(tmp_path):
    missing_file = str(tmp_path / "nonexistent.json")
    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(None, "conn fail")):
        allowed, reason = check_system_switch(missing_file)
    assert allowed is False
    assert "unavailable" in reason.lower() or "disabled" in reason.lower()


def test_state_file_not_found_api_enabled(tmp_path):
    missing_file = str(tmp_path / "nonexistent.json")
    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(True, None)):
        allowed, reason = check_system_switch(missing_file)
    assert allowed is True


def test_state_file_bad_json_falls_back_to_api(tmp_path):
    state_file = str(tmp_path / "system_state.json")
    with open(state_file, "w") as f:
        f.write("NOT JSON{{{")

    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(True, None)):
        allowed, reason = check_system_switch(state_file)
    assert allowed is True


def test_is_auto_trading_allowed_reads_config(tmp_path):
    # Patch the path to a disabled config
    state_path = tmp_path / "system_state.json"
    state_path.write_text('{"trading_enabled": false}')

    with patch("openclaw.system_switch.os.path.join", return_value=str(state_path)):
        result = is_auto_trading_allowed()
    assert result is False


# ── Additional tests for uncovered lines ────────────────────────────────────

def test_api_read_generic_exception_line_36_37():
    """Lines 36-37: generic Exception (not HTTPError/URLError) in _read_trading_enabled_from_api."""
    with patch("openclaw.system_switch.urlopen", side_effect=RuntimeError("unexpected error")):
        enabled, err = _read_trading_enabled_from_api("http://fake/api")
    assert enabled is None
    assert "Control API error" in err


def test_emergency_stop_file_unreadable_line_67_68(tmp_path, monkeypatch):
    """Lines 67-68: EMERGENCY_STOP file exists but raises on read_text."""
    stop_file = tmp_path / ".EMERGENCY_STOP"
    stop_file.write_text("halt")
    state_file = str(tmp_path / "system_state.json")
    _write_state(state_file, True)

    monkeypatch.setenv("_OPENCLAW_PROJECT_ROOT", str(tmp_path))

    # Patch Path.read_text to raise an exception so we hit the except branch
    original_read_text = Path.read_text

    def patched_read_text(self, **kwargs):
        if self.name == ".EMERGENCY_STOP":
            raise PermissionError("cannot read")
        return original_read_text(self, **kwargs)

    with patch.object(Path, "read_text", patched_read_text):
        allowed, reason = check_system_switch(state_file)

    assert allowed is False
    assert reason == "EMERGENCY_STOP file exists"


def test_bad_json_api_fallback_fails_line_89(tmp_path):
    """Line 89: bad JSON state file + API unavailable returns combined error."""
    state_file = str(tmp_path / "system_state.json")
    with open(state_file, "w") as f:
        f.write("BAD{{JSON")

    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(None, "timeout")):
        allowed, reason = check_system_switch(state_file)

    assert allowed is False
    assert "fallback failed" in reason


def test_bad_json_api_returns_false_line_91(tmp_path):
    """Line 91: bad JSON state file + API returns False."""
    state_file = str(tmp_path / "system_state.json")
    with open(state_file, "w") as f:
        f.write("INVALID{")

    with patch("openclaw.system_switch._read_trading_enabled_from_api", return_value=(False, None)):
        allowed, reason = check_system_switch(state_file)

    assert allowed is False
    assert "disabled" in reason.lower()
