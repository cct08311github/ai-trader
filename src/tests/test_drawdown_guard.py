import sqlite3

from openclaw.drawdown_guard import DrawdownPolicy, evaluate_drawdown_guard, evaluate_strategy_health_guard


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
