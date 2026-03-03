"""agents.py — Agent 執行監控 + 手動觸發 API。"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

import app.db as db

router = APIRouter(prefix="/api/agents", tags=["agents"])
log = logging.getLogger("agents_api")

# ── Agent 定義 ────────────────────────────────────────────────────────────────

AGENTS: dict[str, dict] = {
    "market_research": {
        "label": "Market Research",
        "label_zh": "市場研究員",
        "description": "分析大盤走勢、板塊資金流向、異常成交量",
        "schedule": "每交易日 08:20",
    },
    "portfolio_review": {
        "label": "Portfolio Review",
        "label_zh": "Portfolio 審查員",
        "description": "持倉集中度風險、當日勝率分析、再平衡建議",
        "schedule": "每交易日 14:30",
    },
    "system_health": {
        "label": "System Health",
        "label_zh": "系統健康監控",
        "description": "監控 PM2 服務、DB 狀態、磁碟空間、watcher 心跳",
        "schedule": "每 30 / 120 分鐘",
    },
    "strategy_committee": {
        "label": "Strategy Committee",
        "label_zh": "策略小組",
        "description": "多空辯論三方共識（Bull → Bear → Risk Arbiter）",
        "schedule": "PM 審核後 / 每週一 07:30",
    },
    "system_optimization": {
        "label": "System Optimization",
        "label_zh": "系統優化員",
        "description": "分析近 4 週交易，建議 BUY/STOP_LOSS/TAKE_PROFIT 參數調整",
        "schedule": "每週一 07:00 / 3 日無成交觸發",
    },
}

# ── 執行狀態追蹤 ──────────────────────────────────────────────────────────────

_running: set[str] = set()
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(str(db.DB_PATH), timeout=10)


# ── 背景執行 ──────────────────────────────────────────────────────────────────

def _run_agent_bg(agent_name: str, db_path: str) -> None:
    with _lock:
        _running.add(agent_name)
    try:
        from openclaw.agents.base import open_conn
        conn = open_conn(db_path)
        try:
            today = str(date.today())
            if agent_name == "market_research":
                from openclaw.agents.market_research import run_market_research
                run_market_research(today, conn, db_path)
            elif agent_name == "portfolio_review":
                from openclaw.agents.portfolio_review import run_portfolio_review
                run_portfolio_review(today, conn, db_path)
            elif agent_name == "system_health":
                from openclaw.agents.system_health import run_system_health
                run_system_health(conn, db_path)
            elif agent_name == "strategy_committee":
                from openclaw.agents.strategy_committee import run_strategy_committee
                run_strategy_committee(conn, db_path)
            elif agent_name == "system_optimization":
                from openclaw.agents.system_optimization import run_system_optimization
                run_system_optimization(conn, db_path)
        finally:
            conn.close()
    except Exception as e:
        log.error("[agents_api] %s failed: %s", agent_name, e, exc_info=True)
    finally:
        with _lock:
            _running.discard(agent_name)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
def list_agents():
    """各 Agent 最後執行摘要。"""
    conn = _conn()
    try:
        result = []
        for name, meta in AGENTS.items():
            row = conn.execute(
                """
                SELECT created_at, confidence,
                       CASE WHEN json_valid(response)
                            THEN json_extract(response, '$.summary')
                            ELSE NULL END AS summary,
                       latency_ms, model
                FROM llm_traces
                WHERE agent = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
            result.append({
                "name": name,
                **meta,
                "last_run_at": row[0] if row else None,
                "last_confidence": row[1] if row else None,
                "last_summary": row[2] if row else None,
                "last_latency_ms": row[3] if row else None,
                "last_model": row[4] if row else None,
            })
        return {"status": "ok", "data": result, "running": list(_running)}
    finally:
        conn.close()


@router.get("/{agent_name}/history")
def agent_history(agent_name: str, limit: int = Query(20, ge=1, le=100)):
    """指定 Agent 的執行歷史（最新在前）。"""
    if agent_name not in AGENTS:
        raise HTTPException(404, f"Unknown agent: {agent_name}")
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT trace_id, created_at, confidence,
                   CASE WHEN json_valid(response)
                        THEN json_extract(response, '$.summary')
                        ELSE NULL END AS summary,
                   latency_ms, model
            FROM llm_traces
            WHERE agent = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (agent_name, limit),
        ).fetchall()
        return {
            "status": "ok",
            "data": [
                {
                    "trace_id": r[0],
                    "created_at": r[1],
                    "confidence": r[2],
                    "summary": r[3],
                    "latency_ms": r[4],
                    "model": r[5],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.post("/{agent_name}/run")
def run_agent(agent_name: str):
    """手動觸發 Agent（背景執行，立即回傳）。"""
    if agent_name not in AGENTS:
        raise HTTPException(404, f"Unknown agent: {agent_name}")
    with _lock:
        if agent_name in _running:
            raise HTTPException(409, f"{agent_name} 已在執行中，請稍候")
    db_path = str(db.DB_PATH)
    thread = threading.Thread(
        target=_run_agent_bg, args=(agent_name, db_path), daemon=True
    )
    thread.start()
    log.info("[agents_api] Manually triggered: %s", agent_name)
    return {"status": "started", "agent": agent_name}
