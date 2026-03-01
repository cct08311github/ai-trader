import sys
sys.path.insert(0, 'src')
import sqlite3
import tempfile
import json
from datetime import datetime, timezone

from openclaw.decision_pipeline_v4 import run_decision_with_sentinel
from openclaw.market_regime import MarketRegime, MarketRegimeResult
from openclaw.risk_engine import SystemState, OrderCandidate
from openclaw.drawdown_guard import DrawdownPolicy
from openclaw.cash_mode_manager import get_cash_mode_manager

def test_decision_pipeline_with_cash_mode():
    """Test decision pipeline integration with cash mode."""
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Initialize database with required tables
        conn = sqlite3.connect(db_path)
        
        # Create minimal required tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                created_at DATETIME,
                allowed BOOLEAN,
                reason TEXT,
                metrics_json TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cash_mode_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                is_active INTEGER NOT NULL DEFAULT 0,
                rating REAL NOT NULL DEFAULT 50.0,
                reason_code TEXT NOT NULL DEFAULT 'UNINITIALIZED',
                detail_json TEXT NOT NULL DEFAULT '{}',
                market_regime TEXT NOT NULL DEFAULT 'range',
                confidence REAL NOT NULL DEFAULT 0.0,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl_summary (
                trade_date DATE PRIMARY KEY,
                nav_start REAL,
                nav_end REAL,
                realized_pnl REAL,
                unrealized_pnl REAL,
                total_pnl REAL,
                daily_return REAL,
                rolling_peak_nav REAL,
                rolling_drawdown REAL,
                losing_streak_days INTEGER,
                risk_mode TEXT
            )
        """)
        
        conn.commit()
        
        # Create mock LLM caller
        def mock_llm_call(model: str, prompt: str) -> dict:
            return {
                "input_tokens": 10,
                "output_tokens": 20,
                "latency_ms": 100,
                "confidence": 0.8,
                "response": "Test response"
            }
        
        # Test 1: Bear market should trigger cash mode
        bear_market_result = MarketRegimeResult(
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
        
        order_candidate = OrderCandidate(
            symbol="2330",
            side="buy",
            qty=1000,
            price=800.0,
            opens_new_position=True
        )
        
        drawdown_policy = DrawdownPolicy(
            monthly_drawdown_suspend_pct=15.0,
            losing_streak_reduce_only_days=5,
            rolling_win_rate_disable_threshold=0.40, rolling_win_rate_window=20
        )
        
        # Create a temporary budget policy file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as budget_file:
            budget_policy = {
                "tiers": [
                    {"threshold_pct": 80, "action": "warn"},
                    {"threshold_pct": 95, "action": "block"}
                ],
                "reset_schedule": "daily"
            }
            json.dump(budget_policy, budget_file)
            budget_path = budget_file.name
        
        try:
            # First, manually trigger cash mode evaluation
            manager = get_cash_mode_manager(db_path)
            cash_decision, updated_system_state = manager.evaluate(bear_market_result, system_state)
            
            print(f"Cash mode decision: {cash_decision.cash_mode}, reason: {cash_decision.reason_code}")
            
            # Run decision with cash mode integration
            allowed, reason, decision_record = run_decision_with_sentinel(
                conn=conn,
                system_state=updated_system_state,
                order_candidate=order_candidate,
                budget_policy_path=budget_path,
                drawdown_policy=drawdown_policy,
                pm_context={},
                pm_approved=True,
                llm_call=mock_llm_call,
            )
            
            # Check that cash mode was activated
            cursor = conn.cursor()
            cash_mode_row = cursor.execute(
                "SELECT is_active, reason_code FROM cash_mode_state WHERE id = 1"
            ).fetchone()
            
            assert cash_mode_row is not None, "cash_mode_state should have a row"
            is_active, reason_code = cash_mode_row
            
            # In bear market with confidence > 0.45, should enter cash mode
            if bear_market_result.confidence >= 0.45:
                assert is_active == 1, f"Cash mode should be active, got is_active={is_active}"
                assert reason_code in ["CASHMODE_BEAR_REGIME", "CASHMODE_ENTER_LOW_RATING"], f"Unexpected reason_code: {reason_code}"
            
            print("Test passed!")
            return True
            
        finally:
            # Clean up temporary file
            if os.path.exists(budget_path):
                os.unlink(budget_path)
    
    finally:
        # Clean up database
        if os.path.exists(db_path):
            os.unlink(db_path)

if __name__ == "__main__":
    try:
        test_decision_pipeline_with_cash_mode()
        print("All tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
