"""proposal_executor.py — strategy_proposals 執行鏈

掃描 status='approved' 的提案，按類型執行對應動作：
  - POSITION_REBALANCE: 建立部分 sell 訂單
  - STRATEGY_DIRECTION: 記錄但不自動執行（需人工操作）

使用方式（ticker_watcher 每輪掃盤後呼叫）：
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(conn, dry_run=False)
"""
import json
import logging
import sqlite3
import time
import uuid

log = logging.getLogger(__name__)

_STRATEGY_VERSION = "proposal_executor_v1"


def _create_sell_order(conn: sqlite3.Connection, symbol: str, qty: int,
                       price: float, proposal_id: str) -> str:
    order_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO orders
           (order_id, decision_id, broker_order_id, ts_submit,
            symbol, side, qty, price, order_type, tif, status, strategy_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, proposal_id, f"PROP-{proposal_id[:8]}",
         time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
         symbol, "sell", qty, price, "market", "ROD", "submitted",
         _STRATEGY_VERSION)
    )
    return order_id


def execute_pending_proposals(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """執行所有 approved proposals。

    Args:
        conn:    SQLite 連線
        dry_run: True = 只 log，不實際建立訂單（預設安全模式）

    Returns:
        成功執行的 proposal 數量
    """
    rows = conn.execute(
        """SELECT proposal_id, target_rule, proposal_json
           FROM strategy_proposals
           WHERE status='approved'
             AND (expires_at IS NULL OR expires_at > ?)""",
        (int(time.time()),)
    ).fetchall()

    executed = 0
    for proposal_id, target_rule, proposal_json_str in rows:
        try:
            proposal = json.loads(proposal_json_str or "{}")

            if target_rule == "POSITION_REBALANCE":
                symbol = proposal.get("symbol")
                reduce_pct = float(proposal.get("reduce_pct", 0))
                if not symbol or reduce_pct <= 0:
                    log.warning("Invalid POSITION_REBALANCE proposal %s", proposal_id)
                    continue

                pos = conn.execute(
                    "SELECT quantity, current_price FROM positions WHERE symbol=?",
                    (symbol,)
                ).fetchone()
                if not pos or pos[0] <= 0:
                    log.info("Proposal %s: no position in %s", proposal_id, symbol)
                    conn.execute(
                        "UPDATE strategy_proposals SET status='skipped' WHERE proposal_id=?",
                        (proposal_id,)
                    )
                    conn.commit()
                    continue

                qty_to_sell = max(1, int(pos[0] * reduce_pct))
                price = pos[1] or 0.0

                log.info("Proposal %s: %s sell %d @ %.2f (dry_run=%s)",
                         proposal_id, symbol, qty_to_sell, price, dry_run)

                if not dry_run:
                    _create_sell_order(conn, symbol, qty_to_sell, price, proposal_id)
                    conn.execute(
                        "UPDATE strategy_proposals SET status='executed', decided_at=? "
                        "WHERE proposal_id=?",
                        (int(time.time()), proposal_id)
                    )
                    conn.commit()
                    executed += 1

            elif target_rule == "STRATEGY_DIRECTION":
                log.info("Proposal %s (STRATEGY_DIRECTION): noted, no auto-action", proposal_id)
                if not dry_run:
                    conn.execute(
                        "UPDATE strategy_proposals SET status='noted' WHERE proposal_id=?",
                        (proposal_id,)
                    )
                    conn.commit()

        except Exception as e:
            log.error("Error executing proposal %s: %s", proposal_id, e)

    return executed
