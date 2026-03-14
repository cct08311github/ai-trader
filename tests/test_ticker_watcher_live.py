"""Live 切換開關測試。"""
import os
import pytest
from unittest.mock import patch


def test_trading_mode_default_simulation():
    """未設 TRADING_MODE → 預設 simulation。"""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TRADING_MODE", None)
        mode = os.environ.get("TRADING_MODE", "simulation")
        assert mode == "simulation"


def test_trading_mode_live_requires_no_emergency_stop(tmp_path):
    """Live 模式：.EMERGENCY_STOP 存在 → 拒絕。"""
    emergency_file = tmp_path / ".EMERGENCY_STOP"
    emergency_file.touch()
    from openclaw.ticker_watcher import _check_live_mode_safety
    safe, reason = _check_live_mode_safety(
        emergency_stop_path=str(emergency_file),
        trading_enabled=True,
    )
    assert not safe
    assert "EMERGENCY_STOP" in reason


def test_trading_mode_live_requires_trading_enabled(tmp_path):
    """Live 模式：trading_enabled=false → 拒絕。"""
    from openclaw.ticker_watcher import _check_live_mode_safety
    safe, reason = _check_live_mode_safety(
        emergency_stop_path=str(tmp_path / ".EMERGENCY_STOP"),
        trading_enabled=False,
    )
    assert not safe
    assert "trading_enabled" in reason


def test_trading_mode_live_safe_when_all_conditions_met(tmp_path):
    """Live 模式：所有條件滿足 → 允許。"""
    from openclaw.ticker_watcher import _check_live_mode_safety
    safe, reason = _check_live_mode_safety(
        emergency_stop_path=str(tmp_path / ".EMERGENCY_STOP"),
        trading_enabled=True,
    )
    assert safe
    assert reason == "OK"
