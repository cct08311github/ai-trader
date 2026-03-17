# src/openclaw/trading_engine.py
"""trading_engine.py — 持倉狀態機 + 時間止損

持倉生命週期：HOLDING → EXITING（時間止損）→ [proposal_executor 執行] → CLOSED

時間止損規則（以 EOD 交易日計算，不以 tick 次數）：
  - 虧損持倉（current < avg）：10 交易日 → auto-approved proposal
  - 獲利持倉（current >= avg）：30 交易日 → pending proposal（需人工審核）
"""
import json
import logging
import sqlite3
import time
import uuid
from typing import Optional

log = logging.getLogger(__name__)

_LOSING_THRESHOLD_DAYS  = 10
_PROFIT_THRESHOLD_DAYS  = 30
_ACTIVE_STATES = ("HOLDING", "HOLDING_PARTIAL")


def _get_latest_trading_day(conn: sqlite3.Connection) -> Optional[str]:
    """取 eod_prices 最新的 trade_date（當日基準）"""
    row = conn.execute(
        "SELECT MAX(trade_date) FROM eod_prices"
    ).fetchone()
    return row[0] if row else None


def _count_hold_days(conn: sqlite3.Connection, symbol: str, entry_day: str) -> int:
    """計算 entry_day 之後的 eod_prices 筆數（= 交易日數）"""
    row = conn.execute(
        "SELECT COUNT(*) FROM eod_prices WHERE symbol=? AND trade_date > ?",
        (symbol, entry_day),
    ).fetchone()
    return row[0] if row else 0


def _record_event(
    conn: sqlite3.Connection,
    symbol: str,
    from_state: Optional[str],
    to_state: str,
    reason: str,
) -> None:
    today = _get_latest_trading_day(conn)
    if today is None:
        today = "unknown"  # fallback for empty eod_prices (trading_day is NOT NULL)
        log.warning("[trading_engine] eod_prices is empty; using 'unknown' for trading_day")
    conn.execute(
        """INSERT INTO position_events
           (event_id, symbol, from_state, to_state, reason, trading_day, ts)
           VALUES (?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), symbol, from_state, to_state, reason, today,
         int(time.time())),
    )


def _create_time_stop_proposal(
    conn: sqlite3.Connection,
    symbol: str,
    hold_days: int,
    is_losing: bool,
    qty: int,
) -> None:
    proposal_id = str(uuid.uuid4())
    # 虧損全出場；獲利出 50%
    reduce_pct = 1.0 if is_losing else 0.5
    threshold  = _LOSING_THRESHOLD_DAYS if is_losing else _PROFIT_THRESHOLD_DAYS
    pnl_label  = "虧損" if is_losing else "獲利"
    status     = "approved" if is_losing else "pending"

    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            proposed_value, current_value, supporting_evidence, confidence,
            requires_human_approval, status, proposal_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            proposal_id, "trading_engine", "POSITION_REBALANCE", "portfolio",
            f"時間止損：{symbol} {pnl_label}持倉超過 {threshold} 交易日",
            None,  # current_value: 時間止損不需要當前數值
            f"{pnl_label}持倉 {hold_days} 交易日，觸發時間止損",
            0.85, int(not is_losing), status,
            json.dumps({"symbol": symbol, "reduce_pct": reduce_pct,
                        "type": "time_stop", "hold_days": hold_days}),
            int(time.time()),
        ),
    )


def tick(conn: sqlite3.Connection, symbol: str) -> None:
    """每次掃盤呼叫：清理過期 CANDIDATE、檢查時間止損。

    注意：ticker_watcher 使用 isolation_level=None（autocommit），因此
    三個寫入（proposal + event + positions update）使用 BEGIN/COMMIT 確保原子性。
    """
    # 1. 清理過期 CANDIDATE（今日之前的都清除，保留當日 CANDIDATE 供本輪掃盤使用）
    # 邊界為 today（非昨日）：今日產生的 CANDIDATE 須存活到下一交易日才清除
    today = _get_latest_trading_day(conn)
    if today:
        conn.execute(
            "DELETE FROM position_candidates WHERE trading_day < ?",
            (today,),
        )
        conn.commit()

    # 2. 讀取持倉
    pos = conn.execute(
        "SELECT quantity, avg_price, current_price, state, entry_trading_day "
        "FROM positions WHERE symbol=?",
        (symbol,),
    ).fetchone()

    if pos is None or (pos["quantity"] or 0) <= 0:
        return

    state = pos["state"] or "HOLDING"
    if state not in _ACTIVE_STATES:
        return  # EXITING/CLOSED 不重複觸發

    entry_day = pos["entry_trading_day"]
    if not entry_day:
        return  # 無進場日資料，跳過

    hold_days = _count_hold_days(conn, symbol, entry_day)
    avg_price     = pos["avg_price"] or 0
    if avg_price <= 0:
        log.warning(
            "[trading_engine] %s has avg_price=%s, skipping time stop",
            symbol, pos["avg_price"],
        )
        return
    current_price = pos["current_price"] or avg_price
    is_losing     = current_price < avg_price
    threshold     = _LOSING_THRESHOLD_DAYS if is_losing else _PROFIT_THRESHOLD_DAYS

    if hold_days < threshold:
        return  # 未達門檻

    log.info(
        "[trading_engine] %s 時間止損 hold=%d days, is_losing=%s",
        symbol, hold_days, is_losing,
    )

    # 3. 原子寫入：建立 proposal + 記錄 event + 更新 state
    # 使用 conn.in_transaction 相容 isolation_level=None（autocommit）與預設模式
    if conn.in_transaction:
        # 已在 transaction 內（預設 isolation_level）
        _create_time_stop_proposal(conn, symbol, hold_days, is_losing,
                                   pos["quantity"])
        _record_event(conn, symbol, from_state=state, to_state="EXITING",
                      reason=f"time_stop:{hold_days}d")
        conn.execute(
            "UPDATE positions SET state='EXITING' WHERE symbol=?",
            (symbol,),
        )
    else:
        # autocommit 模式（isolation_level=None）— 手動管理 transaction
        conn.execute("BEGIN")
        try:
            _create_time_stop_proposal(conn, symbol, hold_days, is_losing,
                                       pos["quantity"])
            _record_event(conn, symbol, from_state=state, to_state="EXITING",
                          reason=f"time_stop:{hold_days}d")
            conn.execute(
                "UPDATE positions SET state='EXITING' WHERE symbol=?",
                (symbol,),
            )
            conn.execute("COMMIT")
        except Exception:  # noqa: BLE001 — rollback guard; must catch all to ensure atomicity
            log.exception("[trading_engine] transaction failed for %s; rolling back", symbol)
            conn.execute("ROLLBACK")
            raise
