"""shadow_approval_logger.py — Strategy auto-approval logic + shadow logger.

Implements asymmetric confidence thresholds for auto-approval decisions.
Shadow logging records all decisions to shadow_decisions table for
ongoing calibration (T+5/T+20 tracking).

Usage in strategy_committee.py:
    from openclaw.shadow_approval_logger import (
        SHADOW_MODE, log_shadow_decision, shadow_mode_report,
        _should_require_human_new_logic,
    )

    shadow_would_approve = _should_require_human_new_logic(...) == 0
    requires_human_approval = 0 if shadow_would_approve else 1

Rollback:
    STRATEGY_SHADOW_MODE=false  → disable shadow, new logic always requires human (emergency only)
    Default: true (shadow mode ON — observe for 2 weeks before going live per Phase 0 spec)
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

SHADOW_MODE: bool = os.environ.get("STRATEGY_SHADOW_MODE", "true").lower() == "true"

# Asymmetric confidence floors — new logic (Phase 1 values, env-overridable)
_AUTO_APPROVE_BUY_FLOOR: float = float(
    os.environ.get("STRATEGY_AUTO_APPROVE_BUY_CONFIDENCE", "0.65")
)
_AUTO_APPROVE_SELL_FLOOR: float = float(
    os.environ.get("STRATEGY_AUTO_APPROVE_SELL_CONFIDENCE", "0.50")
)


# --------------------------------------------------------------------------- #
# New approval logic (no side-effects — pure function)
# --------------------------------------------------------------------------- #

_BUY_KEYWORDS = frozenset({"buy", "increase", "offensive", "bullish", "加碼", "買入", "多頭"})
_SELL_KEYWORDS = frozenset({"sell", "reduce", "defensive", "bearish", "decrease", "減少", "減碼", "賣出", "空頭"})


def _should_require_human_new_logic(
    arbiter_result: dict,
    confidence: float,
    direction: str = "",
) -> int:
    """New auto-approval logic with asymmetric confidence thresholds.

    Design philosophy: auto-approve only when direction is clear.
    1. Unknown/neutral direction → always require human
    2. Buy direction with confidence < BUY_FLOOR (0.65) → require human
    3. Sell direction with confidence < SELL_FLOOR (0.50) → require human
    4. Arbiter strongly against + buy direction → require human

    LEVEL3 categories are blocked independently by proposal_engine.
    """
    d_lower = direction.lower()
    is_buy = any(kw in d_lower for kw in _BUY_KEYWORDS)
    is_sell = any(kw in d_lower for kw in _SELL_KEYWORDS)

    # Unknown/neutral direction → always require human review
    if not is_buy and not is_sell:
        return 1

    floor = _AUTO_APPROVE_BUY_FLOOR if is_buy else _AUTO_APPROVE_SELL_FLOOR

    if confidence < floor:
        return 1

    stance = arbiter_result.get("stance", "").lower()
    if stance in ("reject", "strong_bearish") and is_buy:
        return 1

    return 0


# --------------------------------------------------------------------------- #
# DB schema
# --------------------------------------------------------------------------- #

_CREATE_SHADOW_TABLE = """
CREATE TABLE IF NOT EXISTS shadow_decisions (
    proposal_id          TEXT PRIMARY KEY,
    symbol               TEXT NOT NULL DEFAULT '',
    direction            TEXT NOT NULL DEFAULT '',
    confidence           REAL,
    would_approve        INTEGER NOT NULL,   -- 1 = new logic auto-approves
    current_requires_human INTEGER NOT NULL, -- 1 = old logic requires human
    logged_at            INTEGER NOT NULL,   -- ms epoch
    price_at_log         REAL,               -- filled by EOD backfill
    price_t5             REAL,               -- T+5 close (EOD backfill)
    price_t20            REAL,               -- T+20 close (EOD backfill)
    pnl_t5               REAL,
    pnl_t20              REAL
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_SHADOW_TABLE)
    conn.commit()


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def log_shadow_decision(
    conn: sqlite3.Connection,
    proposal_id: str,
    symbol: str,
    direction: str,
    confidence: float,
    would_approve: bool,
    current_requires_human: int,
) -> None:
    """Record what the new logic would decide — no execution side-effect."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        _ensure_table(conn)
        conn.execute(
            """INSERT OR REPLACE INTO shadow_decisions
               (proposal_id, symbol, direction, confidence,
                would_approve, current_requires_human, logged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal_id,
                symbol or "",
                direction or "",
                confidence,
                1 if would_approve else 0,
                current_requires_human,
                now_ms,
            ),
        )
        conn.commit()
        log.debug(
            "[shadow] %s symbol=%s dir=%s conf=%.2f would_approve=%s current_human=%s",
            proposal_id[:8],
            symbol,
            direction,
            confidence,
            would_approve,
            current_requires_human,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("[shadow] log_shadow_decision failed: %s", exc)


# --------------------------------------------------------------------------- #
# EOD backfill — call from eod_ingest at end of day
# --------------------------------------------------------------------------- #

def backfill_shadow_decisions_eod(conn: sqlite3.Connection) -> int:
    """Backfill T+5 and T+20 prices for matured shadow decisions.

    Only fills rows where price data is missing and enough time has passed.
    Returns number of rows updated.
    """
    _ensure_table(conn)
    count = 0

    # T+5 backfill: logged > 5 trading days ago, no price_t5 yet
    t5_cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 5 * 86_400_000
    rows_t5 = conn.execute(
        """SELECT sd.proposal_id, sd.symbol, sd.logged_at
           FROM shadow_decisions sd
           WHERE sd.price_t5 IS NULL
             AND sd.logged_at < ?
             AND sd.symbol != ''
           LIMIT 100""",
        (t5_cutoff_ms,),
    ).fetchall()

    for proposal_id, symbol, logged_at_ms in rows_t5:
        log_date = datetime.fromtimestamp(logged_at_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        # Get the closest eod_prices close at/after log_date + 5 days
        row = conn.execute(
            """SELECT close FROM eod_prices
               WHERE symbol = ?
                 AND trade_date >= date(?, '+5 days')
               ORDER BY trade_date ASC LIMIT 1""",
            (symbol, log_date),
        ).fetchone()
        if row and row[0]:
            price_t5 = float(row[0])
            # get entry price (price at log)
            entry_row = conn.execute(
                """SELECT close FROM eod_prices
                   WHERE symbol = ? AND trade_date <= ?
                   ORDER BY trade_date DESC LIMIT 1""",
                (symbol, log_date),
            ).fetchone()
            price_at_log = float(entry_row[0]) if entry_row and entry_row[0] else None
            pnl_t5 = (
                (price_t5 - price_at_log) / price_at_log
                if price_at_log and price_at_log > 0
                else None
            )
            conn.execute(
                """UPDATE shadow_decisions
                   SET price_at_log = ?, price_t5 = ?, pnl_t5 = ?
                   WHERE proposal_id = ?""",
                (price_at_log, price_t5, pnl_t5, proposal_id),
            )
            count += 1

    # T+20 backfill: has T+5, missing T+20, logged > 20 days ago
    t20_cutoff_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 20 * 86_400_000
    rows_t20 = conn.execute(
        """SELECT sd.proposal_id, sd.symbol, sd.logged_at, sd.price_at_log
           FROM shadow_decisions sd
           WHERE sd.price_t5 IS NOT NULL
             AND sd.price_t20 IS NULL
             AND sd.logged_at < ?
             AND sd.symbol != ''
           LIMIT 100""",
        (t20_cutoff_ms,),
    ).fetchall()

    for proposal_id, symbol, logged_at_ms, price_at_log in rows_t20:
        log_date = datetime.fromtimestamp(logged_at_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        row = conn.execute(
            """SELECT close FROM eod_prices
               WHERE symbol = ?
                 AND trade_date >= date(?, '+20 days')
               ORDER BY trade_date ASC LIMIT 1""",
            (symbol, log_date),
        ).fetchone()
        if row and row[0]:
            price_t20 = float(row[0])
            pnl_t20 = (
                (price_t20 - price_at_log) / price_at_log
                if price_at_log and price_at_log > 0
                else None
            )
            conn.execute(
                """UPDATE shadow_decisions
                   SET price_t20 = ?, pnl_t20 = ?
                   WHERE proposal_id = ?""",
                (price_t20, pnl_t20, proposal_id),
            )
            count += 1

    if count:
        conn.commit()

    return count


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def shadow_mode_report(conn: sqlite3.Connection) -> dict:
    """Compute win-rate summary for the new logic's would-approve decisions.

    Returns a dict with:
    - total: total logged shadow decisions
    - would_approve_count: cases where new logic wanted to auto-approve
    - by_direction: breakdown by direction
    - t5_win_rate: T+5 win rate for would-approve cases (None if insufficient data)
    - t20_win_rate: T+20 win rate for would-approve cases (None if insufficient data)
    - ready_to_go_live: True if t5_win_rate >= 0.55 and t20_avg_pnl >= 0.0
    """
    _ensure_table(conn)

    total_row = conn.execute(
        "SELECT COUNT(*) FROM shadow_decisions"
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    approve_row = conn.execute(
        "SELECT COUNT(*) FROM shadow_decisions WHERE would_approve = 1"
    ).fetchone()
    would_approve_count = int(approve_row[0]) if approve_row else 0

    # T+5 win rate for would-approve decisions
    t5_rows = conn.execute(
        """SELECT COUNT(*) as cnt,
                  SUM(CASE WHEN pnl_t5 > 0 THEN 1 ELSE 0 END) as wins,
                  AVG(pnl_t5) as avg_pnl
           FROM shadow_decisions
           WHERE would_approve = 1
             AND pnl_t5 IS NOT NULL"""
    ).fetchone()
    t5_win_rate = None
    t5_avg_pnl = None
    if t5_rows and t5_rows[0] and t5_rows[0] >= 5:
        t5_win_rate = round(float(t5_rows[1] or 0) / float(t5_rows[0]), 3)
        t5_avg_pnl = round(float(t5_rows[2] or 0), 4)

    # T+20 win rate
    t20_rows = conn.execute(
        """SELECT COUNT(*) as cnt,
                  SUM(CASE WHEN pnl_t20 > 0 THEN 1 ELSE 0 END) as wins,
                  AVG(pnl_t20) as avg_pnl
           FROM shadow_decisions
           WHERE would_approve = 1
             AND pnl_t20 IS NOT NULL"""
    ).fetchone()
    t20_win_rate = None
    t20_avg_pnl = None
    if t20_rows and t20_rows[0] and t20_rows[0] >= 5:
        t20_win_rate = round(float(t20_rows[1] or 0) / float(t20_rows[0]), 3)
        t20_avg_pnl = round(float(t20_rows[2] or 0), 4)

    # Breakdown by direction
    dir_rows = conn.execute(
        """SELECT direction,
                  COUNT(*) as cnt,
                  SUM(would_approve) as approves,
                  AVG(CASE WHEN would_approve=1 THEN pnl_t5 END) as avg_pnl_t5
           FROM shadow_decisions
           GROUP BY direction"""
    ).fetchall()
    by_direction = [
        {
            "direction": r[0],
            "total": r[1],
            "would_approve": r[2],
            "avg_pnl_t5": round(float(r[3]), 4) if r[3] is not None else None,
        }
        for r in dir_rows
    ]

    ready = bool(
        t5_win_rate is not None
        and t5_win_rate >= 0.55
        and t20_avg_pnl is not None
        and t20_avg_pnl >= 0.0
    )

    return {
        "total": total,
        "would_approve_count": would_approve_count,
        "t5_win_rate": t5_win_rate,
        "t5_avg_pnl": t5_avg_pnl,
        "t20_win_rate": t20_win_rate,
        "t20_avg_pnl": t20_avg_pnl,
        "by_direction": by_direction,
        "ready_to_go_live": ready,
        "recommendation": (
            "新邏輯表現穩定，持續運行"
            if ready
            else f"注意校準（T+5 勝率 {t5_win_rate or 'N/A'}，建議 ≥ 0.55）"
        ),
    }
