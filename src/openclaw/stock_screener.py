"""stock_screener.py — 系統選股引擎（rule-based + optional LLM refinement）

從 eod_prices / eod_institution_flows / eod_margin_data 掃描全市場，
產出 system_candidates 候選名單。

Tasks 1-6: schema, data loading, short/long term rules, orchestrator,
           LLM refinement, load helpers.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date as _date, timedelta as _timedelta
from typing import Dict, List, Optional, Set, Tuple

from openclaw.technical_indicators import (
    calc_ma,
    calc_macd,
    calc_rsi,
    find_support_resistance,
)

log = logging.getLogger(__name__)

MIN_SCORE_THRESHOLD: float = 0.4

# ── Task 1: Schema ──────────────────────────────────────────────────────────

_CREATE_SYSTEM_CANDIDATES = """\
CREATE TABLE IF NOT EXISTS system_candidates (
    symbol       TEXT    NOT NULL,
    trade_date   TEXT    NOT NULL,
    label        TEXT    NOT NULL,
    score        REAL    NOT NULL,
    source       TEXT    NOT NULL DEFAULT 'rule_screener',
    reasons      TEXT,
    llm_filtered INTEGER NOT NULL DEFAULT 0,
    expires_at   TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    PRIMARY KEY (symbol, trade_date, label)
)
"""


def ensure_screener_schema(conn: sqlite3.Connection) -> None:
    """Create system_candidates table if not exists."""
    conn.execute(_CREATE_SYSTEM_CANDIDATES)
    conn.commit()


# ── Task 2: Data loading helpers ─────────────────────────────────────────────


def _load_market_symbols(
    conn: sqlite3.Connection,
    trade_date: str,
    *,
    exclude: Set[str],
) -> List[str]:
    """Load symbols from eod_prices where volume >= 500, excluding *exclude* set."""
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM eod_prices "
        "WHERE trade_date = ? AND volume >= 500",
        (trade_date,),
    ).fetchall()
    return [r[0] for r in rows if r[0] not in exclude]


def _get_closes(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
    limit: int = 60,
) -> List[float]:
    """Return up to *limit* closing prices ending at *trade_date* (chronological)."""
    rows = conn.execute(
        "SELECT close FROM eod_prices "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (symbol, trade_date, limit),
    ).fetchall()
    return [r[0] for r in reversed(rows)]


def _get_volumes(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
    limit: int = 10,
) -> List[int]:
    """Return up to *limit* volumes ending at *trade_date* (chronological)."""
    rows = conn.execute(
        "SELECT volume FROM eod_prices "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (symbol, trade_date, limit),
    ).fetchall()
    return [int(r[0]) for r in reversed(rows)]


def _get_highs_lows(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
    limit: int = 60,
) -> Tuple[List[float], List[float], List[float]]:
    """Return (highs, lows, closes) up to *limit* rows (chronological)."""
    rows = conn.execute(
        "SELECT high, low, close FROM eod_prices "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT ?",
        (symbol, trade_date, limit),
    ).fetchall()
    rows = list(reversed(rows))
    highs = [r[0] for r in rows]
    lows = [r[1] for r in rows]
    closes = [r[2] for r in rows]
    return highs, lows, closes


# ── Task 3: Short-term rules ────────────────────────────────────────────────


def _check_short_term_rules(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> Tuple[float, List[str]]:
    """Evaluate short-term screening rules. Returns (score, reasons)."""
    score = 0.0
    reasons: List[str] = []

    closes = _get_closes(conn, symbol, trade_date, limit=60)
    if len(closes) < 5:
        return 0.0, []

    volumes = _get_volumes(conn, symbol, trade_date, limit=10)

    # Rule 1: Volume surge — today >= 1.5x of 5-day avg
    if len(volumes) >= 6:
        avg5 = sum(volumes[-6:-1]) / 5
        if avg5 > 0 and volumes[-1] >= 1.5 * avg5:
            ratio = volumes[-1] / avg5
            score += 0.25
            reasons.append(f"量能爆發({ratio:.1f}x)")

    # Rule 2: Institution buying — foreign_net + trust_net > 0 for >= 2 consecutive days
    inst_rows = conn.execute(
        "SELECT foreign_net, trust_net FROM eod_institution_flows "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT 10",
        (symbol, trade_date),
    ).fetchall()
    if inst_rows:
        consecutive = 0
        for r in inst_rows:
            if (r[0] or 0) + (r[1] or 0) > 0:
                consecutive += 1
            else:
                break
        if consecutive >= 2:
            score += 0.25
            reasons.append(f"法人連{consecutive}買")

    # Rule 3: MA golden cross — MA5 crosses above MA20
    if len(closes) >= 21:
        ma5 = calc_ma(closes, 5)
        ma20 = calc_ma(closes, 20)
        if (
            ma5[-1] is not None
            and ma5[-2] is not None
            and ma20[-1] is not None
            and ma20[-2] is not None
            and ma5[-1] > ma20[-1]
            and ma5[-2] <= ma20[-2]
        ):
            score += 0.25
            reasons.append("MA5上穿MA20")

    # Rule 4: RSI rebound — was < 30, now 30~50
    if len(closes) >= 16:
        rsi_vals = calc_rsi(closes, 14)
        # Find valid RSI values at end
        valid = [v for v in rsi_vals if v is not None]
        if len(valid) >= 2:
            prev_rsi = valid[-2]
            curr_rsi = valid[-1]
            if prev_rsi < 30 and 30 <= curr_rsi <= 50:
                score += 0.15
                reasons.append(f"RSI回升({curr_rsi:.0f})")

    # Rule 5: Price breaks resistance
    highs, lows, closes_hl = _get_highs_lows(conn, symbol, trade_date, limit=60)
    if len(highs) >= 5:
        sr = find_support_resistance(highs[:-1], lows[:-1], closes_hl[:-1])
        if sr["resistance"] > 0 and closes[-1] > sr["resistance"]:
            score += 0.10
            reasons.append("突破壓力位")

    return round(score, 2), reasons


# ── Task 3: Long-term rules ─────────────────────────────────────────────────


def _check_long_term_rules(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> Tuple[float, List[str]]:
    """Evaluate long-term screening rules. Returns (score, reasons)."""
    score = 0.0
    reasons: List[str] = []

    closes = _get_closes(conn, symbol, trade_date, limit=80)
    if len(closes) < 5:
        return 0.0, []

    # Rule 1: Steady institution — foreign_net > 0 for >= 5 consecutive days
    inst_rows = conn.execute(
        "SELECT foreign_net FROM eod_institution_flows "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT 20",
        (symbol, trade_date),
    ).fetchall()
    if inst_rows:
        consecutive = 0
        for r in inst_rows:
            if (r[0] or 0) > 0:
                consecutive += 1
            else:
                break
        if consecutive >= 5:
            score += 0.30
            reasons.append(f"法人穩定佈局(連{consecutive}日)")

    # Rule 2: Margin decrease — margin_balance decreasing >= 3 consecutive days
    margin_rows = conn.execute(
        "SELECT margin_balance FROM eod_margin_data "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT 10",
        (symbol, trade_date),
    ).fetchall()
    if len(margin_rows) >= 3:
        # DESC order: newer first. Decreasing means each newer < older.
        consecutive = 0
        for i in range(len(margin_rows) - 1):
            newer = margin_rows[i][0] or 0
            older = margin_rows[i + 1][0] or 0
            if newer < older:
                consecutive += 1
            else:
                break
        if consecutive >= 2:  # 3 data points → 2 decreasing steps = 3 consecutive days
            score += 0.20
            reasons.append(f"融資減少(連{consecutive + 1}日)")

    # Rule 3: MA bullish alignment — MA5 > MA20 > MA60
    if len(closes) >= 60:
        ma5 = calc_ma(closes, 5)
        ma20 = calc_ma(closes, 20)
        ma60 = calc_ma(closes, 60)
        if (
            ma5[-1] is not None
            and ma20[-1] is not None
            and ma60[-1] is not None
            and ma5[-1] > ma20[-1] > ma60[-1]
        ):
            score += 0.25
            reasons.append("多頭排列(MA5>MA20>MA60)")

    # Rule 4: MACD histogram turns positive — hist[-2] < 0 and hist[-1] >= 0
    if len(closes) >= 26:
        macd = calc_macd(closes)
        hist = macd["histogram"]
        valid_hist = [v for v in hist if v is not None]
        if len(valid_hist) >= 2:
            if valid_hist[-2] < 0 and valid_hist[-1] >= 0:
                score += 0.15
                reasons.append("MACD翻正")

    # Rule 5: Price above support
    highs, lows, closes_hl = _get_highs_lows(conn, symbol, trade_date, limit=60)
    if len(highs) >= 5:
        sr = find_support_resistance(highs, lows, closes_hl)
        if sr["support"] > 0 and closes[-1] > sr["support"]:
            score += 0.10
            reasons.append("站穩支撐位")

    return round(score, 2), reasons


# ── Task 5: LLM refinement ─────────────────────────────────────────────────


def _llm_refine_candidates(
    conn: sqlite3.Connection,
    trade_date: str,
    candidates: List[Dict],
) -> List[Dict]:
    """Use Gemini to review rule-based candidates and filter/adjust scores."""
    from openclaw.agents.base import call_agent_llm, DEFAULT_MODEL, write_trace

    summary = json.dumps(
        [
            {
                "symbol": c["symbol"],
                "label": c["label"],
                "score": c["score"],
                "reasons": c["reasons"],
            }
            for c in candidates
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = (
        f"你是 AI Trader 選股篩選器。以下是 {trade_date} 規則引擎篩出的候選股票：\n\n"
        f"{summary}\n\n"
        "請審查每支候選股，移除明顯不適合的（如近期有重大利空、被處置、流動性不足等）。\n"
        "對剩餘候選微調分數（0.0~1.0），並補充理由。\n\n"
        "輸出 JSON 陣列（僅保留通過審查的）：\n"
        '[{"symbol": "2330", "label": "short_term", "score": 0.8, "reasons": ["..."]}, ...]'
    )
    result = call_agent_llm(prompt, model=DEFAULT_MODEL)
    write_trace(conn, agent="screener_llm", prompt=prompt[:500], result=result)

    # Parse — expect list or dict with "candidates" key
    refined: List[Dict] = []
    if isinstance(result, list):
        refined = result
    elif isinstance(result, dict) and "candidates" in result:
        refined = result["candidates"]
    else:
        log.warning("[SCREENER] LLM returned unexpected format, keeping rule results")
        return candidates

    # Validate
    valid: List[Dict] = []
    for item in refined:
        if isinstance(item, dict) and "symbol" in item and "label" in item:
            valid.append(
                {
                    "symbol": item["symbol"],
                    "label": item.get("label", "short_term"),
                    "score": float(item.get("score", 0.5)),
                    "reasons": item.get("reasons", []),
                }
            )
    return valid if valid else candidates


# ── Task 4: Orchestrator ────────────────────────────────────────────────────


def screen_candidates(
    conn: sqlite3.Connection,
    trade_date: str,
    *,
    manual_watchlist: Set[str],
    max_candidates: int = 10,
    llm_refine: bool = True,
) -> List[Dict]:
    """Main entry point: screen the market and return qualified candidates.

    Returns list of dicts with keys:
        symbol, label, score, reasons, llm_filtered, trade_date, expires_at
    """
    ensure_screener_schema(conn)

    symbols = _load_market_symbols(conn, trade_date, exclude=manual_watchlist)
    if not symbols:
        log.info("screen_candidates: no symbols found for %s", trade_date)
        return []

    short_term: List[Dict] = []
    long_term: List[Dict] = []

    for sym in symbols:
        st_score, st_reasons = _check_short_term_rules(conn, sym, trade_date)
        if st_score >= MIN_SCORE_THRESHOLD:
            short_term.append({
                "symbol": sym,
                "label": "short_term",
                "score": st_score,
                "reasons": st_reasons,
            })

        lt_score, lt_reasons = _check_long_term_rules(conn, sym, trade_date)
        if lt_score >= MIN_SCORE_THRESHOLD:
            long_term.append({
                "symbol": sym,
                "label": "long_term",
                "score": lt_score,
                "reasons": lt_reasons,
            })

    # Sort by score desc, cap each label
    half = max(1, max_candidates // 2)
    short_term.sort(key=lambda x: x["score"], reverse=True)
    long_term.sort(key=lambda x: x["score"], reverse=True)
    short_term = short_term[:half]
    long_term = long_term[:half]

    candidates = short_term + long_term

    if not candidates:
        return []

    # LLM refinement
    llm_filtered = 0
    if llm_refine:
        try:
            candidates = _llm_refine_candidates(conn, trade_date, candidates)
            llm_filtered = 1
        except (NotImplementedError, Exception) as exc:
            log.warning("LLM refinement failed, fallback: %s", exc)
            llm_filtered = 0

    # Compute expiry and enrich
    td = _date.fromisoformat(trade_date)
    now_ms = int(time.time() * 1000)
    results: List[Dict] = []

    for c in candidates:
        label = c["label"]
        expires_delta = _timedelta(days=3) if label == "short_term" else _timedelta(days=5)
        expires_at = (td + expires_delta).isoformat()

        record = {
            "symbol": c["symbol"],
            "label": label,
            "score": c["score"],
            "reasons": c["reasons"],
            "llm_filtered": llm_filtered,
            "trade_date": trade_date,
            "expires_at": expires_at,
        }
        results.append(record)

        # Write to DB
        conn.execute(
            "INSERT OR REPLACE INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, ?, ?, ?)",
            (
                c["symbol"],
                trade_date,
                label,
                c["score"],
                json.dumps(c["reasons"], ensure_ascii=False),
                llm_filtered,
                expires_at,
                now_ms,
            ),
        )

    conn.commit()
    log.info(
        "screen_candidates: %d candidates (%d short, %d long) for %s",
        len(results),
        sum(1 for r in results if r["label"] == "short_term"),
        sum(1 for r in results if r["label"] == "long_term"),
        trade_date,
    )
    return results


# ── Task 6: Load helpers ──────────────────────────────────────────────────


def load_system_candidates(conn: sqlite3.Connection) -> List[str]:
    """Load unexpired system candidate symbols for ticker_watcher merge."""
    ensure_screener_schema(conn)
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM system_candidates WHERE expires_at >= date('now')"
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["symbol"] for r in rows]


def load_system_candidates_full(conn: sqlite3.Connection) -> List[Dict]:
    """Load full candidate details for API response."""
    ensure_screener_schema(conn)
    rows = conn.execute(
        "SELECT symbol, trade_date, label, score, reasons, llm_filtered, expires_at "
        "FROM system_candidates WHERE expires_at >= date('now') ORDER BY score DESC"
    ).fetchall()
    result: List[Dict] = []
    for r in rows:
        if isinstance(r, tuple):
            sym, td, label, score, reasons_json, llm_f, exp = r
        else:
            sym, td, label, score, reasons_json, llm_f, exp = (
                r["symbol"],
                r["trade_date"],
                r["label"],
                r["score"],
                r["reasons"],
                r["llm_filtered"],
                r["expires_at"],
            )
        result.append(
            {
                "symbol": sym,
                "trade_date": td,
                "label": label,
                "score": score,
                "reasons": json.loads(reasons_json) if reasons_json else [],
                "llm_filtered": bool(llm_f),
                "expires_at": exp,
            }
        )
    return result
