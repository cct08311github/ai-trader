"""eod_exit_check.py — 盤後 exit signal fallback

盤中 ticker_watcher 可能因 Shioaji 斷線或其他異常而遺漏 exit signal。
本模組在 eod_ingest 完成後，對所有持倉用最新 eod_prices 重跑 evaluate_exit()，
若觸發 stop_loss / trailing_stop / take_profit，寫入 decision 表並發送 Telegram 通知。

不執行實際下單 — 僅記錄 decision + 通知，由下一交易日盤中 watcher 執行。
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from openclaw.signal_logic import SignalParams, evaluate_exit

log = logging.getLogger(__name__)

_TZ_TWN = timezone(timedelta(hours=8))


def _get_positions_with_hwm(conn: sqlite3.Connection) -> list[dict]:
    """取得所有持倉（含 HWM 與 entry_trading_day）。"""
    rows = conn.execute(
        "SELECT symbol, quantity, avg_price, high_water_mark, entry_trading_day "
        "FROM positions WHERE quantity > 0"
    ).fetchall()
    return [
        {
            "symbol": r[0],
            "quantity": int(r[1]),
            "avg_price": float(r[2]),
            "high_water_mark": float(r[3]) if r[3] else None,
            "entry_trading_day": r[4],
        }
        for r in rows
    ]


def _get_eod_closes(conn: sqlite3.Connection, symbol: str, days: int = 60) -> list[float]:
    """從 eod_prices 取最近 N 日收盤價（由舊到新）。"""
    rows = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT ?",
        (symbol, days),
    ).fetchall()
    return [r[0] for r in reversed(rows)]


def _persist_eod_decision(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    signal_reason: str,
) -> str:
    """寫入 decision 表記錄 EOD fallback exit signal。"""
    decision_id = str(uuid.uuid4())
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO decisions (decision_id, ts, symbol, strategy_id, strategy_version, "
        "signal_side, signal_score, signal_ttl_ms, reason_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            decision_id,
            now_iso,
            symbol,
            "eod_exit_fallback",
            "v1",
            "sell",
            0.95,
            86400000,  # 24h TTL
            f'{{"source": "eod_exit_check", "reason": "{signal_reason}"}}',
        ),
    )
    conn.commit()
    return decision_id


def _send_telegram_alert(symbol: str, reason: str, avg_price: float, latest_close: float) -> None:
    """發送 Telegram 止損/止盈告警。"""
    try:
        from openclaw.tg_notify import send_alert
        pnl_pct = (latest_close - avg_price) / avg_price * 100 if avg_price > 0 else 0
        msg = (
            f"⚠️ EOD Exit Signal ─ {symbol}\n"
            f"原因: {reason}\n"
            f"均價: {avg_price:.2f} → 收盤: {latest_close:.2f} ({pnl_pct:+.1f}%)\n"
            f"下一交易日開盤請評估是否執行賣出"
        )
        send_alert(msg)
    except Exception as e:
        log.warning("[eod_exit_check] Telegram alert failed for %s: %s", symbol, e)


def run_eod_exit_check(
    conn: sqlite3.Connection,
    params: Optional[SignalParams] = None,
) -> list[dict]:
    """對所有持倉用最新 eod_prices 重跑 evaluate_exit()。

    Returns:
        list of dicts with keys: symbol, signal, reason, decision_id
    """
    if params is None:
        params = SignalParams()

    old_row_factory = conn.row_factory
    conn.row_factory = None
    try:
        positions = _get_positions_with_hwm(conn)
    finally:
        conn.row_factory = old_row_factory

    results: List[dict] = []

    for pos in positions:
        symbol = pos["symbol"]
        conn.row_factory = None
        try:
            closes = _get_eod_closes(conn, symbol)
        finally:
            conn.row_factory = old_row_factory

        if len(closes) < 5:
            log.debug("[eod_exit_check] %s: insufficient data (%d closes)", symbol, len(closes))
            continue

        sig = evaluate_exit(
            closes,
            avg_price=pos["avg_price"],
            high_water_mark=pos["high_water_mark"],
            params=params,
        )

        if sig.signal != "sell":
            continue

        log.info("[eod_exit_check] %s: EXIT signal — %s", symbol, sig.reason)

        conn.row_factory = None
        try:
            decision_id = _persist_eod_decision(
                conn, symbol=symbol, signal_reason=sig.reason,
            )
        finally:
            conn.row_factory = old_row_factory

        latest_close = closes[-1] if closes else 0
        _send_telegram_alert(symbol, sig.reason, pos["avg_price"], latest_close)

        results.append({
            "symbol": symbol,
            "signal": sig.signal,
            "reason": sig.reason,
            "decision_id": decision_id,
        })

    return results
