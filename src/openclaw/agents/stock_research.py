"""agents/stock_research.py — 個股深度研究 Agent。

執行時機：每交易日 18:00 TWN（market_data_fetcher 之後、eod_analysis 之前）
工作：watchlist 個股 → 技術面 + 籌碼面 → LLM 綜合評估 → stock_research_reports
安全：每日最多 10 檔（LLM 成本控制），A 級建議仍需人工核准
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_VALID_RATINGS = {"A", "B", "C", "D"}


def _sanitize_for_prompt(text: str, max_len: int = 200) -> str:
    """Strip control characters and truncate DB-sourced text for LLM prompts.

    Prevents prompt injection from untrusted DB data fed into LLM prompts.
    """
    if not isinstance(text, str):
        text = str(text)
    # Remove control characters (except common whitespace)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    return text[:max_len]

from openclaw.agents.base import (
    AgentResult,
    DEFAULT_MODEL,
    call_agent_llm,
    open_conn,
    query_db,
    write_proposal,
    write_trace,
)
from openclaw.path_utils import get_repo_root
from openclaw.technical_indicators import (
    calc_ma,
    calc_macd,
    calc_rsi,
    find_support_resistance,
)

_REPO_ROOT = get_repo_root()
_MAX_STOCKS_PER_DAY = 10
_TZ_TWN = timezone(timedelta(hours=8))


# ── Schema ─────────────────────────────────────────────────────────────────────

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS stock_research_reports (
    report_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    technical_json TEXT,
    institutional_json TEXT,
    llm_synthesis_json TEXT,
    rating TEXT,
    entry_price REAL,
    stop_loss REAL,
    target_price REAL,
    report_markdown TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(symbol, trade_date)
)
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TABLE)
    conn.commit()


# ── Layer 1: Technical Analysis ────────────────────────────────────────────────


def layer1_technical(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> Dict:
    """MA / RSI / MACD / trend / volume ratio analysis."""
    rows = query_db(
        conn,
        "SELECT close, high, low, volume FROM eod_prices "
        "WHERE symbol=? AND trade_date<=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT 60",
        (symbol, trade_date),
    )
    if not rows:
        return {"symbol": symbol, "error": "no_data"}

    rows = list(reversed(rows))
    closes = [r["close"] for r in rows]
    highs = [r["high"] or r["close"] for r in rows]
    lows = [r["low"] or r["close"] for r in rows]
    volumes = [r["volume"] or 0 for r in rows]

    def _last(lst):
        for v in reversed(lst):
            if v is not None:
                return round(v, 2)
        return None

    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    rsi = calc_rsi(closes, 14)
    macd_result = calc_macd(closes)
    sr = find_support_resistance(highs, lows, closes)

    # Trend detection
    trend = "neutral"
    if _last(ma5) and _last(ma20):
        if _last(ma5) > _last(ma20):
            trend = "bullish"
        elif _last(ma5) < _last(ma20):
            trend = "bearish"
        if _last(ma60) and _last(ma5) > _last(ma20) > _last(ma60):
            trend = "strong_bullish"
        elif _last(ma60) and _last(ma5) < _last(ma20) < _last(ma60):
            trend = "strong_bearish"

    # Volume ratio (today vs 5-day avg)
    volume_ratio = None
    if len(volumes) >= 6:
        avg5 = sum(volumes[-6:-1]) / 5
        if avg5 > 0:
            volume_ratio = round(volumes[-1] / avg5, 2)

    return {
        "symbol": symbol,
        "close": closes[-1],
        "ma5": _last(ma5),
        "ma20": _last(ma20),
        "ma60": _last(ma60),
        "rsi14": _last(rsi),
        "macd": {
            "macd": _last(macd_result["macd"]),
            "signal": _last(macd_result["signal"]),
            "histogram": _last(macd_result["histogram"]),
        },
        "support": sr["support"],
        "resistance": sr["resistance"],
        "trend": trend,
        "volume_ratio": volume_ratio,
    }


# ── Layer 2: Institutional Analysis ───────────────────────────────────────────


def layer2_institutional(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> Dict:
    """Foreign / trust / dealer flows + margin data analysis."""
    # Institution flows (recent 10 days)
    inst_rows = query_db(
        conn,
        "SELECT trade_date, foreign_net, trust_net, dealer_net, total_net "
        "FROM eod_institution_flows "
        "WHERE symbol=? AND trade_date<=? "
        "ORDER BY trade_date DESC LIMIT 10",
        (symbol, trade_date),
    )

    # Margin data (recent 10 days)
    margin_rows = query_db(
        conn,
        "SELECT trade_date, margin_balance, short_balance "
        "FROM eod_margin_data "
        "WHERE symbol=? AND trade_date<=? "
        "ORDER BY trade_date DESC LIMIT 10",
        (symbol, trade_date),
    )

    # Compute consecutive buying days
    foreign_consecutive = 0
    trust_consecutive = 0
    for r in inst_rows:
        if (r.get("foreign_net") or 0) > 0:
            foreign_consecutive += 1
        else:
            break

    for r in inst_rows:
        if (r.get("trust_net") or 0) > 0:
            trust_consecutive += 1
        else:
            break

    # Recent total net
    recent_total = sum((r.get("total_net") or 0) for r in inst_rows[:5])

    # Margin trend
    margin_trend = "unknown"
    if len(margin_rows) >= 3:
        balances = [r.get("margin_balance") or 0 for r in margin_rows[:3]]
        if balances[0] < balances[1] < balances[2]:
            margin_trend = "decreasing"
        elif balances[0] > balances[1] > balances[2]:
            margin_trend = "increasing"
        else:
            margin_trend = "flat"

    return {
        "symbol": symbol,
        "institution_flows": inst_rows[:5],
        "foreign_consecutive_buy": foreign_consecutive,
        "trust_consecutive_buy": trust_consecutive,
        "recent_5d_total_net": recent_total,
        "margin_data": margin_rows[:5],
        "margin_trend": margin_trend,
    }


# ── Layer 3: LLM Synthesis ────────────────────────────────────────────────────

_LLM_PROMPT = """\
你是 AI Trader 系統的個股研究分析師。請根據以下數據對 {symbol} 進行綜合評估。

