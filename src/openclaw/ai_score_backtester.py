"""ai_score_backtester.py — AI Score Backtesting Engine (Module 2D).

Compare historical AI ratings from stock_research_reports with actual
returns from eod_prices. For each report compute return after 5, 10,
and 20 trading days, check target/stop-loss hits, and store results in
ai_score_backtest table (research.db).

Entry point: run_backtester()
Schedule: Sunday 22:00 TWN (in agent_orchestrator.py)
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_TZ_TWN = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_trades_db_path() -> str:
    """Resolve trades.db path (source of stock_research_reports + eod_prices)."""
    import os
    from openclaw.path_utils import get_repo_root
    return os.environ.get("DB_PATH", str(get_repo_root() / "data" / "sqlite" / "trades.db"))


def _get_research_db() -> sqlite3.Connection:
    """Open read-write connection to research.db and ensure schema."""
    from frontend.backend.app.db.research_db import (  # noqa: PLC0415
        RESEARCH_DB_PATH,
        connect_research,
        init_research_db,
    )
    init_research_db(RESEARCH_DB_PATH)
    return connect_research(RESEARCH_DB_PATH)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _fetch_pending_reports(
    trades_conn: sqlite3.Connection,
    research_conn: sqlite3.Connection,
) -> List[Dict]:
    """Return reports that have not yet been backtested.

    A report is "ready" if it was created more than 20 trading days ago
    (conservative: ≥ 28 calendar days) and is not yet in ai_score_backtest.
    """
    cutoff = (datetime.now(tz=_TZ_TWN) - timedelta(days=28)).strftime("%Y-%m-%d")
    already_done = {
        row[0] + "|" + row[1]
        for row in research_conn.execute(
            "SELECT symbol, report_date FROM ai_score_backtest"
        ).fetchall()
    }

    rows = trades_conn.execute(
        """
        SELECT symbol, trade_date, rating, entry_price, stop_loss, target_price
        FROM stock_research_reports
        WHERE trade_date <= ?
          AND rating IS NOT NULL
        ORDER BY trade_date DESC
        """,
        (cutoff,),
    ).fetchall()

    pending = []
    for row in rows:
        key = row[0] + "|" + row[1]
        if key not in already_done:
            pending.append({
                "symbol":       row[0],
                "report_date":  row[1],
                "rating":       row[2],
                "entry_price":  row[3],
                "stop_loss":    row[4],
                "target_price": row[5],
            })
    return pending


def _fetch_prices_after(
    trades_conn: sqlite3.Connection,
    symbol: str,
    report_date: str,
    n: int = 25,
) -> List[Tuple[str, float]]:
    """Return up to n closing prices after report_date, in chronological order."""
    rows = trades_conn.execute(
        """
        SELECT trade_date, close
        FROM eod_prices
        WHERE symbol = ? AND trade_date > ? AND close IS NOT NULL
        ORDER BY trade_date ASC
        LIMIT ?
        """,
        (symbol, report_date, n),
    ).fetchall()
    return [(r[0], float(r[1])) for r in rows]


def _compute_return(entry: float, close: float) -> float:
    """Simple return: (close - entry) / entry * 100 (percent)."""
    if entry is None or entry == 0:
        return 0.0
    return round((close - entry) / entry * 100, 4)


def _backtest_report(
    trades_conn: sqlite3.Connection,
    report: Dict,
) -> Optional[Dict]:
    """Compute backtest metrics for a single report.

    Returns None when there is insufficient price data.
    """
    symbol      = report["symbol"]
    report_date = report["report_date"]
    entry_price = report.get("entry_price")
    stop_loss   = report.get("stop_loss")
    target_price = report.get("target_price")

    prices = _fetch_prices_after(trades_conn, symbol, report_date, n=25)
    if len(prices) < 5:
        log.debug("[backtester] %s %s: only %d prices — skipping", symbol, report_date, len(prices))
        return None

    # If no entry_price, fall back to price on first available day (day 1 close)
    actual_entry = entry_price if (entry_price and entry_price > 0) else prices[0][1]

    def _price_at(n_days: int) -> Optional[float]:
        if len(prices) >= n_days:
            return prices[n_days - 1][1]
        return None

    p5  = _price_at(5)
    p10 = _price_at(10)
    p20 = _price_at(20)

    ret5  = _compute_return(actual_entry, p5)  if p5  else None
    ret10 = _compute_return(actual_entry, p10) if p10 else None
    ret20 = _compute_return(actual_entry, p20) if p20 else None

    # Check hit_target / hit_stoploss across entire observation window
    hit_target   = 0
    hit_stoploss = 0
    for _, close in prices[:20]:
        if target_price and close >= target_price:
            hit_target = 1
        if stop_loss and close <= stop_loss:
            hit_stoploss = 1

    # Derive confidence from llm_synthesis_json if available
    try:
        synth_row = trades_conn.execute(
            "SELECT llm_synthesis_json FROM stock_research_reports "
            "WHERE symbol=? AND trade_date=?",
            (symbol, report_date),
        ).fetchone()
        if synth_row and synth_row[0]:
            import json
            synth = json.loads(synth_row[0])
            confidence = float(synth.get("confidence", 0.0))
        else:
            confidence = 0.0
    except Exception:
        confidence = 0.0

    return {
        "symbol":       symbol,
        "report_date":  report_date,
        "rating":       report["rating"],
        "confidence":   confidence,
        "entry_price":  actual_entry,
        "return_5d":    ret5,
        "return_10d":   ret10,
        "return_20d":   ret20,
        "hit_target":   hit_target,
        "hit_stoploss": hit_stoploss,
        "created_at":   int(time.time()),
    }


def _upsert_backtest(research_conn: sqlite3.Connection, result: Dict) -> None:
    """Insert or replace a backtest row."""
    research_conn.execute(
        """
        INSERT OR REPLACE INTO ai_score_backtest
            (symbol, report_date, rating, confidence, entry_price,
             return_5d, return_10d, return_20d, hit_target, hit_stoploss, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result["symbol"],
            result["report_date"],
            result["rating"],
            result["confidence"],
            result["entry_price"],
            result["return_5d"],
            result["return_10d"],
            result["return_20d"],
            result["hit_target"],
            result["hit_stoploss"],
            result["created_at"],
        ),
    )
    research_conn.commit()


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

