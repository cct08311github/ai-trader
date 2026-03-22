"""performance_summary.py — 績效閉環模組 (#387)

整合 daily_snapshot、pnl_engine、signal_aggregator 的績效數據，
輸出一份 summary dict 供 EOD Telegram 通知和 API 使用。

呼叫方式：
  from openclaw.performance_summary import build_daily_summary, check_nav_staleness
  summary = build_daily_summary(conn, trade_date="2026-03-19")
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import Optional

log = logging.getLogger(__name__)

_NAV_STALE_DAYS = 5  # daily_nav 連續 N 天無記錄 → 觸發 incident


@dataclass(frozen=True)
class DailyPerformanceSummary:
    """每日績效摘要。"""
    trade_date: str
    nav: float
    nav_change_pct: float          # vs 前一日
    realized_pnl_today: float
    realized_pnl_cumulative: float
    unrealized_pnl: float
    win_rate_28d: Optional[float]  # 28 日滾動勝率
    profit_factor_28d: Optional[float]
    total_trades_28d: int
    signal_attribution: dict       # {source: {count, win_rate}} from decisions


def _get_28d_stats(conn: sqlite3.Connection) -> tuple[Optional[float], Optional[float], int]:
    """28 日滾動勝率、Profit Factor、交易數。"""
    try:
        rows = conn.execute(
            """SELECT realized_pnl FROM daily_pnl_summary
               WHERE trade_date >= date('now', '-28 days', '+8 hours')
               ORDER BY trade_date"""
        ).fetchall()
        if not rows:
            return None, None, 0

        wins = sum(1 for r in rows if (r[0] or 0) > 0)
        total = len(rows)
        win_rate = wins / total if total > 0 else None

        gross_profit = sum(r[0] for r in rows if (r[0] or 0) > 0)
        gross_loss = abs(sum(r[0] for r in rows if (r[0] or 0) < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

        return win_rate, profit_factor, total
    except sqlite3.Error as e:
        log.warning("28d stats query failed: %s", e)
        return None, None, 0


def _get_signal_attribution(conn: sqlite3.Connection, days: int = 28) -> dict:
    """信號來源績效歸因（近 N 日）。"""
    try:
        rows = conn.execute(
            """SELECT signal_source, COUNT(*) as cnt,
                      AVG(CASE WHEN signal_score > 0.5 THEN 1.0 ELSE 0.0 END) as avg_win
               FROM decisions
               WHERE created_at > ?
               GROUP BY signal_source""",
            (int(time.time() * 1000) - days * 86400 * 1000,),
        ).fetchall()
        return {r[0]: {"count": r[1], "win_rate": round(r[2], 3) if r[2] else None} for r in rows}
    except sqlite3.Error as e:
        log.debug("signal attribution query failed: %s", e)
        return {}


def _get_today_realized_pnl(conn: sqlite3.Connection, trade_date: str) -> float:
    """查詢指定日期的已實現損益。"""
    try:
        row = conn.execute(
            "SELECT realized_pnl FROM daily_pnl_summary WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        return float(row[0]) if row and row[0] else 0.0
    except sqlite3.Error:
        return 0.0


def build_daily_summary(
    conn: sqlite3.Connection,
    trade_date: str,
) -> DailyPerformanceSummary:
    """建構每日績效摘要。

    Args:
        conn: SQLite 連線（readonly OK）
        trade_date: "YYYY-MM-DD"

    Returns:
        DailyPerformanceSummary dataclass
    """
    # NAV data from daily_nav
    nav = 0.0
    nav_prev = 0.0
    unrealized = 0.0
    realized_cum = 0.0
    try:
        row = conn.execute(
            "SELECT nav, unrealized_pnl, realized_pnl_cumulative FROM daily_nav WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        if row:
            nav = float(row[0] or 0)
            unrealized = float(row[1] or 0)
            realized_cum = float(row[2] or 0)

        prev_row = conn.execute(
            "SELECT nav FROM daily_nav WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
        if prev_row:
            nav_prev = float(prev_row[0] or 0)
    except sqlite3.Error as e:
        log.warning("NAV query failed: %s", e)

    nav_change_pct = ((nav - nav_prev) / nav_prev * 100) if nav_prev > 0 else 0.0

    # 28-day rolling stats
    win_rate, profit_factor, total_trades = _get_28d_stats(conn)

    # Signal attribution
    attribution = _get_signal_attribution(conn)

    # Today's realized PnL
    realized_today = _get_today_realized_pnl(conn, trade_date)

    return DailyPerformanceSummary(
        trade_date=trade_date,
        nav=round(nav, 2),
        nav_change_pct=round(nav_change_pct, 2),
        realized_pnl_today=round(realized_today, 2),
        realized_pnl_cumulative=round(realized_cum, 2),
        unrealized_pnl=round(unrealized, 2),
        win_rate_28d=round(win_rate, 3) if win_rate is not None else None,
        profit_factor_28d=round(profit_factor, 3) if profit_factor is not None else None,
        total_trades_28d=total_trades,
        signal_attribution=attribution,
    )


def format_summary_text(summary: DailyPerformanceSummary) -> str:
    """Format summary for Telegram notification."""
    lines = [
        f"📊 績效摘要 {summary.trade_date}",
        f"NAV: {summary.nav:,.0f} ({summary.nav_change_pct:+.2f}%)",
        f"今日已實現: {summary.realized_pnl_today:+,.0f}",
        f"累計已實現: {summary.realized_pnl_cumulative:+,.0f}",
        f"浮動損益: {summary.unrealized_pnl:+,.0f}",
    ]
    if summary.win_rate_28d is not None:
        lines.append(f"28日勝率: {summary.win_rate_28d:.1%}")
    if summary.profit_factor_28d is not None:
        lines.append(f"28日損益比: {summary.profit_factor_28d:.2f}")
    lines.append(f"28日交易數: {summary.total_trades_28d}")

    if summary.signal_attribution:
        lines.append("── 信號歸因 ──")
        for src, data in summary.signal_attribution.items():
            wr = f"{data['win_rate']:.1%}" if data.get("win_rate") is not None else "N/A"
            lines.append(f"  {src}: {data['count']}次, 勝率{wr}")

    return "\n".join(lines)


def check_nav_staleness(conn: sqlite3.Connection) -> Optional[str]:
    """Check if daily_nav has been stale for > N days.

    Returns:
        Incident message string if stale, None if OK.
    """
    try:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM daily_nav"
        ).fetchone()
        if not row or not row[0]:
            return "daily_nav table is empty — no NAV snapshots recorded"

        from datetime import datetime, timedelta, timezone
        tz_twn = timezone(timedelta(hours=8))
        last_date = datetime.strptime(row[0], "%Y-%m-%d").replace(tzinfo=tz_twn)
        now = datetime.now(tz_twn)
        gap_days = (now - last_date).days

        if gap_days > _NAV_STALE_DAYS:
            return (
                f"daily_nav stale: last snapshot {row[0]} ({gap_days} days ago), "
                f"threshold={_NAV_STALE_DAYS} days"
            )
    except (sqlite3.Error, ValueError) as e:
        return f"daily_nav staleness check failed: {e}"

    return None
