from __future__ import annotations

from datetime import datetime

from zoneinfo import ZoneInfo

from openclaw.risk_engine import default_limits
from openclaw.tw_session_rules import TWTradingPhase, apply_tw_session_risk_adjustments, get_tw_trading_phase


def _ms(y, m, d, hh, mm, ss=0):
    dt = datetime(y, m, d, hh, mm, ss, tzinfo=ZoneInfo("Asia/Taipei"))
    return int(dt.timestamp() * 1000)


def test_get_tw_trading_phase_boundaries():
    # Closed
    assert get_tw_trading_phase(_ms(2026, 2, 28, 8, 59, 0)) == TWTradingPhase.CLOSED

    # Preopen auction: 09:00-09:10
    assert get_tw_trading_phase(_ms(2026, 2, 28, 9, 0, 0)) == TWTradingPhase.PREOPEN_AUCTION
    assert get_tw_trading_phase(_ms(2026, 2, 28, 9, 9, 59)) == TWTradingPhase.PREOPEN_AUCTION

    # Regular: 09:10-13:25
    assert get_tw_trading_phase(_ms(2026, 2, 28, 9, 10, 0)) == TWTradingPhase.REGULAR
    assert get_tw_trading_phase(_ms(2026, 2, 28, 13, 24, 59)) == TWTradingPhase.REGULAR

    # Between sessions
    assert get_tw_trading_phase(_ms(2026, 2, 28, 13, 26, 0)) == TWTradingPhase.CLOSED

    # Afterhours auction: 13:30-13:40
    assert get_tw_trading_phase(_ms(2026, 2, 28, 13, 30, 0)) == TWTradingPhase.AFTERHOURS_AUCTION
    assert get_tw_trading_phase(_ms(2026, 2, 28, 13, 39, 59)) == TWTradingPhase.AFTERHOURS_AUCTION


def test_apply_tw_session_risk_adjustments_preopen():
    now_ms = _ms(2026, 2, 28, 9, 0, 0)
    limits = default_limits()

    adjusted = apply_tw_session_risk_adjustments(limits, now_ms=now_ms, sentinel_policy_path="config/sentinel_policy_v1.json")

    assert adjusted["tw_trading_phase"] == "preopen_auction"
    assert adjusted["max_orders_per_min"] == limits["max_orders_per_min"] * 0.5
    assert adjusted["max_qty_to_1m_volume_ratio"] == limits["max_qty_to_1m_volume_ratio"] * 0.7
