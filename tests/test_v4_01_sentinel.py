"""Test Sentinel hard circuit-breakers (v4 #1)."""

import pytest
import time
from openclaw.sentinel import (
    SentinelVerdict,
    sentinel_pre_trade_check,
    sentinel_post_risk_check,
    pm_veto,
    is_hard_block
)
from openclaw.risk_engine import SystemState, OrderCandidate
from openclaw.drawdown_guard import DrawdownDecision


def make_system_state(**kwargs):
    """Helper to create SystemState with defaults."""
    defaults = {
        "now_ms": int(time.time() * 1000),
        "trading_locked": False,
        "broker_connected": True,
        "db_write_p99_ms": 50,
        "orders_last_60s": 0,
        "reduce_only_mode": False
    }
    defaults.update(kwargs)
    return SystemState(**defaults)


class TestSentinelPreTradeCheck:
    """Test sentinel_pre_trade_check function."""
    
    def test_trading_locked_hard_block(self):
        """Test that trading_locked triggers hard block."""
        state = make_system_state(trading_locked=True)
        verdict = sentinel_pre_trade_check(system_state=state)
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_TRADING_LOCKED"
    
    def test_broker_disconnected_hard_block(self):
        """Test that broker_disconnected triggers hard block."""
        state = make_system_state(broker_connected=False)
        verdict = sentinel_pre_trade_check(system_state=state)
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_BROKER_DISCONNECTED"
    
    def test_db_latency_hard_block(self):
        """Test that high DB latency triggers hard block."""
        state = make_system_state(db_write_p99_ms=500)
        verdict = sentinel_pre_trade_check(system_state=state)
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_DB_LATENCY"
    
    def test_drawdown_suspended_hard_block(self):
        """Test that drawdown suspended triggers hard block."""
        state = make_system_state()
        drawdown = DrawdownDecision(
            risk_mode="suspended",
            reason_code="RISK_MONTHLY_DRAWDOWN_LIMIT",
            drawdown=0.16,
            losing_streak_days=3
        )
        verdict = sentinel_pre_trade_check(system_state=state, drawdown=drawdown)
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_DRAWDOWN_SUSPENDED"
    
    def test_budget_halt_hard_block(self):
        """Test that budget halt triggers hard block."""
        state = make_system_state()
        verdict = sentinel_pre_trade_check(
            system_state=state,
            budget_status="halt",
            budget_used_pct=100.0
        )
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_BUDGET_HALT"
    
    def test_budget_warn_soft_signal(self):
        """Test that budget warn is a soft signal."""
        state = make_system_state()
        verdict = sentinel_pre_trade_check(
            system_state=state,
            budget_status="warn",
            budget_used_pct=75.0
        )
        
        assert verdict.hard_blocked is False
        assert verdict.allowed is True
        assert verdict.reason_code == "SENTINEL_BUDGET_SOFT"
    
    def test_all_ok(self):
        """Test that all OK returns allowed."""
        state = make_system_state()
        verdict = sentinel_pre_trade_check(system_state=state)
        
        assert verdict.hard_blocked is False
        assert verdict.allowed is True
        assert verdict.reason_code == "SENTINEL_OK"


class TestSentinelPostRiskCheck:
    """Test sentinel_post_risk_check function."""
    
    def test_reduce_only_blocks_new_position(self):
        """Test that reduce_only mode blocks new positions."""
        state = make_system_state(reduce_only_mode=True)
        candidate = OrderCandidate(
            symbol="2330",
            side="buy",
            qty=1000,
            price=800.0,
            opens_new_position=True
        )
        verdict = sentinel_post_risk_check(system_state=state, candidate=candidate)
        
        assert verdict.hard_blocked is True
        assert verdict.reason_code == "SENTINEL_REDUCE_ONLY"
    
    def test_no_candidate_returns_false(self):
        """Test that no candidate returns neutral verdict."""
        state = make_system_state()
        verdict = sentinel_post_risk_check(system_state=state, candidate=None)
        
        assert verdict.allowed is False
        assert verdict.reason_code == "SENTINEL_NO_CANDIDATE"


class TestPMVeto:
    """Test pm_veto function."""
    
    def test_pm_approved_returns_ok(self):
        """Test that PM approved returns OK."""
        verdict = pm_veto(pm_approved=True)
        
        assert verdict.allowed is True
        assert verdict.reason_code == "PM_OK"
    
    def test_pm_rejected_returns_veto(self):
        """Test that PM rejected returns veto."""
        verdict = pm_veto(pm_approved=False, reason_code="PM_REJECT")
        
        assert verdict.allowed is False
        assert verdict.reason_code == "PM_REJECT"


class TestIsHardBlock:
    """Test is_hard_block helper."""
    
    def test_hard_block_codes(self):
        """Test that hard block codes are recognized."""
        codes = [
            "SENTINEL_TRADING_LOCKED",
            "SENTINEL_BROKER_DISCONNECTED", 
            "SENTINEL_DB_LATENCY",
            "SENTINEL_DRAWDOWN_SUSPENDED",
            "SENTINEL_BUDGET_HALT"
        ]
        
        for code in codes:
            verdict = SentinelVerdict(False, True, code, {})
            assert is_hard_block(verdict) is True
    
    def test_soft_veto_not_hard_block(self):
        """Test that soft veto is not a hard block."""
        verdict = SentinelVerdict(False, False, "PM_REJECT", {})
        assert is_hard_block(verdict) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
