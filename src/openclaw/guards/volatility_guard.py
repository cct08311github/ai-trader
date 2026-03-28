"""volatility_guard.py — 雙重觸發市場波動閘門

暫停「買入/加碼」方向的 auto-review，不影響賣出、止損、
concentration auto-reduce 或人工操作。

觸發條件（二擇一，任一成立即觸發）：
1. 【先行指標】大盤（加權指數 Y9999）當日跌幅 > VOLATILITY_GATE_TAIEX_DROP（預設 -2%）
2. 【落後指標】持倉平均未實現損益 < VOLATILITY_GATE_PNL_THRESHOLD（預設 -5%）
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Optional

from openclaw.guards.base import Guard, GuardContext, GuardResult

log = logging.getLogger(__name__)

# 買入方向關鍵字（lower-cased）
_BUY_KEYWORDS = frozenset({"buy", "bullish", "offensive", "增加", "加碼", "買入", "多頭"})


def _is_buy_direction(direction: str) -> bool:
    d = direction.lower()
    return any(kw in d for kw in _BUY_KEYWORDS)


class VolatilityGate(Guard):
    """極端行情暫停新建倉的自動放行。

    效果：當雙重觸發條件任一成立時，標記方向為「買入」的 auto-review 為 blocked。
    不影響：賣出方向、人工操作、concentration auto-reduce。

    用於 proposal_reviewer auto-review 決策前的快速市況判斷，
    不接入正式 GuardChain（GuardChain 用於 order-level 風控）。
    """

    _PNL_THRESHOLD: float = float(
        os.environ.get("VOLATILITY_GATE_PNL_THRESHOLD", "-0.05")
    )
    _TAIEX_DROP_THRESHOLD: float = float(
        os.environ.get("VOLATILITY_GATE_TAIEX_DROP", "-0.02")
    )

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        direction = str(
            (ctx.pm_context or {}).get("direction", "")
        )
        # Volatility gate only applies to buy direction
        if not _is_buy_direction(direction):
            return GuardResult(passed=True, reason="非買入方向，跳過波動閘門")

        # Leading indicator: TAIEX daily change
        taiex_change = _get_taiex_daily_change(ctx.conn)
        if taiex_change is not None and taiex_change < self._TAIEX_DROP_THRESHOLD:
            return GuardResult(
                passed=False,
                reject_code="VOLATILITY_GATE_TAIEX",
                reason=f"大盤急跌 {taiex_change:.1%}（先行指標），暫停買入自動放行",
                metadata={"taiex_change": taiex_change},
            )

        # Lagging indicator: avg unrealized PnL across positions
        avg_pnl = _get_avg_unrealized_pnl(ctx.conn)
        if avg_pnl is not None and avg_pnl < self._PNL_THRESHOLD:
            return GuardResult(
                passed=False,
                reject_code="VOLATILITY_GATE_PNL",
                reason=f"持倉平均未實現損益 {avg_pnl:.1%}（落後指標），暫停買入自動放行",
                metadata={"avg_unrealized_pnl": avg_pnl},
            )

        return GuardResult(passed=True, reason="市場正常", reject_code="")


def _get_taiex_daily_change(conn: sqlite3.Connection) -> Optional[float]:
    """查 eod_prices 取加權指數（Y9999）最近兩日收盤算日漲跌幅。"""
    try:
        rows = conn.execute(
            """SELECT close FROM eod_prices
               WHERE symbol = 'Y9999'
               ORDER BY trade_date DESC LIMIT 2"""
        ).fetchall()
        if len(rows) < 2:
            return None
        today_close, prev_close = rows[0][0], rows[1][0]
        if not prev_close:
            return None
        return (today_close - prev_close) / prev_close
    except Exception:
        return None


def _get_avg_unrealized_pnl(conn: sqlite3.Connection) -> Optional[float]:
    """持倉平均未實現損益率（(current_price - avg_price) / avg_price）。"""
    try:
        row = conn.execute(
            """SELECT AVG((current_price - avg_price) / NULLIF(avg_price, 0))
               FROM positions WHERE quantity > 0"""
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    except Exception:
        return None


def check_volatility_gate(
    conn: sqlite3.Connection,
    direction: str,
) -> GuardResult:
    """Convenience function: evaluate VolatilityGate without building GuardContext.

    Used by proposal_reviewer before auto-approving buy-direction proposals.
    """
    from openclaw.guards.base import GuardContext

    ctx = GuardContext(
        conn=conn,
        system_state=None,
        order_candidate=None,
        pm_context={"direction": direction},
    )
    return VolatilityGate().evaluate(ctx)
