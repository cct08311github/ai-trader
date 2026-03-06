"""proposal_executor.py — strategy_proposals 執行鏈

掃描 status='approved' 的提案，按類型回傳執行意圖：
  - POSITION_REBALANCE: 回傳 SellIntent，由 ticker_watcher 透過 broker 實際執行
  - STRATEGY_DIRECTION: 記錄但不自動執行（需人工操作）

使用方式（ticker_watcher 每輪掃盤後呼叫）：
    from openclaw.proposal_executor import execute_pending_proposals
    intents, n_noted = execute_pending_proposals(conn)
"""
import json
import logging
import sqlite3
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SellIntent:
    proposal_id: str
    symbol: str
    qty: int
    price: float


def execute_pending_proposals(conn: sqlite3.Connection) -> tuple[list[SellIntent], int]:
    """掃描 approved proposals，回傳待執行的 sell intents。

    Returns:
        (sell_intents, n_noted): sell 意圖清單 + 已標記 noted 的 STRATEGY_DIRECTION 數量
    """
    rows = conn.execute(
        """SELECT proposal_id, target_rule, proposal_json
           FROM strategy_proposals
           WHERE status='approved'
             AND (expires_at IS NULL OR expires_at > ?)""",
        (int(time.time()),)
    ).fetchall()

    intents: list[SellIntent] = []
    n_noted = 0

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

                if price <= 0:
                    log.warning("Proposal %s: %s has no valid price (%.2f), skipping",
                                proposal_id, symbol, price)
                    continue

                intents.append(SellIntent(
                    proposal_id=proposal_id,
                    symbol=symbol,
                    qty=qty_to_sell,
                    price=price,
                ))
                log.info("Proposal %s: %s sell %d @ %.2f → intent created",
                         proposal_id, symbol, qty_to_sell, price)

            elif target_rule == "STRATEGY_DIRECTION":
                log.info("Proposal %s (STRATEGY_DIRECTION): noted, no auto-action", proposal_id)
                conn.execute(
                    "UPDATE strategy_proposals SET status='noted' WHERE proposal_id=?",
                    (proposal_id,)
                )
                conn.commit()
                n_noted += 1

        except Exception as e:
            log.error("Error processing proposal %s: %s", proposal_id, e)

    return intents, n_noted


def mark_intent_executed(conn: sqlite3.Connection, proposal_id: str) -> None:
    """Broker 成交後，由 ticker_watcher 呼叫標記 proposal 為 executed。"""
    conn.execute(
        "UPDATE strategy_proposals SET status='executed', decided_at=? "
        "WHERE proposal_id=?",
        (int(time.time()), proposal_id)
    )
    conn.commit()


def mark_intent_failed(conn: sqlite3.Connection, proposal_id: str, reason: str = "") -> None:
    """Broker 拒絕或執行異常時標記 proposal 為 failed，防止無限重試。"""
    conn.execute(
        "UPDATE strategy_proposals SET status='failed', decided_at=?, "
        "supporting_evidence=COALESCE(supporting_evidence,'') || ? "
        "WHERE proposal_id=?",
        (int(time.time()), f" | broker_reject: {reason}", proposal_id)
    )
    conn.commit()
