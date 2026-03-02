import sqlite3

from openclaw.drawdown_guard import (
    DrawdownPolicy,
    DrawdownDecision,
    evaluate_drawdown_guard,
    evaluate_strategy_health_guard,
    recompute_rolling_drawdown,
    apply_drawdown_actions,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
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
        );
        CREATE TABLE strategy_health (
          strategy_id TEXT PRIMARY KEY,
          as_of_ts TEXT NOT NULL,
          rolling_trades INTEGER NOT NULL DEFAULT 0,
          rolling_win_rate REAL NOT NULL DEFAULT 0.0,
          enabled INTEGER NOT NULL DEFAULT 1,
          note TEXT
        );
        """
    )
    return conn


def test_drawdown_suspends():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO daily_pnl_summary(
          trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, total_pnl, daily_return,
          rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode
        ) VALUES ('2026-02-27', 1000000, 830000, -170000, 0, -170000, -0.17, 1000000, 0.17, 1, 'normal')
        """
    )
    result = evaluate_drawdown_guard(conn, DrawdownPolicy())
    assert result.risk_mode == "suspended"
    assert result.reason_code == "RISK_MONTHLY_DRAWDOWN_LIMIT"


def test_strategy_health_reduce_only():
    conn = _conn()
    conn.execute(
        """
        INSERT INTO strategy_health(strategy_id, as_of_ts, rolling_trades, rolling_win_rate, enabled, note)
        VALUES ('breakout', '2026-02-27T00:00:00Z', 25, 0.35, 1, 'degraded')
        """
    )
    result = evaluate_strategy_health_guard(conn, DrawdownPolicy(), "breakout")
    assert result.risk_mode == "reduce_only"
    assert result.reason_code == "RISK_LOW_WIN_RATE"


def test_drawdown_normal():
    """正向測試：drawdown 在限制內，保持 normal 模式。"""
    conn = _conn()
    conn.execute(
        """
        INSERT INTO daily_pnl_summary(
          trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, total_pnl, daily_return,
          rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode
        ) VALUES ('2026-02-27', 1000000, 950000, -50000, 0, -50000, -0.05, 1000000, 0.05, 1, 'normal')
        """
    )
    policy = DrawdownPolicy(monthly_drawdown_suspend_pct=0.15)
    result = evaluate_drawdown_guard(conn, policy)
    assert result.risk_mode == "normal"
    assert result.reason_code == "RISK_DRAWDOWN_OK"


def test_drawdown_losing_streak():
    """反向測試：連敗天數超過限制。"""
    conn = _conn()
    conn.execute(
        """
        INSERT INTO daily_pnl_summary(
          trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, total_pnl, daily_return,
          rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode
        ) VALUES ('2026-02-27', 1000000, 980000, -20000, 0, -20000, -0.02, 1000000, 0.02, 5, 'normal')
        """
    )
    policy = DrawdownPolicy(losing_streak_reduce_only_days=3)
    result = evaluate_drawdown_guard(conn, policy)
    assert result.risk_mode == "reduce_only"  # 注意：losing_streak_reduce_only_days 可能觸發 reduce_only，但實作可能不同。我們暫時使用 suspended。
    assert result.reason_code == "RISK_LOSING_STREAK_LIMIT"


def test_strategy_health_normal():
    """邊界測試：win rate 在邊界上（剛好高於閾值）。"""
    conn = _conn()
    conn.execute(
        """
        INSERT INTO strategy_health(strategy_id, as_of_ts, rolling_trades, rolling_win_rate, enabled, note)
        VALUES ('breakout', '2026-02-27T00:00:00Z', 30, 0.401, 1, 'acceptable')
        """
    )
    policy = DrawdownPolicy(rolling_win_rate_disable_threshold=0.40)
    result = evaluate_strategy_health_guard(conn, policy, "breakout")
    assert result.risk_mode == "normal"
    assert result.reason_code == "RISK_STRATEGY_HEALTH_OK"


# ---------------------------------------------------------------------------
# New tests targeting previously uncovered lines
# ---------------------------------------------------------------------------


def _conn_no_pnl() -> sqlite3.Connection:
    """Return an in-memory connection that does NOT have daily_pnl_summary."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE strategy_health (
          strategy_id TEXT PRIMARY KEY,
          as_of_ts TEXT NOT NULL,
          rolling_trades INTEGER NOT NULL DEFAULT 0,
          rolling_win_rate REAL NOT NULL DEFAULT 0.0,
          enabled INTEGER NOT NULL DEFAULT 1,
          note TEXT
        );
        """
    )
    return conn


def test_recompute_rolling_drawdown_early_return_no_table():
    """Line 39: recompute_rolling_drawdown returns early when daily_pnl_summary absent."""
    conn = _conn_no_pnl()
    # Should not raise; just returns without doing anything
    recompute_rolling_drawdown(conn)


def test_evaluate_drawdown_guard_no_rows_returns_normal():
    """Line 69: evaluate_drawdown_guard returns normal when table exists but has no rows."""
    conn = _conn()
    result = evaluate_drawdown_guard(conn, DrawdownPolicy())
    assert result.risk_mode == "normal"
    assert result.reason_code == "RISK_DRAWDOWN_OK"
    assert result.drawdown == 0.0
    assert result.losing_streak_days == 0


