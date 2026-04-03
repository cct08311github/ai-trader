"""debate_loop.py — Multi-Agent Debate Loop 主流程。

每日對 watchlist 中的標的執行三方辯論：
Bull -> Bear -> Arbiter -> Risk Check -> Shadow Decision

安全約束：
- 只寫 shadow_decisions，不下真實訂單
- Risk layer veto = skip，不拋例外
- .EMERGENCY_STOP 檢查（入口 + 每輪迭代）
- LLM timeout 30s，失敗回傳 confidence=0 / action=observe
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw.agents.base import open_conn, write_trace
from openclaw.agents.bull_agent import BullAgent, BullThesis
from openclaw.agents.bear_agent import BearAgent, BearThesis
from openclaw.agents.arbiter_agent import ArbiterAgent, ArbiterDecision
from openclaw.path_utils import get_repo_root

log = logging.getLogger("debate_loop")

_REPO_ROOT = get_repo_root()


def _sanitize_for_prompt(text: str, max_len: int = 500) -> str:
    """Strip control characters and truncate text to prevent prompt injection."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    return cleaned[:max_len]


@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""
    checks: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DebateRecord:
    debate_id: str
    debate_date: str
    symbol: str
    bull_thesis: BullThesis
    bear_thesis: BearThesis
    arbiter_decision: ArbiterDecision
    risk_check: RiskCheckResult
    recommendation: str
    confidence: float
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "debate_date": self.debate_date,
            "symbol": self.symbol,
            "bull_thesis": self.bull_thesis.to_dict(),
            "bear_thesis": self.bear_thesis.to_dict(),
            "arbiter_decision": self.arbiter_decision.to_dict(),
            "risk_check": self.risk_check.to_dict(),
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "elapsed_ms": self.elapsed_ms,
        }


def _check_emergency_stop() -> bool:
    """Check if .EMERGENCY_STOP file exists at repo root."""
    return (_REPO_ROOT / ".EMERGENCY_STOP").exists()


def _load_watchlist() -> List[str]:
    """Load watchlist from config/watchlist.json."""
    watchlist_path = _REPO_ROOT / "config" / "watchlist.json"
    try:
        with open(watchlist_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("manual_watchlist", []))
    except Exception as e:
        log.warning("[debate_loop] Failed to load watchlist: %s", e)
        return []


def _get_signals(conn: sqlite3.Connection, symbol: str) -> Dict[str, Any]:
    """Gather signal pack for a symbol from DB (EOD data + indicators)."""
    signals: Dict[str, Any] = {"symbol": symbol}

    try:
        # Recent EOD prices
        rows = conn.execute(
            """SELECT trade_date, open, high, low, close, volume, change
               FROM eod_prices
               WHERE symbol = ?
               ORDER BY trade_date DESC LIMIT 20""",
            (symbol,),
        ).fetchall()
        if rows:
            signals["recent_prices"] = [dict(r) for r in rows]
            closes = [r["close"] for r in reversed(rows) if r["close"]]
            if closes:
                signals["latest_close"] = closes[-1]
                signals["price_change_5d"] = (
                    round((closes[-1] - closes[-min(5, len(closes))]) / closes[-min(5, len(closes))] * 100, 2)
                    if len(closes) >= 2 else 0.0
                )
    except Exception as e:
        log.debug("[debate_loop] EOD fetch error for %s: %s", symbol, e)

    try:
        # Institution flows — columns match actual DB schema
        fi_rows = conn.execute(
            """SELECT trade_date, foreign_net, trust_net, dealer_net, total_net
               FROM eod_institution_flows
               WHERE symbol = ?
               ORDER BY trade_date DESC LIMIT 5""",
            (symbol,),
        ).fetchall()
        if fi_rows:
            signals["institution_flows"] = [dict(r) for r in fi_rows]
    except Exception as e:
        log.debug("[debate_loop] Institution flow fetch error for %s: %s", symbol, e)

    try:
        # RSI / MACD from technical_indicators (computed on the fly)
        from openclaw.technical_indicators import calc_rsi, calc_macd
        prices_rows = conn.execute(
            "SELECT close FROM eod_prices WHERE symbol = ? ORDER BY trade_date ASC LIMIT 60",
            (symbol,),
        ).fetchall()
        prices = [r[0] for r in prices_rows if r[0]]
        if len(prices) >= 15:
            rsi_vals = calc_rsi(prices)
            signals["rsi_14"] = rsi_vals[-1] if rsi_vals and rsi_vals[-1] is not None else None
        if len(prices) >= 27:
            macd_data = calc_macd(prices)
            signals["macd"] = macd_data["macd"][-1]
            signals["macd_signal"] = macd_data["signal"][-1]
            signals["macd_histogram"] = macd_data["histogram"][-1]
    except Exception as e:
        log.debug("[debate_loop] Technical indicator error for %s: %s", symbol, e)

    return signals


