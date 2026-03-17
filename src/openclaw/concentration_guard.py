"""concentration_guard.py — 集中度守衛

自動偵測單檔倉位過度集中，生成再平衡 proposal：
  - 超過 60%：自動核准 → approved（proposal_executor 下輪掃盤自動執行）
  - 超過 40%：待審 → pending（需人工核准）
  - 低於 40%：無動作
"""
import json
import logging
import sqlite3
import time
import uuid
from typing import TypedDict

log = logging.getLogger(__name__)

_AUTO_REDUCE_THRESHOLD: float = 0.60   # 超過 60%：自動核准減倉
_WARN_THRESHOLD:        float = 0.40   # 超過 40%：生成待審 proposal
_TARGET_WEIGHT:         float = 0.30   # 目標降至 30%


class ConcentrationProposal(TypedDict):
    symbol: str
    current_weight: float
    auto_approve: bool
    reduce_pct: float


def check_concentration(
    conn: sqlite3.Connection,
    locked_symbols: set[str] | None = None,
) -> list[ConcentrationProposal]:
    """計算各持倉集中度，對超標標的生成 proposal 並寫入 DB。

    Args:
        conn: SQLite 連線
        locked_symbols: 鎖定標的集合（可買不可賣）；在集中度檢查中跳過，不產生賣出 proposal

    Returns:
        需要處理的 ConcentrationProposal 清單（含已寫入 DB 的提案資訊）
    """
    rows = conn.execute(
        "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
    ).fetchall()
    if not rows:
        return []

    total_value = sum(r[1] * (r[2] or 0) for r in rows)
    if total_value <= 0:
        return []

    # Dedup: skip symbols that already have pending submitted sell orders
    try:
        pending_symbols = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM orders WHERE side='sell' AND status='submitted'"
            ).fetchall()
        }
    except sqlite3.Error as e:
        log.error("Dedup query failed, proceeding WITHOUT dedup — "
                  "duplicate proposals may be generated: %s", e)
        pending_symbols = set()

    proposals: list[ConcentrationProposal] = []
    for symbol, qty, price in rows:
        weight = (qty * (price or 0)) / total_value
        if weight < _WARN_THRESHOLD:
            continue

        if symbol in pending_symbols:
            log.info("Concentration %s: %.1f%% — skipped (pending sell orders exist)",
                     symbol, weight * 100)
            continue

        if locked_symbols and symbol in locked_symbols:
            log.warning("Concentration %s: %.1f%% — skipped (locked symbol, sell prohibited)",
                        symbol, weight * 100)
            continue

        auto_approve = weight >= _AUTO_REDUCE_THRESHOLD
        current_value = qty * (price or 0)
        target_value  = total_value * _TARGET_WEIGHT
        reduce_value  = max(0.0, current_value - target_value)
        reduce_pct    = min(reduce_value / current_value, 0.8) if current_value > 0 else 0.0

        proposal = ConcentrationProposal(
            symbol=symbol,
            current_weight=round(weight, 4),
            auto_approve=auto_approve,
            reduce_pct=round(reduce_pct, 3),
        )
        proposals.append(proposal)

        status = "approved" if auto_approve else "pending"
        proposal_id = str(uuid.uuid4())
        conn.execute(
            """INSERT OR IGNORE INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (proposal_id, "concentration_guard", "POSITION_REBALANCE", "portfolio",
             f"降低 {symbol} 持倉至 {_TARGET_WEIGHT*100:.0f}% 以下",
             f"{symbol} 目前佔組合 {weight:.1%}，超過警示門檻",
             0.9, int(not auto_approve), status,
             json.dumps({"symbol": symbol, "reduce_pct": reduce_pct,
                         "type": "rebalance", "auto": auto_approve}),
             int(time.time() * 1000))
        )
        conn.commit()
        log.info("Concentration %s: %.1f%% → %s proposal (reduce_pct=%.1f%%)",
                 symbol, weight * 100, status, reduce_pct * 100)

    return proposals
