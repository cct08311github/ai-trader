"""agents/strategy_committee.py — 策略小組 Agent（三方辯論）。

執行時機：PM 審核完成後（事件），或每週一 07:30
工作：Bull Analyst → Bear Analyst → Risk Arbiter 三次序列 Gemini 呼叫
"""
from __future__ import annotations

import sqlite3
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from openclaw.agents.base import (
    AgentResult, COMMITTEE_MODEL, call_agent_llm, open_conn,
    query_db, to_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_BULL_PROMPT = """\
你是 AI Trader 的 Bull Analyst（看多派分析師）。

## 市場數據
{market_data}

## 任務
從技術面與籌碼面找出做多理由，提出今日加碼方向與目標價。
輸出 JSON：{{"bull_thesis": "...", "confidence": 0.7, "targets": ["2330", ...]}}
"""

_BEAR_PROMPT = """\
你是 AI Trader 的 Bear Analyst（看空派分析師）。

## 市場數據
{market_data}

## 看多方觀點
{bull_thesis}

## 任務
找出風險與下跌訊號，反駁或補充看多觀點，提出減碼建議。
輸出 JSON：{{"bear_thesis": "...", "confidence": 0.65, "risks": ["..."]}}
"""

_ARBITER_PROMPT = """\
你是 AI Trader 的 Risk Arbiter（風險仲裁者）。

## 看多方
{bull_thesis}（置信：{bull_confidence}）

## 看空方
{bear_thesis}（置信：{bear_confidence}）

## 任務
整合雙方意見，給出 confidence-weighted 最終策略建議。
不能預設採用保守結論，也不能流於空泛口號。
你必須根據雙方證據判斷：
- 若風險明顯高於報酬，才給出防守/降風險建議
- 若報酬風險比仍有利，可給出中性或偏積極建議
- 若資訊不足，需明確指出缺口，而不是套用固定模板

輸出 JSON：
```json
{{
  "summary": "...",
  "confidence": 0.0,
  "stance": "defensive|neutral|constructive",
  "decision_basis": {{
    "bull_points": ["..."],
    "bear_points": ["..."],
    "key_tradeoffs": ["..."],
    "data_gaps": ["..."]
  }},
  "action_type": "suggest",
  "proposals": [
    {{
      "target_rule": "STRATEGY_DIRECTION",
      "rule_category": "strategy",
      "proposed_value": "...",
      "supporting_evidence": "...",
      "confidence": 0.65,
      "requires_human_approval": 1
    }}
  ]
}}
```
    """

_DEDUP_LOOKBACK_HOURS = 12
_DEDUP_VALUE_SIMILARITY_THRESHOLD = 0.74
_DEDUP_COMBINED_SIMILARITY_THRESHOLD = 0.7


def _build_market_context(conn: sqlite3.Connection) -> str:
    positions = query_db(
        conn,
        "SELECT symbol, quantity, avg_price, unrealized_pnl FROM positions "
        "WHERE quantity > 0 ORDER BY quantity DESC LIMIT 8"
    )
    recent_pnl = query_db(
        conn,
        "SELECT trade_date, SUM(realized_pnl) as pnl FROM daily_pnl_summary "
        "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5"
    )
    latest_prices = query_db(
        conn,
        "SELECT trade_date, symbol, close, change, volume FROM eod_prices "
        "ORDER BY trade_date DESC, volume DESC LIMIT 12"
    )
    recent_decisions = query_db(
        conn,
        "SELECT ts, symbol, signal_side, signal_score FROM decisions "
        "ORDER BY ts DESC LIMIT 8"
    )

    return (
        f"持倉摘要：{positions}\n"
        f"近期損益：{recent_pnl}\n"
        f"最新價量樣本：{latest_prices}\n"
        f"近期決策樣本：{recent_decisions}"
    )


def _normalize_strategy_text(*parts: str) -> str:
    normalized = " ".join((part or "").strip().lower() for part in parts if part)
    return " ".join(normalized.split())


def _find_recent_similar_strategy_direction(
    conn: sqlite3.Connection,
    *,
    proposed_value: str,
    supporting_evidence: str,
    lookback_hours: int = _DEDUP_LOOKBACK_HOURS,
    value_similarity_threshold: float = _DEDUP_VALUE_SIMILARITY_THRESHOLD,
    combined_similarity_threshold: float = _DEDUP_COMBINED_SIMILARITY_THRESHOLD,
) -> Optional[dict[str, Any]]:
    lookback_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - (lookback_hours * 60 * 60 * 1000)
    candidate_rows = conn.execute(
        """
        SELECT proposal_id, proposed_value, supporting_evidence, created_at
          FROM strategy_proposals
         WHERE generated_by='strategy_committee'
           AND target_rule='STRATEGY_DIRECTION'
           AND created_at >= ?
         ORDER BY created_at DESC
         LIMIT 10
        """,
        (lookback_ms,),
    ).fetchall()

    current_value = _normalize_strategy_text(proposed_value)
    current_evidence = _normalize_strategy_text(supporting_evidence)
    current_text = _normalize_strategy_text(proposed_value, supporting_evidence)
    if not current_value and not current_text:
        return None

    for row in candidate_rows:
        previous_value = _normalize_strategy_text(row["proposed_value"])
        previous_evidence = _normalize_strategy_text(row["supporting_evidence"])
        previous_text = _normalize_strategy_text(row["proposed_value"], row["supporting_evidence"])
        if not previous_value and not previous_text:
            continue
        value_similarity = SequenceMatcher(None, current_value, previous_value).ratio()
        evidence_similarity = SequenceMatcher(None, current_evidence, previous_evidence).ratio()
        combined_similarity = SequenceMatcher(None, current_text, previous_text).ratio()
        if (
            value_similarity >= value_similarity_threshold
            or combined_similarity >= combined_similarity_threshold
        ):
            return {
                "proposal_id": row["proposal_id"],
                "created_at": row["created_at"],
                "similarity": round(max(value_similarity, combined_similarity), 4),
                "value_similarity": round(value_similarity, 4),
                "evidence_similarity": round(evidence_similarity, 4),
                "combined_similarity": round(combined_similarity, 4),
                "lookback_hours": lookback_hours,
            }
    return None


def run_strategy_committee(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    try:
        market_data = _build_market_context(_conn)

        # ── Round 1: Bull Analyst ────────────────────────────────────────
        bull_prompt = _BULL_PROMPT.format(market_data=market_data)
        bull_resp = call_agent_llm(bull_prompt, model=COMMITTEE_MODEL)
        write_trace(_conn, agent="strategy_committee",
                    prompt="[Bull Analyst] " + bull_prompt[:300], result=bull_resp)

        bull_thesis = bull_resp.get("bull_thesis", str(bull_resp.get("summary", "")))
        bull_confidence = float(bull_resp.get("confidence", 0.5))

        # ── Round 2: Bear Analyst ────────────────────────────────────────
        bear_prompt = _BEAR_PROMPT.format(
            market_data=market_data, bull_thesis=bull_thesis)
        bear_resp = call_agent_llm(bear_prompt, model=COMMITTEE_MODEL)
        write_trace(_conn, agent="strategy_committee",
                    prompt="[Bear Analyst] " + bear_prompt[:300], result=bear_resp)

        bear_thesis = bear_resp.get("bear_thesis", str(bear_resp.get("summary", "")))
        bear_confidence = float(bear_resp.get("confidence", 0.5))

        # ── Round 3: Risk Arbiter ────────────────────────────────────────
        arbiter_prompt = _ARBITER_PROMPT.format(
            bull_thesis=bull_thesis, bull_confidence=bull_confidence,
            bear_thesis=bear_thesis, bear_confidence=bear_confidence,
        )
        arbiter_resp = call_agent_llm(arbiter_prompt, model=COMMITTEE_MODEL)
        write_trace(_conn, agent="strategy_committee",
                    prompt="[Risk Arbiter] " + arbiter_prompt[:300], result=arbiter_resp)

        # ── 寫入提案（必須人工確認）───────────────────────────────────────
        result = to_agent_result(arbiter_resp)
        duplicate_alerts: list[dict[str, Any]] = []
        persisted_proposals: list[dict[str, Any]] = []

        for p in result.proposals:
            target_rule = p.get("target_rule", "STRATEGY")
            proposed_value = str(p.get("proposed_value", ""))
            supporting_evidence = str(p.get("supporting_evidence", ""))

            duplicate_info = None
            if target_rule == "STRATEGY_DIRECTION":
                duplicate_info = _find_recent_similar_strategy_direction(
                    _conn,
                    proposed_value=proposed_value,
                    supporting_evidence=supporting_evidence,
                )

            if duplicate_info:
                duplicate_alert = {
                    "target_rule": target_rule,
                    "proposed_value": proposed_value,
                    "supporting_evidence": supporting_evidence,
                    "duplicate_of": duplicate_info["proposal_id"],
                    "similarity": duplicate_info["similarity"],
                    "lookback_hours": duplicate_info["lookback_hours"],
                    "action": "suppressed",
                }
                duplicate_alerts.append(duplicate_alert)
                write_trace(
                    _conn,
                    agent="strategy_committee",
                    prompt="[Duplicate Guard] suppress similar STRATEGY_DIRECTION proposal",
                    result={
                        "summary": (
                            "相似策略提案已抑制，避免短時間重複產出相同方向。"
                            f" similarity={duplicate_info['similarity']}"
                        ),
                        "confidence": float(p.get("confidence", result.confidence)),
                        "action_type": "observe",
                        "duplicate_alert": duplicate_alert,
                        "_model": COMMITTEE_MODEL,
                        "_latency_ms": 0,
                    },
                )
                continue

            proposal_payload = {
                "generated_by": "strategy_committee",
                "target_rule": target_rule,
                "rule_category": p.get("rule_category", "strategy"),
                "type": "suggest",
                "committee_context": {
                    "market_data": market_data,
                    "bull": {
                        "thesis": bull_thesis,
                        "confidence": bull_confidence,
                        "raw": bull_resp,
                    },
                    "bear": {
                        "thesis": bear_thesis,
                        "confidence": bear_confidence,
                        "raw": bear_resp,
                    },
                    "arbiter": {
                        "summary": arbiter_resp.get("summary", ""),
                        "stance": arbiter_resp.get("stance", "neutral"),
                        "decision_basis": arbiter_resp.get("decision_basis", {}),
                        "raw": arbiter_resp,
                    },
                },
            }
            write_proposal(
                _conn,
                generated_by="strategy_committee",
                target_rule=target_rule,
                rule_category=p.get("rule_category", "strategy"),
                proposed_value=proposed_value,
                supporting_evidence=supporting_evidence,
                confidence=float(p.get("confidence", 0.5)),
                requires_human_approval=1,   # 策略小組建議必須人工確認
                proposal_type="suggest",
                proposal_payload=proposal_payload,
            )
            persisted_proposals.append(p)

        if duplicate_alerts:
            result.raw["duplicate_alerts"] = duplicate_alerts
        result.proposals = persisted_proposals
        return result
    finally:
        if conn is None:
            _conn.close()