def validate_risk(decision: ArbiterDecision, conn: sqlite3.Connection) -> RiskCheckResult:
    """Basic risk validation. Returns RiskCheckResult.

    Safety: veto = skip, no exception raised.
    """
    checks: Dict[str, Any] = {}

    # 1. Confidence floor: reject if < 0.3
    if decision.confidence < 0.3 and decision.recommendation in ("BUY", "SELL"):
        checks["confidence_floor"] = False
        return RiskCheckResult(
            passed=False,
            reason=f"Confidence {decision.confidence:.2f} < 0.3 threshold for {decision.recommendation}",
            checks=checks,
        )
    checks["confidence_floor"] = True

    # 2. Check concentration (simplified: max 40% single position)
    try:
        total_row = conn.execute(
            "SELECT COALESCE(SUM(quantity * avg_price), 0) FROM positions WHERE quantity > 0"
        ).fetchone()
        symbol_row = conn.execute(
            "SELECT COALESCE(SUM(quantity * avg_price), 0) FROM positions WHERE symbol = ? AND quantity > 0",
            (decision.symbol,),
        ).fetchone()
        total_val = total_row[0] if total_row else 0
        symbol_val = symbol_row[0] if symbol_row else 0
        if total_val > 0 and symbol_val / total_val > 0.4 and decision.recommendation == "BUY":
            checks["concentration"] = False
            return RiskCheckResult(
                passed=False,
                reason=f"Concentration risk: {decision.symbol} already {symbol_val/total_val:.0%} of portfolio",
                checks=checks,
            )
        checks["concentration"] = True
    except Exception:
        checks["concentration"] = "skipped"

    return RiskCheckResult(passed=True, reason="all checks passed", checks=checks)


def _ensure_debate_records_table(conn: sqlite3.Connection) -> None:
    """Create debate_records table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS debate_records (
            id TEXT PRIMARY KEY,
            debate_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            bull_thesis_json TEXT,
            bear_thesis_json TEXT,
            arbiter_decision_json TEXT,
            risk_check_json TEXT,
            recommendation TEXT,
            confidence REAL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.commit()


def record_shadow_decision(record: DebateRecord, conn: sqlite3.Connection) -> None:
    """Write debate record to DB (shadow only, no real order)."""
    conn.execute(
        """INSERT OR REPLACE INTO debate_records
           (id, debate_date, symbol, bull_thesis_json, bear_thesis_json,
            arbiter_decision_json, risk_check_json, recommendation, confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.debate_id,
            record.debate_date,
            record.symbol,
            json.dumps(record.bull_thesis.to_dict(), ensure_ascii=False),
            json.dumps(record.bear_thesis.to_dict(), ensure_ascii=False),
            json.dumps(record.arbiter_decision.to_dict(), ensure_ascii=False),
            json.dumps(record.risk_check.to_dict(), ensure_ascii=False),
            record.recommendation,
            record.confidence,
            int(time.time() * 1000),
        ),
    )
    conn.commit()


