"""agents/market_research.py — 市場研究員 Agent。

執行時機：每交易日 08:20
工作：Python 查 EOD 數據 → Gemini 分析市場結構 → 板塊建議
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw.agents.base import (
    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    query_db, to_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 MarketResearchAgent（市場研究員）。

## 分析日期：{trade_date}

### TWSE 漲跌幅前 10 名
{top_movers}

### 成交量前 5 名
{top_volume}

## 任務
1. 判斷今日主力板塊（半導體/金融/傳產/電子等）
2. 評估整體多空氣氛（偏多/中性/偏空）
3. 若有明顯強勢板塊，提出板塊建議 proposal

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.75,
  "action_type": "suggest",
  "proposals": [
    {{
      "target_rule": "SECTOR_FOCUS",
      "rule_category": "allocation",
      "proposed_value": "...",
      "supporting_evidence": "...",
      "confidence": 0.75,
      "requires_human_approval": 0
    }}
  ]
}}
```
若無明顯訊號，proposals 為空列表，action_type 為 "observe"。
"""


def run_market_research(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    try:
        top_movers = query_db(
            _conn,
            "SELECT symbol, name, close, change FROM eod_prices "
            "WHERE trade_date=? AND market='TWSE' AND close IS NOT NULL "
            "ORDER BY ABS(change) DESC LIMIT 10",
            (_date,),
        )
        top_volume = query_db(
            _conn,
            "SELECT symbol, name, volume FROM eod_prices "
            "WHERE trade_date=? AND market='TWSE' AND volume IS NOT NULL "
            "ORDER BY volume DESC LIMIT 5",
            (_date,),
        )

        prompt = _PROMPT_TEMPLATE.format(
            trade_date=_date,
            top_movers=top_movers or "（無資料）",
            top_volume=top_volume or "（無資料）",
        )

        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="market_research", prompt=prompt[:500], result=result_dict)

        result = to_agent_result(result_dict)
        for p in result.proposals:
            write_proposal(
                _conn,
                generated_by="market_research",
                target_rule=p.get("target_rule", "MARKET_DIRECTION"),
                rule_category=p.get("rule_category", "analysis"),
                proposed_value=str(p.get("proposed_value", "")),
                supporting_evidence=str(p.get("supporting_evidence", "")),
                confidence=float(p.get("confidence", 0.5)),
                requires_human_approval=int(p.get("requires_human_approval", 0)),
            )
        return result
    finally:
        if conn is None:
            _conn.close()
