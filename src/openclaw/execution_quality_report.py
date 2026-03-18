# src/openclaw/execution_quality_report.py
"""execution_quality_report.py — 實盤 vs 模擬帳戶執行品質比對

功能：
- 比對同日同標的同方向的實盤與模擬成交價差
- 計算執行滑點（basis points）
- 輸出結構化比對結果，供 Telegram 週報使用

Issue #284
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SlippagePair:
    """一組實盤 vs 模擬的比對結果。"""
    symbol: str
    trade_date: str
    side: str
    sim_avg_price: float
    live_avg_price: float
    sim_qty: int
    live_qty: int

    @property
    def slippage_bps(self) -> float:
        """
        執行滑點（basis points）。
        - buy：實盤比模擬貴多少（正值 = 實盤成本較高）
        - sell：實盤比模擬少收多少（正值 = 實盤回收較少）
        """
        if self.sim_avg_price <= 0:
            return 0.0
        if self.side == "buy":
            return (self.live_avg_price / self.sim_avg_price - 1) * 10_000
        else:  # sell
            return (self.sim_avg_price / self.live_avg_price - 1) * 10_000

    @property
    def slippage_pct(self) -> float:
        return self.slippage_bps / 100


@dataclass
class ExecutionQualityReport:
    """週期性執行品質報告。"""
    period_days: int
    pairs: list[SlippagePair] = field(default_factory=list)
    sim_only_trades: int = 0   # 僅有模擬、無對應實盤的交易日數
    live_only_trades: int = 0  # 僅有實盤、無對應模擬的交易日數

    @property
    def avg_slippage_bps(self) -> Optional[float]:
        if not self.pairs:
            return None
        return round(sum(p.slippage_bps for p in self.pairs) / len(self.pairs), 2)

    @property
    def max_slippage_bps(self) -> Optional[float]:
        if not self.pairs:
            return None
        return round(max(p.slippage_bps for p in self.pairs), 2)

    @property
    def has_data(self) -> bool:
        return bool(self.pairs)


def compute_execution_quality(
    conn: sqlite3.Connection,
    days: int = 7,
) -> ExecutionQualityReport:
    """計算近 N 日的執行品質比對。

    查詢 orders + fills，以 (symbol, date(ts_submit, '+8 hours'), side)
    為鍵，比對模擬帳戶與實盤帳戶的加權平均成交價。

    Args:
        conn: SQLite 連線（需有 orders、fills 表）
        days: 回顧天數，預設 7（週報）

    Returns:
        ExecutionQualityReport
    """
    rows = conn.execute(
        """
        WITH filled_orders AS (
            SELECT
                o.order_id,
                o.symbol,
                o.side,
                o.account_mode,
                date(o.ts_submit, '+8 hours') AS trade_date,
                SUM(f.qty)                      AS total_qty,
                SUM(f.qty * f.price) / SUM(f.qty) AS avg_price
            FROM orders o
            JOIN fills f ON f.order_id = o.order_id
            WHERE o.ts_submit >= datetime('now', ?)
              AND o.status IN ('filled', 'partially_filled')
            GROUP BY o.order_id
        ),
        by_mode AS (
            SELECT
                symbol, side, trade_date, account_mode,
                SUM(total_qty * avg_price) / SUM(total_qty) AS wt_avg_price,
                SUM(total_qty)                               AS total_qty
            FROM filled_orders
            GROUP BY symbol, side, trade_date, account_mode
        )
        SELECT
            s.symbol, s.side, s.trade_date,
            s.wt_avg_price AS sim_price, s.total_qty AS sim_qty,
            l.wt_avg_price AS live_price, l.total_qty AS live_qty
        FROM by_mode s
        JOIN by_mode l
            ON  l.symbol     = s.symbol
            AND l.side       = s.side
            AND l.trade_date = s.trade_date
            AND l.account_mode = 'live'
        WHERE s.account_mode = 'simulation'
        ORDER BY s.trade_date DESC, s.symbol
        """,
        (f"-{days} days",),
    ).fetchall()

    pairs = [
        SlippagePair(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            side=row["side"],
            sim_avg_price=row["sim_price"],
            live_avg_price=row["live_price"],
            sim_qty=row["sim_qty"],
            live_qty=row["live_qty"],
        )
        for row in rows
    ]

    # 統計只在單一模式出現的交易（無法配對）
    # SQLite 不支援 FULL OUTER JOIN，用 UNION + LEFT JOIN 模擬
    unpaired = conn.execute(
        """
        WITH filled_keys AS (
            SELECT
                o.symbol, o.side, o.account_mode,
                date(o.ts_submit, '+8 hours') AS trade_date
            FROM orders o
            JOIN fills f ON f.order_id = o.order_id
            WHERE o.ts_submit >= datetime('now', ?)
              AND o.status IN ('filled', 'partially_filled')
            GROUP BY o.symbol, o.side, o.account_mode, trade_date
        ),
        sim_keys  AS (SELECT symbol, side, trade_date FROM filled_keys WHERE account_mode='simulation'),
        live_keys AS (SELECT symbol, side, trade_date FROM filled_keys WHERE account_mode='live'),
        sim_only AS (
            SELECT COUNT(*) AS cnt FROM sim_keys s
            WHERE NOT EXISTS (
                SELECT 1 FROM live_keys l
                WHERE l.symbol=s.symbol AND l.side=s.side AND l.trade_date=s.trade_date
            )
        ),
        live_only AS (
            SELECT COUNT(*) AS cnt FROM live_keys l
            WHERE NOT EXISTS (
                SELECT 1 FROM sim_keys s
                WHERE s.symbol=l.symbol AND s.side=l.side AND s.trade_date=l.trade_date
            )
        )
        SELECT (SELECT cnt FROM sim_only) AS sim_only,
               (SELECT cnt FROM live_only) AS live_only
        """,
        (f"-{days} days",),
    ).fetchone()

    return ExecutionQualityReport(
        period_days=days,
        pairs=pairs,
        sim_only_trades=unpaired["sim_only"] if unpaired else 0,
        live_only_trades=unpaired["live_only"] if unpaired else 0,
    )


def format_telegram_report(report: ExecutionQualityReport) -> str:
    """格式化為 Telegram 週報訊息。"""
    lines = [
        f"📊 *執行品質週報*（近 {report.period_days} 日）",
        "",
    ]

    if not report.has_data:
        lines.append("本期無實盤 vs 模擬配對交易，無法計算執行滑點。")
        lines.append(f"（模擬單數：{report.sim_only_trades}，實盤單數：{report.live_only_trades}）")
        return "\n".join(lines)

    avg = report.avg_slippage_bps
    max_slip = report.max_slippage_bps
    lines += [
        f"配對交易筆數：{len(report.pairs)}",
        f"平均滑點：{avg:+.1f} bps",
        f"最大滑點：{max_slip:+.1f} bps",
        "",
        "明細（前 5 筆）：",
    ]

    top5 = sorted(report.pairs, key=lambda p: abs(p.slippage_bps), reverse=True)[:5]
    for p in top5:
        direction = "↑買" if p.side == "buy" else "↓賣"
        lines.append(
            f"  {p.symbol} {direction} {p.trade_date}："
            f" 模擬={p.sim_avg_price:.2f} 實盤={p.live_avg_price:.2f}"
            f" 滑點={p.slippage_bps:+.1f}bps"
        )

    if report.sim_only_trades or report.live_only_trades:
        lines += [
            "",
            f"⚠️ 無配對：模擬單 {report.sim_only_trades} 筆，實盤單 {report.live_only_trades} 筆",
        ]

    return "\n".join(lines)
