"""Test sentinel.py - hard circuit-breakers and PM soft veto."""

import pytest
from openclaw.sentinel import (
    SentinelVerdict,
    sentinel_pre_trade_check,
    sentinel_post_risk_check,
    pm_veto,
    is_hard_block,
    filter_locked_positions,
    _locked_symbols,
)
from openclaw.risk_engine import SystemState, OrderCandidate, PortfolioState, Position
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


# ---------------------------------------------------------------------------
# New tests targeting previously uncovered lines
# ---------------------------------------------------------------------------


class TestLockedSymbolsException:
    """Lines 19-20: _locked_symbols returns empty set on any exception."""

    def test_locked_symbols_returns_empty_set_on_missing_file(self, tmp_path, monkeypatch):
        """_locked_symbols() catches exception and returns empty set when file missing."""
        import openclaw.sentinel as sentinel_mod
        bad_path = str(tmp_path / "nonexistent_locked_symbols.json")
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", bad_path)
        result = _locked_symbols()
        assert result == set()

    def test_locked_symbols_returns_empty_set_on_invalid_json(self, tmp_path, monkeypatch):
        """_locked_symbols() catches exception and returns empty set for invalid JSON."""
        import openclaw.sentinel as sentinel_mod
        bad_file = tmp_path / "locked_symbols.json"
        bad_file.write_text("NOT VALID JSON{{{{")
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(bad_file))
        result = _locked_symbols()
        assert result == set()


class TestSentinelPostRiskCheckLockedSymbol:
    """Line 115: sell on locked symbol is hard-blocked."""

    def test_sell_locked_symbol_hard_block(self, tmp_path, monkeypatch):
        """Selling a locked symbol returns SENTINEL_SYMBOL_LOCKED hard block."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        lock_file.write_text(json.dumps({"locked": ["2330"]}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        system_state = create_system_state()
        candidate = OrderCandidate(
            symbol="2330",
            side="sell",
            qty=500,
            price=580.0,
            opens_new_position=False,
        )
        verdict = sentinel_post_risk_check(system_state=system_state, candidate=candidate)
        assert not verdict.allowed
        assert verdict.hard_blocked
        assert verdict.reason_code == "SENTINEL_SYMBOL_LOCKED"
        assert verdict.detail["symbol"] == "2330"
        assert is_hard_block(verdict)

    def test_sell_unlocked_symbol_allowed(self, tmp_path, monkeypatch):
        """Selling a symbol NOT in locked list is allowed."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        lock_file.write_text(json.dumps({"locked": ["9999"]}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        system_state = create_system_state()
        candidate = OrderCandidate(
            symbol="2330",
            side="sell",
            qty=500,
            price=580.0,
            opens_new_position=False,
        )
        verdict = sentinel_post_risk_check(system_state=system_state, candidate=candidate)
        assert verdict.allowed
        assert verdict.reason_code == "SENTINEL_OK"


class TestFilterLockedPositions:
    """Lines 144-159: filter_locked_positions with locked symbols present."""

    def _make_portfolio(self) -> PortfolioState:
        return PortfolioState(
            nav=1_000_000.0,
            cash=500_000.0,
            realized_pnl_today=0.0,
            unrealized_pnl=50_000.0,
            positions={
                "2330": Position(symbol="2330", qty=1000, avg_price=500.0, last_price=550.0),
                "2317": Position(symbol="2317", qty=2000, avg_price=100.0, last_price=110.0),
            },
            consecutive_losses=0,
        )

    def test_filter_removes_locked_symbols(self, tmp_path, monkeypatch):
        """filter_locked_positions removes locked symbols and adjusts NAV/unrealized_pnl."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        lock_file.write_text(json.dumps({"locked": ["2330"]}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        portfolio = self._make_portfolio()
        filtered = filter_locked_positions(portfolio)

        assert "2330" not in filtered.positions
        assert "2317" in filtered.positions

    def test_filter_returns_same_portfolio_when_no_locked(self, tmp_path, monkeypatch):
        """filter_locked_positions returns same object when locked set is empty."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        lock_file.write_text(json.dumps({"locked": []}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        portfolio = self._make_portfolio()
        filtered = filter_locked_positions(portfolio)
        assert filtered is portfolio

    def test_filter_returns_same_portfolio_when_locked_not_held(self, tmp_path, monkeypatch):
        """filter_locked_positions returns same object when locked symbols not in portfolio."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        lock_file.write_text(json.dumps({"locked": ["9999"]}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        portfolio = self._make_portfolio()
        filtered = filter_locked_positions(portfolio)
        assert filtered is portfolio

    def test_filter_adjusts_unrealized_pnl(self, tmp_path, monkeypatch):
        """filter_locked_positions subtracts locked position unrealized PnL."""
        import json
        import openclaw.sentinel as sentinel_mod

        lock_file = tmp_path / "locked_symbols.json"
        # Lock 2330: qty=1000, avg=500, last=550 → unrealized = (550-500)*1000 = 50000
        lock_file.write_text(json.dumps({"locked": ["2330"]}))
        monkeypatch.setattr(sentinel_mod, "_LOCKED_SYMBOLS_PATH", str(lock_file))

        portfolio = self._make_portfolio()
        filtered = filter_locked_positions(portfolio)

        # unrealized_pnl should be reduced by 50000
        expected_unrealized = 50_000.0 - (550.0 - 500.0) * 1000
        assert abs(filtered.unrealized_pnl - expected_unrealized) < 1e-6
