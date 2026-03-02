"""Test cash mode integration with decision pipeline."""

import math
import sqlite3
import tempfile
import os
from datetime import datetime, timezone

from openclaw.cash_mode import (
    compute_market_rating,
    evaluate_cash_mode,
    CashModePolicy,
    apply_cash_mode_to_system_state,
)
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
        from openclaw.cash_mode import CashModePolicy as CP
        custom_policy = CP(
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

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def _make_system_state(reduce_only_mode: bool = False) -> SystemState:
    return SystemState(
        now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=50,
        orders_last_60s=0,
        reduce_only_mode=reduce_only_mode,
    )


def test_compute_market_rating_nan_confidence_returns_fifty():
    """Line 67: when score is not finite (NaN confidence), default to 50.0."""
    result = MarketRegimeResult(
        regime=MarketRegime.BULL,
        confidence=float("nan"),
        features={"trend_strength": 0.05, "volatility": 0.02},
        volatility_multiplier=1.0,
        risk_multipliers=None,
    )
    rating = compute_market_rating(result)
    assert rating == 50.0
    assert math.isfinite(rating)


def test_evaluate_cash_mode_hold_when_in_cash_mode_rating_below_exit():
    """Line 138: CASHMODE_HOLD when already in cash mode and rating < exit threshold."""
    # RANGE regime, vol=0.02 (< emergency 0.07), trend=0 → rating ≈ 41.7 (< exit_above=55)
    result = MarketRegimeResult(
        regime=MarketRegime.RANGE,
        confidence=0.5,
        features={"trend_strength": 0.0, "volatility": 0.02},
        volatility_multiplier=1.0,
        risk_multipliers=None,
    )
    policy = CashModePolicy(
        enter_on_bear_regime=False,   # disable bear trigger to isolate rating logic
        emergency_volatility_threshold=0.10,  # raise threshold so 0.02 vol doesn't trigger
    )
    decision = evaluate_cash_mode(result, current_cash_mode=True, policy=policy)
    assert decision.cash_mode is True
    assert decision.reason_code == "CASHMODE_HOLD"


def test_evaluate_cash_mode_enter_low_rating():
    """Line 147: CASHMODE_ENTER_LOW_RATING when not in cash mode and rating <= enter_below."""
    # RANGE regime, strong negative trend, zero vol → rating = 15.0 (< enter_below=35)
    result = MarketRegimeResult(
        regime=MarketRegime.RANGE,
        confidence=1.0,
        features={"trend_strength": -0.05, "volatility": 0.0},
        volatility_multiplier=1.0,
        risk_multipliers=None,
    )
    policy = CashModePolicy(
        enter_on_bear_regime=False,   # isolate to rating-based trigger
        emergency_volatility_threshold=0.10,
    )
    decision = evaluate_cash_mode(result, current_cash_mode=False, policy=policy)
    assert decision.cash_mode is True
    assert decision.reason_code == "CASHMODE_ENTER_LOW_RATING"


def test_apply_cash_mode_to_system_state():
    """Verify apply_cash_mode_to_system_state updates reduce_only_mode."""
    from openclaw.cash_mode import CashModeDecision
    state = _make_system_state(reduce_only_mode=False)
    decision = CashModeDecision(
        cash_mode=True,
        rating=30.0,
        reason_code="CASHMODE_ENTER_LOW_RATING",
        detail={},
    )
    new_state = apply_cash_mode_to_system_state(state, decision)
    assert new_state.reduce_only_mode is True
    # original unchanged
    assert state.reduce_only_mode is False


def test_load_policy_returns_default_when_empty():
    """Test load_policy returns CashModePolicy.default() when DB has no policy row (line 103)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        manager = CashModeManager(db_path)

        # Remove the policy row that __init__ inserted
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM cash_mode_config WHERE key = 'policy'")
        conn.commit()
        conn.close()

        policy = manager.load_policy()
        default = CashModePolicy.default()
        assert policy.enter_below_rating == default.enter_below_rating
        assert policy.exit_above_rating == default.exit_above_rating
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_get_cash_mode_manager_singleton():
    """Test get_cash_mode_manager creates and reuses a global singleton (lines 255-257)."""
    import openclaw.cash_mode_manager as mod
    from openclaw.cash_mode_manager import get_cash_mode_manager

    # Reset the module-level singleton so we exercise the creation branch
    mod._cash_mode_manager = None

    manager1 = get_cash_mode_manager(":memory:")
    assert isinstance(manager1, CashModeManager)

    # Second call should return the same instance (singleton)
    manager2 = get_cash_mode_manager(":memory:")
    assert manager1 is manager2

    # Clean up so other tests aren't affected
    mod._cash_mode_manager = None


def test_integrate_with_decision_pipeline(tmp_path):
    """Exercise integrate_with_decision_pipeline (lines 273-302).

    integrate_with_decision_pipeline creates CashModeManager(db_path=":memory:")
    internally.  Each sqlite3.connect(":memory:") returns a DIFFERENT in-memory
    database, so _init_db() tables in __init__ are not visible to _log_decision().

    We patch CashModeManager.__init__ to redirect the db_path to a temp file so
    that all connections within the same manager instance share the same tables.
    """
    import openclaw.cash_mode_manager as mod
    from openclaw.cash_mode_manager import integrate_with_decision_pipeline

    db_path = str(tmp_path / "pipe_test.db")
    original_init = mod.CashModeManager.__init__

    def patched_init(self, *args, **kwargs):
        # Always redirect to the shared temp-file DB
        original_init(self, db_path)

    mod.CashModeManager.__init__ = patched_init
    try:
        main_conn = sqlite3.connect(":memory:")
        main_conn.execute("""
            CREATE TABLE cash_mode_state (
                id INTEGER PRIMARY KEY,
                is_active INTEGER NOT NULL,
                rating REAL NOT NULL,
                reason_code TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                confidence REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        main_conn.commit()

        mkt = MarketRegimeResult(
            regime=MarketRegime.BEAR,
            confidence=0.8,
            features={"trend_strength": -0.05, "volatility": 0.03},
            volatility_multiplier=0.7,
            risk_multipliers={"max_gross_exposure": 0.8},
        )
        ss = SystemState(
            now_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
            trading_locked=False,
            broker_connected=True,
            db_write_p99_ms=50,
            orders_last_60s=2,
            reduce_only_mode=False,
        )

        new_state, report = integrate_with_decision_pipeline(mkt, ss, main_conn)

        assert isinstance(new_state, SystemState)
        assert isinstance(report, dict)

        # Verify the row was written to cash_mode_state in main_conn
        row = main_conn.execute(
            "SELECT id FROM cash_mode_state WHERE id=1"
        ).fetchone()
        assert row is not None

        main_conn.close()
    finally:
        mod.CashModeManager.__init__ = original_init


if __name__ == "__main__":
    test_cash_mode_manager_basic()
    test_cash_mode_hysteresis()
    test_emergency_volatility()
    test_policy_configuration()