def run_debate_loop(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
    watchlist: Optional[List[str]] = None,
    debate_date: Optional[str] = None,
) -> List[DebateRecord]:
    """Execute the full multi-agent debate loop for all watchlist symbols.

    Returns list of DebateRecord for downstream reporting.
    The returned list includes VETOED records (recommendation="VETOED") for
    audit trail purposes; only risk-passed records are persisted to DB.
    """
    from datetime import datetime, timezone, timedelta

    # Emergency stop check
    if _check_emergency_stop():
        log.warning("[debate_loop] EMERGENCY_STOP active — aborting debate loop")
        return []

    _tz_twn = timezone(timedelta(hours=8))
    _now = datetime.now(tz=_tz_twn)
    _debate_date = debate_date or _now.strftime("%Y-%m-%d")

    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    own_conn = conn is None

    try:
        _ensure_debate_records_table(_conn)

        _watchlist = watchlist or _load_watchlist()
        if not _watchlist:
            log.warning("[debate_loop] Empty watchlist — nothing to debate")
            return []

        bull_agent = BullAgent()
        bear_agent = BearAgent()
        arbiter = ArbiterAgent()

        debates: List[DebateRecord] = []

        for symbol in _watchlist:
            # Check EMERGENCY_STOP at each iteration
            if _check_emergency_stop():
                log.warning("EMERGENCY_STOP detected mid-loop, aborting")
                break

            t0 = time.time()
            debate_id = str(uuid.uuid4())

            try:
                # 1. Gather signals
                signals = _get_signals(_conn, symbol)

                # 2. Bull argues
                bull = bull_agent.argue(symbol, signals)
                write_trace(
                    _conn,
                    agent="debate_bull",
                    prompt=f"[Bull] {symbol}",
                    result={"summary": _sanitize_for_prompt(bull.thesis),
                            "confidence": bull.confidence,
                            "action_type": "observe", "_model": bull_agent.model},
                )

                # 3. Bear argues
                bear = bear_agent.argue(symbol, signals)
                write_trace(
                    _conn,
                    agent="debate_bear",
                    prompt=f"[Bear] {symbol}",
                    result={"summary": _sanitize_for_prompt(bear.thesis),
                            "confidence": bear.confidence,
                            "action_type": "observe", "_model": bear_agent.model},
                )

                # 4. Arbiter decides
                decision = arbiter.decide(bull, bear, signals)
                write_trace(
                    _conn,
                    agent="debate_arbiter",
                    prompt=f"[Arbiter] {symbol}",
                    result={"summary": _sanitize_for_prompt(decision.rationale),
                            "confidence": decision.confidence,
                            "action_type": "suggest", "_model": arbiter.model},
                )

                # 5. Risk validation
                risk_ok = validate_risk(decision, _conn)

                elapsed_ms = int((time.time() - t0) * 1000)

                record = DebateRecord(
                    debate_id=debate_id,
                    debate_date=_debate_date,
                    symbol=symbol,
                    bull_thesis=bull,
                    bear_thesis=bear,
                    arbiter_decision=decision,
                    risk_check=risk_ok,
                    recommendation=decision.recommendation if risk_ok.passed else "VETOED",
                    confidence=decision.confidence if risk_ok.passed else 0.0,
                    elapsed_ms=elapsed_ms,
                )

                # 6. Record shadow decision (only if risk passed)
                if risk_ok.passed:
                    record_shadow_decision(record, _conn)
                else:
                    log.info("[debate_loop] %s vetoed by risk: %s", symbol, risk_ok.reason)

                debates.append(record)

            except Exception as e:
                log.error("[debate_loop] Error debating %s: %s", symbol, e, exc_info=True)
                continue

        log.info("[debate_loop] Completed %d/%d debates", len(debates), len(_watchlist))
        return debates

    finally:
        if own_conn:
            _conn.close()
