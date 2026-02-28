import json
import os
from pathlib import Path

import pytest

from openclaw.system_switch import check_system_switch, is_auto_trading_allowed


def _project_root() -> Path:
    # src/openclaw/system_switch.py -> parents[2] == project root
    import openclaw.system_switch as mod

    return Path(mod.__file__).resolve().parents[2]


def test_check_system_switch_emergency_stop_readable(tmp_path):
    root = _project_root()
    stop = root / ".EMERGENCY_STOP"
    stop.write_text("maintenance", encoding="utf-8")
    try:
        allowed, reason = check_system_switch(str(tmp_path / "missing.json"))
        assert allowed is False
        assert reason == "EMERGENCY_STOP: maintenance"
    finally:
        stop.unlink(missing_ok=True)


def test_check_system_switch_emergency_stop_unreadable(monkeypatch, tmp_path):
    root = _project_root()
    stop = root / ".EMERGENCY_STOP"
    stop.write_text("x", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("nope")

    try:
        monkeypatch.setattr(Path, "read_text", boom)
        allowed, reason = check_system_switch(str(tmp_path / "missing.json"))
        assert allowed is False
        assert reason == "EMERGENCY_STOP file exists"
    finally:
        stop.unlink(missing_ok=True)


def test_check_system_switch_config_not_found(tmp_path):
    allowed, reason = check_system_switch(str(tmp_path / "nope.json"))
    assert allowed is False
    assert "config not found" in reason


def test_check_system_switch_config_disabled(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"trading_enabled": False}), encoding="utf-8")
    allowed, reason = check_system_switch(str(p))
    assert allowed is False
    assert reason == "Auto-trading is disabled (master switch OFF)"


def test_check_system_switch_config_enabled(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"trading_enabled": True}), encoding="utf-8")
    allowed, reason = check_system_switch(str(p))
    assert allowed is True
    assert reason is None


def test_check_system_switch_invalid_json(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json}", encoding="utf-8")
    allowed, reason = check_system_switch(str(p))
    assert allowed is False
    assert reason.startswith("Error reading system state")


def test_is_auto_trading_allowed_false_when_check_fails(monkeypatch):
    import openclaw.system_switch as mod

    monkeypatch.setattr(mod, "check_system_switch", lambda system_state_path: (False, "x"))
    assert is_auto_trading_allowed() is False
