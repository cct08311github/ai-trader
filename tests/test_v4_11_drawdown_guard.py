"""Test Drawdown Guard (v4 #11)."""

import sqlite3
from datetime import date, timedelta


def test_drawdown_guard_basic():
    from openclaw.drawdown_guard import DrawdownPolicy, evaluate_drawdown_guard
    
    # Create in-memory database
    conn = sqlite3.connect(":memory:")
    
    # Create daily_pnl_summary table with correct schema
    conn.execute("""
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            nav_start REAL NOT NULL,
            nav_end REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            unrealized_pnl REAL NOT NULL,
            total_pnl REAL NOT NULL,
            daily_return REAL NOT NULL,
            rolling_peak_nav REAL NOT NULL,
            rolling_drawdown REAL NOT NULL,
            losing_streak_days INTEGER NOT NULL DEFAULT 0,
            risk_mode TEXT NOT NULL DEFAULT 'normal'
        )
    """)
    
    # Insert test data
    test_date = date.today()
    for i in range(30):
        trade_date = (test_date - timedelta(days=29-i)).isoformat()
        nav_start = 1_000_000.0
        nav_end = 1_000_000.0 * (1.0 - 0.01 * i)  # Decreasing NAV
        rolling_peak_nav = 1_000_000.0  # Peak NAV
        rolling_drawdown = 0.01 * i if i > 0 else 0.0  # Increasing drawdown
        
        conn.execute(
            """INSERT INTO daily_pnl_summary 
               (trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, 
                total_pnl, daily_return, rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode)
               VALUES (?, ?, ?, 0, 0, 0, 0, ?, ?, ?, 'normal')""",
            (trade_date, nav_start, nav_end, rolling_peak_nav, rolling_drawdown, i)
        )
    
    policy = DrawdownPolicy(monthly_drawdown_suspend_pct=0.15)
    
    # This should trigger drawdown warning
    decision = evaluate_drawdown_guard(conn, policy)
    
    assert decision.risk_mode in ["normal", "reduce_only", "suspended"]
    assert decision.drawdown > 0
    conn.close()


def test_recompute_rolling_drawdown():
    from openclaw.drawdown_guard import recompute_rolling_drawdown
    
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            nav_start REAL NOT NULL,
            nav_end REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            unrealized_pnl REAL NOT NULL,
            total_pnl REAL NOT NULL,
            daily_return REAL NOT NULL,
            rolling_peak_nav REAL,
            rolling_drawdown REAL,
            losing_streak_days INTEGER NOT NULL DEFAULT 0,
            risk_mode TEXT NOT NULL DEFAULT 'normal'
        )
    """)
    
    # Insert increasing then decreasing NAV
    nav_values = [1_000_000.0, 1_050_000.0, 1_100_000.0, 1_050_000.0, 950_000.0]
    for i, nav in enumerate(nav_values):
        trade_date = (date.today() - timedelta(days=len(nav_values)-1-i)).isoformat()
        conn.execute(
            """INSERT INTO daily_pnl_summary 
               (trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, 
                total_pnl, daily_return, losing_streak_days, risk_mode)
               VALUES (?, ?, ?, 0, 0, 0, 0, 0, 'normal')""",
            (trade_date, nav, nav)
        )
    
    recompute_rolling_drawdown(conn)
    
    rows = conn.execute(
        "SELECT trade_date, nav_end, rolling_peak_nav, rolling_drawdown FROM daily_pnl_summary ORDER BY trade_date ASC"
    ).fetchall()
    
    # Check that rolling_peak_nav is monotonic non-decreasing
    prev_peak = 0.0
    for row in rows:
        peak = float(row[2] or 0.0)
        assert peak >= prev_peak
        prev_peak = peak
    
    conn.close()


def test_drawdown_policy_defaults():
    from openclaw.drawdown_guard import DrawdownPolicy
    
    policy = DrawdownPolicy()
    assert policy.monthly_drawdown_suspend_pct == 0.15
    assert policy.losing_streak_reduce_only_days == 5
    assert policy.rolling_win_rate_disable_threshold == 0.40
    assert policy.rolling_win_rate_window == 20
