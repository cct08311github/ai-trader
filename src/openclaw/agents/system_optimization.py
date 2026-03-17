"""agents/system_optimization.py — 系統優化員 Agent。

執行時機：每週一 07:00，或 watcher 連續 3 日無成交時觸發
工作：Python 查近 4 週交易績效 → Gemini 評估訊號閾值是否需調整
"""
from __future__ import annotations
from openclaw.path_utils import get_repo_root

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw.agents.base import (

    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    query_db, to_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = get_repo_root()

# 現有訊號閾值（從環境變數讀取，與 ticker_watcher 一致）
_BUY_SIGNAL_PCT   = float(os.environ.get("BUY_SIGNAL_PCT",   "0.002"))
_TAKE_PROFIT_PCT  = float(os.environ.get("TAKE_PROFIT_PCT",  "0.02"))
_STOP_LOSS_PCT    = float(os.environ.get("STOP_LOSS_PCT",    "0.03"))

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 SystemOptimizationAgent（系統優化員）。

## 執行時間：{now_utc}

## 當前訊號閾值
- BUY_SIGNAL_PCT：{buy_pct}（close < ref*(1-threshold) 觸發 buy）
- TAKE_PROFIT_PCT：{tp_pct}（止盈觸發點）
- STOP_LOSS_PCT：{sl_pct}（止損觸發點）

## 近 4 週交易統計
### 訊號分佈
{signal_stats}

### 損益統計
{pnl_stats}

## 任務
1. 若 buy 訊號勝率 < 40% 或平均損益 < 0，建議提高 BUY_SIGNAL_PCT（減少假訊號）
2. 若止損次數 > 止盈次數，考慮調整 STOP_LOSS_PCT
3. 若整體績效良好，proposals 為空列表，action_type 為 "observe"

## 注意
所有參數變更建議都必須 requires_human_approval=1，不可自動套用。

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.7,
  "action_type": "observe",
  "proposals": []
}}
```
"""


def run_system_optimization(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    try:
        signal_stats = query_db(_conn,
            "SELECT signal_side, COUNT(*) as cnt, AVG(signal_score) as avg_score "
            "FROM decisions WHERE ts > datetime('now','-28 days') "
            "GROUP BY signal_side")
        pnl_stats = query_db(_conn,
            "SELECT COUNT(*) as trades, SUM(realized_pnl) as total_pnl, "
            "AVG(realized_pnl) as avg_pnl "
            "FROM daily_pnl_summary "
            "WHERE trade_date > date('now','-28 days')")

        prompt = _PROMPT_TEMPLATE.format(
            now_utc=datetime.now(tz=timezone.utc).isoformat(),
            buy_pct=_BUY_SIGNAL_PCT,
            tp_pct=_TAKE_PROFIT_PCT,
            sl_pct=_STOP_LOSS_PCT,
            signal_stats=signal_stats or "（無資料）",
            pnl_stats=pnl_stats or "（無損益記錄）",
        )

        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="system_optimization",
                    prompt=prompt[:500], result=result_dict)

        result = to_agent_result(result_dict)
        for p in result.proposals:
            write_proposal(
                _conn,
                generated_by="system_optimization",
                target_rule=p.get("target_rule", "CONFIG"),
                rule_category=p.get("rule_category", "config"),
                proposed_value=str(p.get("proposed_value", "")),
                supporting_evidence=str(p.get("supporting_evidence", "")),
                confidence=float(p.get("confidence", 0.5)),
                requires_human_approval=1,   # config 變更強制人工確認
                proposal_type="config_change",
            )
        return result
    finally:
        if conn is None:
            _conn.close()
