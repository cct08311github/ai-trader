"""agents/base.py — 共用 helper：DB 查詢、LLM 呼叫、trace/proposal 寫入。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw.llm_minimax import minimax_call
from openclaw.llm_observability import LLMTrace, insert_llm_trace
from openclaw.path_utils import get_repo_root

_REPO_ROOT = get_repo_root()
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")

# 預設模型：可透過環境變數覆寫
DEFAULT_MODEL: str = os.environ.get("AGENT_LLM_MODEL", "MiniMax-M2.5")
COMMITTEE_MODEL: str = os.environ.get("AGENT_COMMITTEE_MODEL", "MiniMax-M2.5")


def open_conn(db_path: str = _DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def query_db(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """執行 SELECT，回傳 list of dict。"""
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def call_agent_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """呼叫 MiniMax M2.5，回傳解析後的 dict。失敗時回傳 fallback dict。"""
    try:
        return minimax_call(model, prompt)
    except Exception as e:
        return {
            "summary": f"LLM 呼叫失敗：{e}",
            "confidence": 0.0,
            "action_type": "observe",
            "proposals": [],
            "_error": str(e),
        }


def write_trace(
    conn: sqlite3.Connection,
    *,
    agent: str,
    prompt: str,
    result: Dict[str, Any],
) -> None:
    """LLMTrace 寫入 DB（SSE → LogTerminal 即時可見）。"""
    trace = LLMTrace(
        component=agent,
        agent=agent,
        model=result.get("_model", DEFAULT_MODEL),
        prompt_text=prompt[:1000],
        response_text=json.dumps(
            {k: v for k, v in result.items() if not k.startswith("_")},
            ensure_ascii=False,
        ),
        input_tokens=0,
        output_tokens=0,
        latency_ms=int(result.get("_latency_ms", 0)),
        confidence=float(result.get("confidence", 0.0)),
        metadata={
            "action_type": result.get("action_type", "observe"),
            "summary": result.get("summary", ""),
            "prompt_version": "agents/base/v1",
            "model_version": result.get("_resolved_model", result.get("_model", DEFAULT_MODEL)),
            "input_snapshot": {"agent": agent, "prompt": prompt[:200]},
            "shadow_mode": bool(result.get("_shadow_mode", False)),
            "created_at_ms": int(time.time() * 1000),
        },
    )
    insert_llm_trace(conn, trace, auto_commit=True)


def write_proposal(
    conn: sqlite3.Connection,
    *,
    generated_by: str,
    target_rule: str,
    rule_category: str,
    proposed_value: str,
    supporting_evidence: str,
    confidence: float,
    requires_human_approval: int = 0,
    proposal_type: str = "suggest",
    proposal_payload: Optional[Dict[str, Any]] = None,
) -> str:
    """strategy_proposals に書き込む。proposal_id を返す。"""
    proposal_id = str(uuid.uuid4())
    payload = {
        "generated_by": generated_by,
        "target_rule": target_rule,
        "proposed_value": proposed_value,
        "type": proposal_type,
    }
    if proposal_payload:
        payload.update(proposal_payload)
    proposal_json = json.dumps(payload, ensure_ascii=False)
    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            current_value, proposed_value, supporting_evidence,
            confidence, requires_human_approval, status,
            proposal_json, created_at)
           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 'pending', ?, CAST(strftime('%s','now') AS INTEGER) * 1000)""",
        (
            proposal_id, generated_by, target_rule, rule_category,
            proposed_value, supporting_evidence,
            confidence, requires_human_approval, proposal_json,
        ),
    )
    conn.commit()
    return proposal_id


@dataclass
class AgentResult:
    summary: str
    confidence: float
    action_type: str          # observe | suggest | config_change
    proposals: List[Dict[str, Any]]
    raw: Dict[str, Any]
    success: bool = True


def to_agent_result(d: Dict[str, Any]) -> AgentResult:
    return AgentResult(
        summary=str(d.get("summary", "")),
        confidence=float(d.get("confidence", 0.5)),
        action_type=str(d.get("action_type", "observe")),
        proposals=list(d.get("proposals", [])),
        raw=d,
    )
