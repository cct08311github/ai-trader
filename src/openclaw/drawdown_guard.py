from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass
class DrawdownPolicy:
    monthly_drawdown_suspend_pct: float = 0.15
    losing_streak_reduce_only_days: int = 5
    rolling_win_rate_disable_threshold: float = 0.40
    rolling_win_rate_window: int = 20
    # DEEP_SUSPEND: consecutive monthly losses exceeding the threshold
    deep_suspend_consecutive_loss_months: int = 3
    deep_suspend_monthly_loss_pct: float = 0.10


@dataclass
class DrawdownDecision:
    risk_mode: str  # normal/reduce_only/suspended/deep_suspend
    reason_code: str
    drawdown: float
    losing_streak_days: int
    # extra context carried by deep_suspend
    consecutive_loss_months: int = 0
    monthly_losses: list = field(default_factory=list)


_DEEP_SUSPEND_CHECKLIST = """
📋 *DEEP SUSPEND 復盤 Checklist*

以下問題需全部確認後，方可人工重啟交易：

1. [ ] 是否已找出連續虧損的根本原因（市場 Regime 變化 / 策略失效 / 執行問題）？
2. [ ] 策略是否已針對虧損期間的市場環境進行回測調整？
3. [ ] 風控參數（月最大虧損、持倉比重上限）是否重新校正？
4. [ ] 是否已確認模擬帳戶連續 5 個交易日正向表現？
5. [ ] 是否已通知相關 Stakeholder 並取得重啟授權？

✅ 確認完成後，請執行：
  `POST /api/control/clear-deep-suspend`（含授權 token）

⛔ 未完成以上 checklist 前，系統將維持 DEEP_SUSPEND，拒絕一切開倉指令。
""".strip()


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


def _compute_monthly_returns(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    """Compute monthly NAV return from daily_pnl_summary.

    Returns list of (YYYY-MM, monthly_return) ordered oldest-first.
    monthly_return = (last_nav_of_month - first_nav_of_month) / first_nav_of_month
    """
    if not _table_exists(conn, "daily_pnl_summary"):
        return []

    rows = conn.execute(
        """
        SELECT strftime('%Y-%m', trade_date) AS month,
               MIN(nav_start) AS first_nav,
               MAX(nav_end)   AS last_nav_approx,
               MIN(trade_date) AS first_date,
               MAX(trade_date) AS last_date
        FROM daily_pnl_summary
        WHERE nav_start > 0
        GROUP BY month
        ORDER BY month ASC
        """
    ).fetchall()

    # Use nav_start of first day and nav_end of last day for accuracy
    results: list[tuple[str, float]] = []
    for row in rows:
        month, _, _, first_date, last_date = row
        nav_start_row = conn.execute(
            "SELECT nav_start FROM daily_pnl_summary WHERE trade_date = ?", (first_date,)
        ).fetchone()
        nav_end_row = conn.execute(
            "SELECT nav_end FROM daily_pnl_summary WHERE trade_date = ?", (last_date,)
        ).fetchone()
        if not nav_start_row or not nav_end_row:
            continue
        nav_start = float(nav_start_row[0] or 0)
        nav_end = float(nav_end_row[0] or 0)
        if nav_start <= 0:
            continue
        results.append((month, (nav_end - nav_start) / nav_start))

    return results


def evaluate_deep_suspend_guard(conn: sqlite3.Connection, policy: DrawdownPolicy) -> DrawdownDecision:
    """Check if consecutive monthly losses warrant DEEP_SUSPEND.

    Triggers when the last N complete months each lost >= deep_suspend_monthly_loss_pct.
    N = policy.deep_suspend_consecutive_loss_months (default 3).

    Returns DrawdownDecision with risk_mode='deep_suspend' if triggered,
    otherwise risk_mode='normal'.
    """
    monthly = _compute_monthly_returns(conn)
    n = policy.deep_suspend_consecutive_loss_months
    threshold = -abs(policy.deep_suspend_monthly_loss_pct)

    if len(monthly) < n:
        return DrawdownDecision("normal", "RISK_DEEP_SUSPEND_INSUFFICIENT_DATA", 0.0, 0)

    last_n = monthly[-n:]
    losing_months = [(m, r) for m, r in last_n if r <= threshold]

    if len(losing_months) == n:
        avg_loss = sum(r for _, r in losing_months) / n
        return DrawdownDecision(
            "deep_suspend",
            "RISK_DEEP_SUSPEND_CONSECUTIVE_LOSS",
            abs(avg_loss),
            0,
            consecutive_loss_months=n,
            monthly_losses=[{"month": m, "return": round(r, 4)} for m, r in last_n],
        )

    return DrawdownDecision("normal", "RISK_DEEP_SUSPEND_OK", 0.0, 0)


def get_restart_checklist() -> str:
    """Return the human review checklist required before restarting after DEEP_SUSPEND."""
    return _DEEP_SUSPEND_CHECKLIST


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
    - deep_suspend => permanent trading_locked until human review
    - suspended    => trading_locked
    - reduce_only  => reduce_only_mode

    Responsibility split (P1): this is a *Sentinel* hard guard, not a PM veto.
    """

    if decision.risk_mode == "normal":
        return

    locked = decision.risk_mode in ("suspended", "deep_suspend")

    if _table_exists(conn, "trading_locks"):
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
                1 if locked else 0,
                decision.reason_code,
                f"mode={decision.risk_mode} drawdown={decision.drawdown:.4f} streak_days={decision.losing_streak_days}",
            ),
        )

    if _table_exists(conn, "incidents"):
        detail = {
            "risk_mode": decision.risk_mode,
            "drawdown": decision.drawdown,
            "losing_streak_days": decision.losing_streak_days,
        }
        if decision.risk_mode == "deep_suspend":
            detail["consecutive_loss_months"] = decision.consecutive_loss_months
            detail["monthly_losses"] = decision.monthly_losses
        severity = "warn" if decision.risk_mode == "reduce_only" else "critical"
        conn.execute(
            """
            INSERT INTO incidents(incident_id, ts, severity, source, code, detail_json, resolved)
            VALUES (lower(hex(randomblob(16))), datetime('now'), ?, 'drawdown_guard', ?, ?, 0)
            """,
            (
                severity,
                decision.reason_code,
                json.dumps(detail, ensure_ascii=True),
            ),
        )

    # DEEP_SUSPEND: send Telegram notification with human review checklist
    if decision.risk_mode == "deep_suspend":
        _notify_deep_suspend(decision)


def _notify_deep_suspend(decision: DrawdownDecision) -> None:
    """Send Telegram alert with restart checklist when DEEP_SUSPEND is triggered."""
    try:
        from openclaw.tg_notify import send_message  # lazy import

        monthly_summary = "\n".join(
            f"  {row['month']}: {row['return']:+.1%}"
            for row in decision.monthly_losses
        )
        msg = (
            f"🚨 <b>[DEEP SUSPEND 觸發]</b>\n"
            f"連續 {decision.consecutive_loss_months} 個月虧損 ≥ {decision.drawdown:.1%}（平均），\n"
            f"系統已自動切換為 DEEP_SUSPEND，拒絕一切開倉指令。\n\n"
            f"<b>近期月度績效：</b>\n{monthly_summary}\n\n"
            f"<b>重啟前必須完成以下 Checklist：</b>\n"
            f"{_DEEP_SUSPEND_CHECKLIST}"
        )
        send_message(msg)
    except Exception:  # noqa: BLE001
        pass  # 通知失敗不影響主流程；incident 已寫入 DB