def compute_aggregate_stats(research_conn: sqlite3.Connection) -> Dict:
    """Compute win_rate and avg_return aggregated by rating + overall.

    win_rate = fraction of entries where return_20d > 0 (simple definition).
    """
    rows = research_conn.execute(
        """
        SELECT rating,
               COUNT(*) AS cnt,
               AVG(return_20d) AS avg_ret_20d,
               AVG(return_5d)  AS avg_ret_5d,
               AVG(return_10d) AS avg_ret_10d,
               SUM(CASE WHEN return_20d > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(hit_target)   AS total_hits_target,
               SUM(hit_stoploss) AS total_hits_stoploss
        FROM ai_score_backtest
        WHERE return_20d IS NOT NULL
        GROUP BY rating
        ORDER BY rating
        """
    ).fetchall()

    by_rating: Dict[str, Dict] = {}
    total_cnt = 0
    total_wins = 0
    total_ret_20d: List[float] = []

    for row in rows:
        rating   = row[0] or "?"
        cnt      = row[1]
        avg_ret  = round(row[2], 4) if row[2] is not None else None
        avg_ret5 = round(row[4], 4) if row[4] is not None else None
        avg_ret10 = round(row[3], 4) if row[3] is not None else None
        wins     = row[5] or 0
        win_rate = round(wins / cnt, 4) if cnt > 0 else 0.0

        by_rating[rating] = {
            "count":            cnt,
            "win_rate":         win_rate,
            "avg_return_5d":    avg_ret5,
            "avg_return_10d":   avg_ret10,
            "avg_return_20d":   avg_ret,
            "total_hit_target": row[6] or 0,
            "total_hit_stoploss": row[7] or 0,
        }
        total_cnt  += cnt
        total_wins += wins

    overall_win_rate = round(total_wins / total_cnt, 4) if total_cnt > 0 else 0.0

    # Overall avg return
    all_row = research_conn.execute(
        "SELECT AVG(return_20d) FROM ai_score_backtest WHERE return_20d IS NOT NULL"
    ).fetchone()
    overall_avg_ret = round(all_row[0], 4) if all_row and all_row[0] is not None else None

    return {
        "by_rating":        by_rating,
        "overall": {
            "total_count":    total_cnt,
            "win_rate":       overall_win_rate,
            "avg_return_20d": overall_avg_ret,
        },
        "computed_at": datetime.now(tz=_TZ_TWN).isoformat(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_backtester(trades_db_path: Optional[str] = None) -> Dict:
    """Run the AI score backtester.

    1. Fetch reports older than 28 calendar days that haven't been backtested.
    2. Compute 5/10/20d returns and target/stoploss hits.
    3. Write results to research.db.
    4. Return aggregate stats.

    Args:
        trades_db_path: Override path for trades.db (used in tests).

    Returns:
        Aggregate stats dict (by_rating + overall).
    """
    log.info("[ai_score_backtester] Starting backtester run …")

    if trades_db_path is None:
        trades_db_path = _get_trades_db_path()

    try:
        trades_conn = sqlite3.connect(trades_db_path, check_same_thread=False)
        trades_conn.row_factory = sqlite3.Row
    except Exception as e:
        log.error("[ai_score_backtester] Cannot open trades.db (%s): %s", trades_db_path, e)
        raise

    try:
        research_conn = _get_research_db()
    except Exception as e:
        log.error("[ai_score_backtester] Cannot open research.db: %s", e)
        trades_conn.close()
        raise

    try:
        pending = _fetch_pending_reports(trades_conn, research_conn)
        log.info("[ai_score_backtester] %d reports to backtest", len(pending))

        processed = 0
        skipped   = 0
        for report in pending:
            try:
                result = _backtest_report(trades_conn, report)
                if result is None:
                    skipped += 1
                    continue
                _upsert_backtest(research_conn, result)
                processed += 1
            except Exception as e:
                log.warning(
                    "[ai_score_backtester] Error processing %s/%s: %s",
                    report["symbol"], report["report_date"], e,
                )
                skipped += 1

        log.info(
            "[ai_score_backtester] Done: processed=%d skipped=%d",
            processed, skipped,
        )

        stats = compute_aggregate_stats(research_conn)
        log.info("[ai_score_backtester] Stats: %s", stats.get("overall"))
        return stats

    finally:
        trades_conn.close()
        research_conn.close()
