from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class DrawdownPolicy:
    monthly_drawdown_suspend_pct: float = 0.15
    losing_streak_reduce_only_days: int = 5
    rolling_win_rate_disable_threshold: float = 0.40
    rolling_win_rate_window: int = 20


@dataclass
class DrawdownDecision:
    risk_mode: str  # normal/reduce_only/suspended
    reason_code: str
    drawdown: float
    losing_streak_days: int


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def recompute_rolling_drawdown(conn: sqlite3.Connection) -> None:
    """Recompute rolling_peak_nav and rolling_drawdown for daily_pnl_summary.

    P1 use-case: ensure cumulative drawdown fields remain consistent even if
    rows were backfilled or edited.
    """

    if not _table_exists(conn, "daily_pnl_summary"):
        return

    rows = conn.execute(
        "SELECT trade_date, nav_end FROM daily_pnl_summary ORDER BY trade_date ASC"
    ).fetchall()
    peak = 0.0
    for r in rows:
        trade_date = str(r[0])
        nav_end = float(r[1] or 0.0)
        peak = max(peak, nav_end)
        dd = 0.0
        if peak > 0:
            dd = max(0.0, (peak - nav_end) / peak)
        conn.execute(
            "UPDATE daily_pnl_summary SET rolling_peak_nav = ?, rolling_drawdown = ? WHERE trade_date = ?",
            (peak, dd, trade_date),
        )


def evaluate_drawdown_guard(conn: sqlite3.Connection, policy: DrawdownPolicy) -> DrawdownDecision:
    row = conn.execute(
        """
        SELECT rolling_drawdown, losing_streak_days
        FROM daily_pnl_summary
        ORDER BY trade_date DESC
        LIMIT 1
        """
    ).fetchone()

    if row is None:
        return DrawdownDecision("normal", "RISK_DRAWDOWN_OK", 0.0, 0)

    drawdown = float(row[0] or 0.0)
    streak = int(row[1] or 0)

    if drawdown >= policy.monthly_drawdown_suspend_pct:
        return DrawdownDecision("suspended", "RISK_MONTHLY_DRAWDOWN_LIMIT", drawdown, streak)
    if streak >= policy.losing_streak_reduce_only_days:
        return DrawdownDecision("reduce_only", "RISK_LOSING_STREAK_LIMIT", drawdown, streak)
    return DrawdownDecision("normal", "RISK_DRAWDOWN_OK", drawdown, streak)


def evaluate_strategy_health_guard(conn: sqlite3.Connection, policy: DrawdownPolicy, strategy_id: str) -> DrawdownDecision:
    row = conn.execute(
        """
        SELECT rolling_trades, rolling_win_rate, enabled
        FROM strategy_health
        WHERE strategy_id = ?
        """,
        (strategy_id,),
    ).fetchone()
    if row is None:
        return DrawdownDecision("normal", "RISK_STRATEGY_HEALTH_OK", 0.0, 0)

    trades = int(row[0] or 0)
    win_rate = float(row[1] or 0.0)
    enabled = int(row[2] or 0)
    if enabled == 0:
        return DrawdownDecision("suspended", "RISK_STRATEGY_DISABLED", 0.0, 0)
    if trades >= policy.rolling_win_rate_window and win_rate < policy.rolling_win_rate_disable_threshold:
        return DrawdownDecision("reduce_only", "RISK_LOW_WIN_RATE", 0.0, 0)
    return DrawdownDecision("normal", "RISK_STRATEGY_HEALTH_OK", 0.0, 0)


def apply_drawdown_actions(conn: sqlite3.Connection, decision: DrawdownDecision) -> None:
    """Persist drawdown mode into trading_locks/incidents (best-effort).

    Sentinel/risk-engine can use this as a hard signal:
    - suspended => trading_locked
    - reduce_only => reduce_only_mode

    Responsibility split (P1): this is a *Sentinel* hard guard, not a PM veto.
    """

    if decision.risk_mode == "normal":
        return

    if _table_exists(conn, "trading_locks"):
        # lock_id=1 reserved for drawdown guard
        conn.execute(
            """
            INSERT INTO trading_locks(lock_id, locked, reason_code, locked_at, unlock_after, note)
            VALUES ('drawdown_guard', ?, ?, datetime('now'), NULL, ?)
            ON CONFLICT(lock_id) DO UPDATE SET
              locked = excluded.locked,
              reason_code = excluded.reason_code,
              locked_at = excluded.locked_at,
              unlock_after = excluded.unlock_after,
              note = excluded.note
            """,
            (
                1 if decision.risk_mode == "suspended" else 0,
                decision.reason_code,
                f"mode={decision.risk_mode} drawdown={decision.drawdown:.4f} streak_days={decision.losing_streak_days}",
            ),
        )

    if _table_exists(conn, "incidents"):
        conn.execute(
            """
            INSERT INTO incidents(incident_id, ts, severity, source, code, detail_json, resolved)
            VALUES (lower(hex(randomblob(16))), datetime('now'), ?, 'drawdown_guard', ?, ?, 0)
            """,
            (
                "critical" if decision.risk_mode == "suspended" else "warn",
                decision.reason_code,
                '{"risk_mode": "%s", "drawdown": %s, "losing_streak_days": %s}'
                % (decision.risk_mode, decision.drawdown, decision.losing_streak_days),
            ),
        )