## 技術面分析
<data>
{technical_json}
</data>

## 籌碼面分析
<data>
{institutional_json}
</data>

## 評估要求
1. 綜合技術面與籌碼面，給出評級：
   - A: 強烈看好，建議建倉
   - B: 看好，可考慮建倉
   - C: 中性，持續觀察
   - D: 看空或風險過高
2. 若評級 A 或 B，提供建議進場價、停損價、目標價
3. 提供 1-3 句簡要理由

## 輸出格式（必須是 JSON）
```json
{{
  "rating": "B",
  "entry_price": 580.0,
  "stop_loss": 555.0,
  "target_price": 630.0,
  "confidence": 0.72,
  "rationale": "技術面多頭排列 + 外資連買 3 日，建議回測 MA20 時進場",
  "risk_notes": ["注意半導體族群系統性風險"]
}}
```
"""


def layer3_llm_synthesis(
    technical: Dict,
    institutional: Dict,
    symbol: str,
) -> Dict:
    """LLM-based synthesis of technical + institutional data."""
    safe_symbol = _sanitize_for_prompt(symbol, max_len=20)
    prompt = _LLM_PROMPT.format(
        symbol=safe_symbol,
        technical_json=_sanitize_for_prompt(
            json.dumps(technical, ensure_ascii=False, indent=2), max_len=2000
        ),
        institutional_json=_sanitize_for_prompt(
            json.dumps(institutional, ensure_ascii=False, indent=2), max_len=2000
        ),
    )

    result = call_agent_llm(prompt, model=DEFAULT_MODEL)

    # Check for LLM error — return safe defaults
    if result.get("_error"):
        log.warning(
            "[stock_research] LLM error for %s: %s", symbol, result.get("_error")
        )
        return {
            "rating": "C",
            "entry_price": None,
            "stop_loss": None,
            "target_price": None,
            "confidence": 0.0,
            "rationale": f"LLM error: {result.get('_error', 'unknown')}",
            "risk_notes": [],
            "_raw": result,
        }

    # Validate rating against whitelist
    raw_rating = result.get("rating", "C")
    rating = raw_rating if raw_rating in _VALID_RATINGS else "C"

    # Ensure required fields with defaults
    return {
        "rating": rating,
        "entry_price": result.get("entry_price"),
        "stop_loss": result.get("stop_loss"),
        "target_price": result.get("target_price"),
        "confidence": float(result.get("confidence", 0.0)),
        "rationale": result.get("rationale", result.get("summary", "")),
        "risk_notes": result.get("risk_notes", []),
        "_raw": result,
    }


# ── Report Generator ──────────────────────────────────────────────────────────


def generate_report(symbol: str, layers_result: Dict) -> str:
    """Generate a Markdown research report from layers data."""
    tech = layers_result.get("technical", {})
    inst = layers_result.get("institutional", {})
    synth = layers_result.get("synthesis", {})

    rating = synth.get("rating", "N/A")
    entry = synth.get("entry_price")
    stop = synth.get("stop_loss")
    target = synth.get("target_price")

    lines = [
        f"# {symbol} 個股研究報告",
        f"**評級: {rating}** | 信心度: {synth.get('confidence', 'N/A')}",
        "",
        "## 技術面",
        f"- 收盤: {tech.get('close', 'N/A')}",
        f"- MA5/MA20/MA60: {tech.get('ma5', '-')}/{tech.get('ma20', '-')}/{tech.get('ma60', '-')}",
        f"- RSI14: {tech.get('rsi14', '-')}",
        f"- 趨勢: {tech.get('trend', '-')}",
        f"- 量比: {tech.get('volume_ratio', '-')}",
        f"- 支撐/壓力: {tech.get('support', '-')}/{tech.get('resistance', '-')}",
        "",
        "## 籌碼面",
        f"- 外資連買: {inst.get('foreign_consecutive_buy', 0)} 日",
        f"- 投信連買: {inst.get('trust_consecutive_buy', 0)} 日",
        f"- 近5日法人合計: {inst.get('recent_5d_total_net', 0):,.0f}",
        f"- 融資趨勢: {inst.get('margin_trend', '-')}",
        "",
        "## LLM 綜合評估",
        f"- 理由: {synth.get('rationale', '-')}",
    ]

    if entry is not None:
        lines.append(f"- 建議進場: {entry}")
    if stop is not None:
        lines.append(f"- 停損: {stop}")
    if target is not None:
        lines.append(f"- 目標: {target}")

    risk_notes = synth.get("risk_notes", [])
    if risk_notes:
        lines.append("")
        lines.append("## 風險提示")
        for note in risk_notes:
            lines.append(f"- {note}")

    return "\n".join(lines)


# ── Main Entry Point ──────────────────────────────────────────────────────────


def _load_watchlist() -> List[str]:
    """Load watchlist from config, capped at _MAX_STOCKS_PER_DAY.

    Uses ``manual_watchlist`` key exclusively (consistent with debate_loop).
    """
    watchlist_path = _REPO_ROOT / "config" / "watchlist.json"
    if not watchlist_path.exists():
        return []
    wl = json.loads(watchlist_path.read_text())
    # Use only manual_watchlist key for consistency with debate_loop
    symbols = wl.get("manual_watchlist", [])
    return symbols[:_MAX_STOCKS_PER_DAY]


def run_stock_research(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    """Run stock research loop over watchlist.

    - Max 10 stocks per day (LLM cost control)
    - A/B rated stocks auto-create POSITION_REBALANCE proposal
      (both A and B require human approval)
    """
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=_TZ_TWN).strftime("%Y-%m-%d")

    try:
        _ensure_table(_conn)

        watchlist = _load_watchlist()
        if not watchlist:
            return AgentResult(
                success=False,
                summary=f"Watchlist 為空，跳過 {_date} 個股研究",
                confidence=0.0,
                action_type="observe",
                proposals=[],
                raw={},
            )

        reports: List[Dict] = []
        proposal_ids: List[str] = []

        for symbol in watchlist:
            try:
                # Layer 1: Technical
                technical = layer1_technical(_conn, symbol, _date)
                if technical.get("error"):
                    log.warning("[stock_research] %s: %s — skipping", symbol, technical["error"])
                    continue

                # Layer 2: Institutional
                institutional = layer2_institutional(_conn, symbol, _date)

                # Layer 3: LLM Synthesis
                synthesis = layer3_llm_synthesis(technical, institutional, symbol)

                # Generate report
                layers_result = {
                    "technical": technical,
                    "institutional": institutional,
                    "synthesis": synthesis,
                }
                report_md = generate_report(symbol, layers_result)

                rating = synthesis.get("rating", "C")
                entry_price = synthesis.get("entry_price")
                stop_loss = synthesis.get("stop_loss")
                target_price = synthesis.get("target_price")

                # Save to DB
                report_id = str(uuid.uuid4())
                _conn.execute(
                    """INSERT OR REPLACE INTO stock_research_reports
                       (report_id, symbol, trade_date,
                        technical_json, institutional_json, llm_synthesis_json,
                        rating, entry_price, stop_loss, target_price,
                        report_markdown, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        report_id,
                        symbol,
                        _date,
                        json.dumps(technical, ensure_ascii=False),
                        json.dumps(institutional, ensure_ascii=False),
                        json.dumps(synthesis, ensure_ascii=False),
                        rating,
                        entry_price,
                        stop_loss,
                        target_price,
                        report_md,
                        int(time.time()),
                    ),
                )

                # Write LLM trace
                write_trace(
                    _conn,
                    agent="stock_research",
                    prompt=f"[{symbol}] layer3_llm_synthesis",
                    result={
                        "summary": synthesis.get("rationale", ""),
                        "confidence": synthesis.get("confidence", 0.0),
                        "action_type": "suggest" if rating in ("A", "B") else "observe",
                    },
                )

                # A/B rated → create POSITION_REBALANCE proposal
                if rating in ("A", "B"):
                    pid = write_proposal(
                        _conn,
                        generated_by="stock_research",
                        target_rule="POSITION_REBALANCE",
                        rule_category="position",
                        proposed_value=json.dumps(
                            {
                                "symbol": symbol,
                                "rating": rating,
                                "entry_price": entry_price,
                                "stop_loss": stop_loss,
                                "target_price": target_price,
                            },
                            ensure_ascii=False,
                        ),
                        supporting_evidence=synthesis.get("rationale", ""),
                        confidence=synthesis.get("confidence", 0.0),
                        requires_human_approval=1,  # Both A and B require human approval
                        proposal_type="POSITION_REBALANCE",
                    )
                    proposal_ids.append(pid)
                    log.info(
                        "[stock_research] %s rated %s → proposal %s created",
                        symbol, rating, pid,
                    )

                reports.append(
                    {
                        "symbol": symbol,
                        "rating": rating,
                        "confidence": synthesis.get("confidence", 0.0),
                        "entry_price": entry_price,
                        "stop_loss": stop_loss,
                        "target_price": target_price,
                    }
                )

            except Exception as e:
                log.error("[stock_research] %s failed: %s", symbol, e, exc_info=True)
                continue

        _conn.commit()

        # Aggregate summary
        a_count = sum(1 for r in reports if r["rating"] == "A")
        b_count = sum(1 for r in reports if r["rating"] == "B")
        summary = (
            f"個股研究完成：{len(reports)}/{len(watchlist)} 檔分析完畢，"
            f"A級 {a_count} 檔、B級 {b_count} 檔，"
            f"共產生 {len(proposal_ids)} 個 POSITION_REBALANCE 提案"
        )

        return AgentResult(
            success=True,
            summary=summary,
            confidence=0.7,
            action_type="suggest" if proposal_ids else "observe",
            proposals=[{"proposal_id": pid} for pid in proposal_ids],
            raw={
                "trade_date": _date,
                "reports": reports,
                "proposal_ids": proposal_ids,
            },
        )
    finally:
        if conn is None:
            _conn.close()
