"""concentration_guard.py — 集中度守衛

自動偵測單檔倉位過度集中，生成再平衡 proposal：
  - 超過 40%：自動核准 → approved（proposal_executor 下輪掃盤自動執行）
  - 超過 25%：待審 → pending（需人工核准）
  - 低於 25%：無動作

#385: 閾值從 60%/40% 降至 40%/25%，修復 dedup 阻擋減倉的問題

All SQL delegated to PositionRepository, OrderRepository, ProposalRepository.
"""
import json
import logging
import sqlite3
import time
import uuid
from typing import TypedDict

from openclaw.repositories.order_repository import OrderRepository
from openclaw.repositories.position_repository import PositionRepository
from openclaw.repositories.proposal_repository import ProposalRepository

log = logging.getLogger(__name__)

_AUTO_REDUCE_THRESHOLD: float = 0.40   # 超過 40%：自動核准減倉
_WARN_THRESHOLD:        float = 0.25   # 超過 25%：生成待審 proposal
_TARGET_WEIGHT:         float = 0.20   # 目標降至 20%（與 risk_engine max_symbol_weight 對齊）
_STALE_ORDER_SEC:       int   = 3600   # 超過 1 小時的賣單視為 stale（#483: was 360s）
_MAX_DAILY_SELL_ORDERS: int   = 3      # 同一 symbol 每日最多產生 3 筆 concentration sell（#483）


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
    pos_repo = PositionRepository(conn)
    order_repo = OrderRepository(conn)
    proposal_repo = ProposalRepository(conn)

    rows = conn.execute(
        "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
    ).fetchall()
    active_rows = [(r[0], r[1], r[2]) for r in rows]
    if not active_rows:
        return []

    total_value = sum(qty * (price or 0) for _, qty, price in active_rows)
    if total_value <= 0:
        return []

    # Dedup: check recent sell orders per symbol (submitted + filled)
    stale_cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                                 time.gmtime(time.time() - _STALE_ORDER_SEC))
    try:
        pending_sell_qty = order_repo.get_recent_sell_qty_by_symbol(stale_cutoff)
    except sqlite3.Error as e:
        log.error("Dedup query failed, proceeding WITHOUT dedup — "
                  "duplicate proposals may be generated: %s", e)
        pending_sell_qty = {}

    # #483: daily sell cap
    try:
        daily_sell_count = order_repo.count_daily_filled_sells()
    except sqlite3.Error as e:
        log.warning("Daily sell count query failed: %s", e)
        daily_sell_count = {}

    proposals: list[ConcentrationProposal] = []
    for symbol, qty, price in active_rows:
        weight = (qty * (price or 0)) / total_value
        if weight < _WARN_THRESHOLD:
            continue

        # Check if pending sell is sufficient to bring weight below target
        pending_qty = pending_sell_qty.get(symbol, 0)
        if pending_qty > 0:
            remaining_qty = qty - pending_qty
            remaining_weight = (remaining_qty * (price or 0)) / total_value if total_value > 0 else 0
            if remaining_weight <= _TARGET_WEIGHT:
                log.info("Concentration %s: %.1f%% — skipped (pending sell %d will reduce to %.1f%%)",
                         symbol, weight * 100, pending_qty, remaining_weight * 100)
                continue
            log.info("Concentration %s: %.1f%% — pending sell %d insufficient (would be %.1f%%), generating additional proposal",
                     symbol, weight * 100, pending_qty, remaining_weight * 100)

        # #483: daily cap
        sym_daily_sells = daily_sell_count.get(symbol, 0)
        if sym_daily_sells >= _MAX_DAILY_SELL_ORDERS:
            log.info("Concentration %s: %.1f%% — skipped (daily cap %d/%d reached)",
                     symbol, weight * 100, sym_daily_sells, _MAX_DAILY_SELL_ORDERS)
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
        proposal_repo.insert_proposal(
            proposal_id=str(uuid.uuid4()),
            generated_by="concentration_guard",
            target_rule="POSITION_REBALANCE",
            rule_category="portfolio",
            proposed_value=f"降低 {symbol} 持倉至 {_TARGET_WEIGHT*100:.0f}% 以下",
            supporting_evidence=f"{symbol} 目前佔組合 {weight:.1%}，超過警示門檻",
            confidence=0.9,
            requires_human_approval=not auto_approve,
            status=status,
            proposal_json=json.dumps({"symbol": symbol, "reduce_pct": reduce_pct,
                                      "type": "rebalance", "auto": auto_approve}),
        )
        conn.commit()
        log.info("Concentration %s: %.1f%% → %s proposal (reduce_pct=%.1f%%)",
                 symbol, weight * 100, status, reduce_pct * 100)

    return proposals
