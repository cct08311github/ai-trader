"""agents/portfolio_review.py — Portfolio 審查員 Agent。

執行時機：每交易日 14:30（收盤後）
工作：Python 查持倉/損益 → Gemini 分析健康度 → 再平衡建議
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
你是 AI Trader 系統的 PortfolioReviewAgent（Portfolio 審查員）。

## 審查日期：{trade_date}

### 當前持倉
{positions}

### 今日損益
{pnl_today}

### 今日成交紀錄
{fills_today}

## 任務
1. 計算持倉集中度（單一股票 > 40% 市值比重需警示）
2. 評估今日勝率（獲利筆數 / 總成交筆數）
3. 若有再平衡需求，提出具體建議

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.8,
  "action_type": "observe",
  "proposals": [
    {{
      "target_rule": "POSITION_REBALANCE",
      "rule_category": "portfolio",
      "proposed_value": "...",
      "supporting_evidence": "...",
      "confidence": 0.7,
      "requires_human_approval": 0
    }}
  ]
}}
```
若無需再平衡，proposals 為空列表。
"""


def run_portfolio_review(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    try:
        positions = query_db(_conn,
            "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0")
        pnl_today = query_db(_conn,
            "SELECT symbol, realized_pnl FROM daily_pnl_summary WHERE trade_date=?",
            (_date,))
        fills_today = query_db(_conn,
            "SELECT o.symbol, o.side, o.qty, f.price "
            "FROM orders o JOIN fills f ON o.order_id=f.order_id "
            "WHERE date(o.ts_submit)=?",
            (_date,))

        prompt = _PROMPT_TEMPLATE.format(
            trade_date=_date,
            positions=positions or "（無持倉）",
            pnl_today=pnl_today or "（無損益記錄）",
            fills_today=fills_today or "（今日無成交）",
        )

        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="portfolio_review", prompt=prompt[:500], result=result_dict)

        result = to_agent_result(result_dict)
        for p in result.proposals:
            write_proposal(
                _conn,
                generated_by="portfolio_review",
                target_rule=p.get("target_rule", "PORTFOLIO"),
                rule_category=p.get("rule_category", "portfolio"),
                proposed_value=str(p.get("proposed_value", "")),
                supporting_evidence=str(p.get("supporting_evidence", "")),
                confidence=float(p.get("confidence", 0.5)),
                requires_human_approval=int(p.get("requires_human_approval", 0)),
            )
        return result
    finally:
        if conn is None:
            _conn.close()