def test_evaluate_strategy_health_guard_no_rows_returns_normal():
    """Line 91: evaluate_strategy_health_guard returns normal when strategy row absent."""
    conn = _conn()
    result = evaluate_strategy_health_guard(conn, DrawdownPolicy(), "nonexistent_strategy")
    assert result.risk_mode == "normal"
    assert result.reason_code == "RISK_STRATEGY_HEALTH_OK"


def test_evaluate_strategy_health_guard_disabled_suspended():
    """Line 97: evaluate_strategy_health_guard returns suspended when enabled=0."""
    conn = _conn()
    conn.execute(
        """
        INSERT INTO strategy_health(strategy_id, as_of_ts, rolling_trades, rolling_win_rate, enabled)
        VALUES ('disabled_strat', '2026-02-27T00:00:00Z', 10, 0.5, 0)
        """
    )
    result = evaluate_strategy_health_guard(conn, DrawdownPolicy(), "disabled_strat")
    assert result.risk_mode == "suspended"
    assert result.reason_code == "RISK_STRATEGY_DISABLED"


def _conn_with_locks() -> sqlite3.Connection:
    """Return connection with trading_locks + incidents tables."""
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE trading_locks (
          lock_id TEXT PRIMARY KEY,
          locked INTEGER NOT NULL DEFAULT 0,
          reason_code TEXT,
          locked_at TEXT,
          unlock_after TEXT,
          note TEXT
        );
        CREATE TABLE incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    return conn


def test_apply_drawdown_actions_normal_is_noop():
    """Line 113-114: normal decision → apply_drawdown_actions does nothing."""
    conn = _conn_with_locks()
    decision = DrawdownDecision("normal", "RISK_DRAWDOWN_OK", 0.0, 0)
    apply_drawdown_actions(conn, decision)
    count = conn.execute("SELECT COUNT(*) FROM trading_locks").fetchone()[0]
    assert count == 0
    inc_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert inc_count == 0


def test_apply_drawdown_actions_suspended_upserts_lock_and_incident():
    """Lines 116-148: suspended decision writes trading_locks (locked=1) + incidents."""
    conn = _conn_with_locks()
    decision = DrawdownDecision("suspended", "RISK_MONTHLY_DRAWDOWN_LIMIT", 0.17, 2)
    apply_drawdown_actions(conn, decision)

    lock_row = conn.execute(
        "SELECT locked, reason_code FROM trading_locks WHERE lock_id = 'drawdown_guard'"
    ).fetchone()
    assert lock_row is not None
    assert lock_row[0] == 1
    assert lock_row[1] == "RISK_MONTHLY_DRAWDOWN_LIMIT"

    inc_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert inc_count == 1
    severity = conn.execute("SELECT severity FROM incidents").fetchone()[0]
    assert severity == "critical"


def test_apply_drawdown_actions_reduce_only_upserts_unlocked_and_warn_incident():
    """Lines 116-148: reduce_only decision writes trading_locks (locked=0) + warn incident."""
    conn = _conn_with_locks()
    decision = DrawdownDecision("reduce_only", "RISK_LOSING_STREAK_LIMIT", 0.05, 5)
    apply_drawdown_actions(conn, decision)

    lock_row = conn.execute(
        "SELECT locked, reason_code FROM trading_locks WHERE lock_id = 'drawdown_guard'"
    ).fetchone()
    assert lock_row is not None
    assert lock_row[0] == 0
    assert lock_row[1] == "RISK_LOSING_STREAK_LIMIT"

    inc_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert inc_count == 1
    severity = conn.execute("SELECT severity FROM incidents").fetchone()[0]
    assert severity == "warn"


def test_apply_drawdown_actions_without_locks_table():
    """Lines 116-148: when trading_locks table absent, only incidents written."""
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    decision = DrawdownDecision("suspended", "RISK_MONTHLY_DRAWDOWN_LIMIT", 0.20, 3)
    apply_drawdown_actions(conn, decision)

    inc_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert inc_count == 1


def test_apply_drawdown_actions_without_incidents_table():
    """Lines 116-148: when incidents table absent, only trading_locks written."""
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE trading_locks (
          lock_id TEXT PRIMARY KEY,
          locked INTEGER NOT NULL DEFAULT 0,
          reason_code TEXT,
          locked_at TEXT,
          unlock_after TEXT,
          note TEXT
        );
        """
    )
    decision = DrawdownDecision("reduce_only", "RISK_LOSING_STREAK_LIMIT", 0.03, 4)
    apply_drawdown_actions(conn, decision)

    count = conn.execute("SELECT COUNT(*) FROM trading_locks").fetchone()[0]
    assert count == 1


def test_recompute_rolling_drawdown_recalculates():
    """recompute_rolling_drawdown actually updates rows when table exists."""
    conn = _conn()
    conn.executemany(
        """
        INSERT INTO daily_pnl_summary(
          trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, total_pnl,
          daily_return, rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode
        ) VALUES (?, 1000000, ?, 0, 0, 0, 0, 0, 0, 0, 'normal')
        """,
        [("2026-01-01", 1000000), ("2026-01-02", 900000), ("2026-01-03", 950000)],
    )
    recompute_rolling_drawdown(conn)
    row = conn.execute(
        "SELECT rolling_peak_nav, rolling_drawdown FROM daily_pnl_summary WHERE trade_date='2026-01-02'"
    ).fetchone()
    assert row[0] == 1000000.0
    assert abs(row[1] - 0.10) < 1e-6  # (1000000 - 900000) / 1000000
