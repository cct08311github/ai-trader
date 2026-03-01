"""Test sentinel.py - hard circuit-breakers and PM soft veto."""

import pytest
from openclaw.sentinel import (
    SentinelVerdict,
    sentinel_pre_trade_check,
    sentinel_post_risk_check,
    pm_veto,
    is_hard_block,
)
from openclaw.risk_engine import SystemState, OrderCandidate
from openclaw.drawdown_guard import DrawdownDecision


def create_system_state(**kwargs):
    """Helper to create SystemState with default values."""
    defaults = {
        'now_ms': 1700000000000,
        'trading_locked': False,
        'broker_connected': True,
        'db_write_p99_ms': 50,
        'orders_last_60s': 0,
        'reduce_only_mode': False,
    }
    defaults.update(kwargs)
    return SystemState(**defaults)


class TestSentinelPreTradeCheck:
    """Test sentinel_pre_trade_check function."""
    
    def test_trading_locked_hard_block(self):
        """trading_locked→阻斷"""
        system_state = create_system_state(trading_locked=True)
        verdict = sentinel_pre_trade_check(system_state=system_state)
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_TRADING_LOCKED"
        assert is_hard_block(verdict)
    
    def test_broker_disconnected_hard_block(self):
        """broker離線→阻斷"""
        system_state = create_system_state(broker_connected=False)
        verdict = sentinel_pre_trade_check(system_state=system_state)
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_BROKER_DISCONNECTED"
        assert is_hard_block(verdict)
    
    def test_db_latency_hard_block(self):
        """DB延遲>200ms→阻斷"""
        system_state = create_system_state(db_write_p99_ms=250)  # > 200ms limit
        verdict = sentinel_pre_trade_check(
            system_state=system_state,
            max_db_write_p99_ms=200
        )
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_DB_LATENCY"
        assert "db_write_p99_ms" in verdict.detail
        assert is_hard_block(verdict)
    
    def test_drawdown_suspended_hard_block(self):
        """drawdown suspended→阻斷"""
        system_state = create_system_state()
        drawdown = DrawdownDecision(
            risk_mode="suspended",
            reason_code="DRAWDOWN_BREACH",
            drawdown=0.12,
            losing_streak_days=3,
        )
        verdict = sentinel_pre_trade_check(
            system_state=system_state,
            drawdown=drawdown
        )
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_DRAWDOWN_SUSPENDED"
        assert is_hard_block(verdict)
    
    def test_budget_halt_hard_block(self):
        """budget halt→阻斷"""
        system_state = create_system_state()
        verdict = sentinel_pre_trade_check(
            system_state=system_state,
            budget_status="halt",
            budget_used_pct=1.0
        )
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_BUDGET_HALT"
        assert is_hard_block(verdict)
    
    def test_normal_pass(self):
        """正常→通過"""
        system_state = create_system_state()
        verdict = sentinel_pre_trade_check(system_state=system_state)
        assert verdict.allowed
        assert not verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_OK"
        assert not is_hard_block(verdict)
    
    def test_budget_warn_soft(self):
        """budget warn→soft warning"""
        system_state = create_system_state()
        verdict = sentinel_pre_trade_check(
            system_state=system_state,
            budget_status="warn",
            budget_used_pct=0.85
        )
        assert verdict.allowed  # Still allowed
        assert not verdict.hard_blocked  # Not hard blocked
        assert verdict.reason_code == "SENTINEL_BUDGET_SOFT"
        assert not is_hard_block(verdict)
    
    def test_budget_throttle_soft(self):
        """budget throttle→soft warning"""
        system_state = create_system_state()
        verdict = sentinel_pre_trade_check(
            system_state=system_state,
            budget_status="throttle",
            budget_used_pct=0.95
        )
        assert verdict.allowed  # Still allowed
        assert not verdict.hard_blocked  # Not hard blocked
        assert verdict.reason_code == "SENTINEL_BUDGET_SOFT"
        assert not is_hard_block(verdict)


class TestSentinelPostRiskCheck:
    """Test sentinel_post_risk_check function."""
    
    def test_no_candidate(self):
        """No candidate→blocked"""
        system_state = create_system_state()
        verdict = sentinel_post_risk_check(
            system_state=system_state,
            candidate=None
        )
        assert not verdict.allowed
        assert not verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_NO_CANDIDATE"
    
    def test_reduce_only_mode_block_new_position(self):
        """reduce_only_mode + opens_new_position→阻斷"""
        system_state = create_system_state(reduce_only_mode=True)
        candidate = OrderCandidate(
            symbol="2330.TW",
            side="buy",
            qty=1000,
            price=580.0,
            opens_new_position=True,
        )
        verdict = sentinel_post_risk_check(
            system_state=system_state,
            candidate=candidate
        )
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_REDUCE_ONLY"
        assert is_hard_block(verdict)
    
    def test_reduce_only_mode_allow_reduction(self):
        """reduce_only_mode + not opens_new_position→允許"""
        system_state = create_system_state(reduce_only_mode=True)
        candidate = OrderCandidate(
            symbol="2330.TW",
            side="sell",
            qty=1000,
            price=580.0,
            opens_new_position=False,  # Reducing position
        )
        verdict = sentinel_post_risk_check(
            system_state=system_state,
            candidate=candidate
        )
        assert verdict.allowed
        assert not verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_OK"


class TestPMVeto:
    """Test pm_veto function."""
    
    def test_pm_approved(self):
        """PM approved→通過"""
        verdict = pm_veto(pm_approved=True)
        assert verdict.allowed
        assert not verdict.hard_blocked
        assert verdict.reason_code == "PM_OK"
        assert not is_hard_block(verdict)  # PM veto is always soft
    
    def test_pm_rejected(self):
        """PM rejected→阻斷 (soft)"""
        verdict = pm_veto(pm_approved=False, reason_code="PM_REJECT_CONSERVATIVE")
        assert not verdict.allowed
        assert not verdict.hard_blocked  # PM veto is soft
        assert verdict.reason_code == "PM_REJECT_CONSERVATIVE"
        assert not is_hard_block(verdict)  # Not a hard block


class TestIsHardBlock:
    """Test is_hard_block function."""
    
    def test_hard_block_by_hard_blocked_flag(self):
        """Test hard_blocked flag detection."""
        verdict = SentinelVerdict(
            allowed=False,
            hard_blocked=True,
            reason_code="TEST_HARD",
            detail={}
        )
        assert is_hard_block(verdict)
    
    def test_hard_block_by_reason_code(self):
        """Test hard block reason code detection."""
        verdict = SentinelVerdict(
            allowed=False,
            hard_blocked=False,  # Flag not set
            reason_code="SENTINEL_TRADING_LOCKED",  # But code is in hard block list
            detail={}
        )
        assert is_hard_block(verdict)
    
    def test_soft_block(self):
        """Test soft block detection."""
        verdict = SentinelVerdict(
            allowed=False,
            hard_blocked=False,
            reason_code="PM_REJECT",  # Not in hard block list
            detail={}
        )
        assert not is_hard_block(verdict)
