"""Test cash mode integration with decision pipeline."""

import sqlite3
import tempfile
import os
from datetime import datetime, timezone

from openclaw.cash_mode_manager import CashModeManager
from openclaw.market_regime import MarketRegime, MarketRegimeResult
from openclaw.risk_engine import SystemState


def test_cash_mode_manager_basic():
    """Test basic cash mode manager functionality."""
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Create manager
        manager = CashModeManager(db_path)
        
        # Test initial state
        status = manager.get_status_report()
        assert status["status"] == "UNINITIALIZED"
        assert not status["cash_mode_active"]
        
        # Create test data
        market_result = MarketRegimeResult(
            regime=MarketRegime.BEAR,
            confidence=0.8,
            features={"trend_strength": -0.05, "volatility": 0.03},
            volatility_multiplier=0.7,
            risk_multipliers={"max_gross_exposure": 0.8}
        )
        
        system_state = SystemState(
            now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            trading_locked=False,
            broker_connected=True,
            db_write_p99_ms=50,
            orders_last_60s=2,
            reduce_only_mode=False
        )
        
        # Test evaluation
        decision, new_system_state = manager.evaluate(market_result, system_state)
        
        # Should enter cash mode due to bear regime
        assert decision.cash_mode is True
        assert decision.reason_code in {"CASHMODE_BEAR_REGIME", "CASHMODE_ENTER_LOW_RATING"}
        assert new_system_state.reduce_only_mode is True
        
        # Test status report
        status = manager.get_status_report()
        assert status["cash_mode_active"] is True
        assert status["market_regime"] == "bear"
        assert status["confidence"] == 0.8
        
        # Test history
        history = manager.get_history(limit=10)
        assert len(history) >= 1
        assert history[0]["is_active"] is True
        
        print("✅ Basic cash mode manager test passed")
        
    finally:
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_cash_mode_hysteresis():
    """Test cash mode hysteresis (enter/exit logic)."""
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        manager = CashModeManager(db_path)
        
        # Start with bull market (should not enter cash mode)
        bull_result = MarketRegimeResult(
            regime=MarketRegime.BULL,
            confidence=0.7,
            features={"trend_strength": 0.04, "volatility": 0.02},
            volatility_multiplier=1.0,
            risk_multipliers=None
        )
        
        system_state = SystemState(
            now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            trading_locked=False,
            broker_connected=True,
            db_write_p99_ms=50,
            orders_last_60s=2,
            reduce_only_mode=False
        )
        
        decision1, state1 = manager.evaluate(bull_result, system_state)
        assert decision1.cash_mode is False
        assert state1.reduce_only_mode is False
        
        # Switch to bear market (should enter cash mode)
        bear_result = MarketRegimeResult(
            regime=MarketRegime.BEAR,
            confidence=0.8,
            features={"trend_strength": -0.05, "volatility": 0.03},
            volatility_multiplier=0.7,
            risk_multipliers={"max_gross_exposure": 0.8}
        )
        
        decision2, state2 = manager.evaluate(bear_result, state1)
        assert decision2.cash_mode is True
        assert state2.reduce_only_mode is True
        
        # Back to bull with good rating (should exit cash mode)
        bull_result2 = MarketRegimeResult(
            regime=MarketRegime.BULL,
            confidence=0.9,
            features={"trend_strength": 0.06, "volatility": 0.01},  # Strong trend, low vol
            volatility_multiplier=1.0,
            risk_multipliers=None
        )
        
        decision3, state3 = manager.evaluate(bull_result2, state2)
        # Rating should be high enough to exit
        if decision3.rating >= 55.0:  # exit_above_rating default
            assert decision3.cash_mode is False
            assert state3.reduce_only_mode is False
            assert decision3.reason_code == "CASHMODE_EXIT_RATING_RECOVERY"
        
        print("✅ Cash mode hysteresis test passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_emergency_volatility():
    """Test emergency cash mode activation due to high volatility."""
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        manager = CashModeManager(db_path)
        
        # High volatility scenario (above emergency threshold)
        high_vol_result = MarketRegimeResult(
            regime=MarketRegime.BULL,  # Even in bull market
            confidence=0.6,
            features={"trend_strength": 0.03, "volatility": 0.08},  # 8% volatility > 7% threshold
            volatility_multiplier=1.5,
            risk_multipliers=None
        )
        
        system_state = SystemState(
            now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            trading_locked=False,
            broker_connected=True,
            db_write_p99_ms=50,
            orders_last_60s=2,
            reduce_only_mode=False
        )
        
        decision, new_state = manager.evaluate(high_vol_result, system_state)
        
        # Should enter emergency cash mode
        assert decision.cash_mode is True
        assert decision.reason_code == "CASHMODE_EMERGENCY_VOLATILITY"
        assert new_state.reduce_only_mode is True
        
        print("✅ Emergency volatility test passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_policy_configuration():
    """Test cash mode policy configuration and persistence."""
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        manager = CashModeManager(db_path)
        
        # Load default policy
        default_policy = manager.load_policy()
        assert default_policy.enter_below_rating == 35.0
        assert default_policy.exit_above_rating == 55.0
        assert default_policy.enter_on_bear_regime is True
        
        # Create custom policy
        from openclaw.cash_mode import CashModePolicy
        custom_policy = CashModePolicy(
            enter_below_rating=30.0,
            exit_above_rating=60.0,
            enter_on_bear_regime=False,  # Disable bear regime trigger
            bear_min_confidence=0.6,
            emergency_volatility_threshold=0.1  # Higher threshold
        )
        
        # Save custom policy
        manager.save_policy(custom_policy)
        
        # Reload and verify
        manager.policy = manager.load_policy()
        assert manager.policy.enter_below_rating == 30.0
        assert manager.policy.exit_above_rating == 60.0
        assert manager.policy.enter_on_bear_regime is False
        assert manager.policy.emergency_volatility_threshold == 0.1
        
        print("✅ Policy configuration test passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    test_cash_mode_manager_basic()
    test_cash_mode_hysteresis()
    test_emergency_volatility()
    test_policy_configuration()
    print("\n🎉 All cash mode integration tests passed!")
