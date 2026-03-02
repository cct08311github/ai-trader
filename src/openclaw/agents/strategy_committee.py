"""agents/strategy_committee.py — 策略小組 Agent（三方辯論）。

執行時機：PM 審核完成後（事件），或每週一 07:30
工作：Bull Analyst → Bear Analyst → Risk Arbiter 三次序列 Gemini 呼叫
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
建議必須謹慎，優先保本。

輸出 JSON：
```json
{{
  "summary": "...",
  "confidence": 0.65,
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


def run_strategy_committee(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    try:
        # 取得基礎市場數據
        positions = query_db(_conn,
            "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0")
        recent_pnl = query_db(_conn,
            "SELECT trade_date, SUM(realized_pnl) as pnl FROM daily_pnl_summary "
            "GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5")
        market_data = f"持倉：{positions}\n近期損益：{recent_pnl}"

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
        for p in result.proposals:
            write_proposal(
                _conn,
                generated_by="strategy_committee",
                target_rule=p.get("target_rule", "STRATEGY"),
                rule_category=p.get("rule_category", "strategy"),
                proposed_value=str(p.get("proposed_value", "")),
                supporting_evidence=str(p.get("supporting_evidence", "")),
                confidence=float(p.get("confidence", 0.5)),
                requires_human_approval=1,   # 策略小組建議必須人工確認
                proposal_type="suggest",
            )
        return result
    finally:
        if conn is None:
            _conn.close()
