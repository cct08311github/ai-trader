# Agent Roles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 實作五個 LLM agent 角色（MarketResearch、PortfolioReview、SystemHealth、StrategyCommittee、SystemOptimization）並以統一 Orchestrator 排程執行。

**Architecture:** 單一 PM2 進程 `ai-trader-agents` 執行 `agent_orchestrator.py`。每個 agent 由 Python 直接執行 sqlite3 查詢取得數據，組成 prompt 後呼叫 `gemini_call()`，結果寫入 `llm_traces` + `strategy_proposals`，前端 LogTerminal 即時可見。

**Tech Stack:** Python 3.11+、`google-generativeai`（已安裝）、`openclaw.llm_gemini.gemini_call`、asyncio、sqlite3、PM2

**不需要新 API key**：沿用現有 `GEMINI_API_KEY`（`frontend/backend/.env` 已有）。

**預設模型**：`gemini-3.0-flash`（快速、低成本）；StrategyCommittee 使用 `gemini-3.1-pro`（推理能力更強）。可透過環境變數 `AGENT_LLM_MODEL` 覆寫。

---

## Task 1：建立 agents/ 套件與 base.py

**Files:**
- Create: `src/openclaw/agents/__init__.py`
- Create: `src/openclaw/agents/base.py`

**Step 1: 建立目錄**

```bash
mkdir -p src/openclaw/agents
touch src/openclaw/agents/__init__.py
```

**Step 2: 寫 `src/openclaw/agents/base.py`**

```python
"""agents/base.py — 共用 helper：DB 查詢、Gemini 呼叫、trace/proposal 寫入。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw.llm_gemini import gemini_call
from openclaw.llm_observability import LLMTrace, insert_llm_trace

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")

# 預設模型：可透過環境變數覆寫
DEFAULT_MODEL: str = os.environ.get("AGENT_LLM_MODEL", "gemini-3.0-flash")
COMMITTEE_MODEL: str = os.environ.get("AGENT_COMMITTEE_MODEL", "gemini-3.1-pro")


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
    """呼叫 Gemini，回傳解析後的 dict。失敗時回傳 fallback dict。"""
    try:
        return gemini_call(model, prompt)
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
        response_text=result.get("_raw_response", json.dumps(result, ensure_ascii=False))[:1000],
        input_tokens=0,
        output_tokens=0,
        latency_ms=int(result.get("_latency_ms", 0)),
        confidence=float(result.get("confidence", 0.0)),
        metadata={
            "action_type": result.get("action_type", "observe"),
            "summary": result.get("summary", ""),
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
) -> str:
    """strategy_proposals に書き込む。proposal_id を返す。"""
    proposal_id = str(uuid.uuid4())
    proposal_json = json.dumps({
        "generated_by": generated_by,
        "target_rule": target_rule,
        "proposed_value": proposed_value,
        "type": proposal_type,
    }, ensure_ascii=False)
    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            current_value, proposed_value, supporting_evidence,
            confidence, requires_human_approval, status,
            proposal_json, created_at)
           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 'pending', ?, strftime('%s','now'))""",
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


def to_agent_result(d: Dict[str, Any]) -> AgentResult:
    return AgentResult(
        summary=str(d.get("summary", "")),
        confidence=float(d.get("confidence", 0.5)),
        action_type=str(d.get("action_type", "observe")),
        proposals=list(d.get("proposals", [])),
        raw=d,
    )
```

**Step 3: Commit**

```bash
git add src/openclaw/agents/
git commit -m "feat: add agents/ package with Gemini-based base.py helpers"
```

---

## Task 2：unit test 基礎設施（test_agents.py）

**Files:**
- Create: `src/tests/test_agents.py`

**Step 1: 寫測試**

```python
"""test_agents.py — agents/base.py 的單元測試（mock gemini_call）。"""
from __future__ import annotations

import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch


# ── Fixture: in-memory DB ────────────────────────────────────────────────────

@pytest.fixture()
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        );
        CREATE TABLE eod_prices (
            trade_date TEXT,
            market TEXT,
            symbol TEXT,
            name TEXT,
            close REAL,
            change REAL,
            volume REAL
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL
        );
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT,
            symbol TEXT,
            realized_pnl REAL
        );
        CREATE TABLE decisions (
            decision_id TEXT,
            ts TEXT,
            symbol TEXT,
            signal_side TEXT,
            signal_score REAL
        );
    """)
    yield conn
    conn.close()


# ── Gemini mock helper ───────────────────────────────────────────────────────

def _mock_gemini(summary: str, confidence: float = 0.8,
                 action_type: str = "observe", proposals: list = None):
    """回傳模擬 gemini_call 結果的 MagicMock。"""
    return {
        "summary": summary,
        "confidence": confidence,
        "action_type": action_type,
        "proposals": proposals or [],
        "_raw_response": f'{{"summary": "{summary}"}}',
        "_latency_ms": 500,
        "_model": "gemini-3.0-flash",
    }


# ── write_trace ──────────────────────────────────────────────────────────────

class TestWriteTrace:
    def test_inserts_row(self, mem_db):
        from openclaw.agents.base import write_trace
        result = _mock_gemini("系統正常")
        write_trace(mem_db, agent="test_agent", prompt="check", result=result)
        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row is not None
        assert row[0] == "test_agent"

    def test_confidence_stored(self, mem_db):
        from openclaw.agents.base import write_trace
        result = _mock_gemini("測試", confidence=0.75)
        write_trace(mem_db, agent="a", prompt="p", result=result)
        row = mem_db.execute("SELECT confidence FROM llm_traces").fetchone()
        assert row[0] == pytest.approx(0.75, abs=0.01)


# ── write_proposal ───────────────────────────────────────────────────────────

class TestWriteProposal:
    def test_inserts_pending(self, mem_db):
        from openclaw.agents.base import write_proposal
        pid = write_proposal(
            mem_db,
            generated_by="market_research",
            target_rule="SECTOR_FOCUS",
            rule_category="allocation",
            proposed_value="半導體",
            supporting_evidence="近 5 日強勢",
            confidence=0.75,
        )
        row = mem_db.execute(
            "SELECT status, requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] == 0

    def test_config_change_requires_approval(self, mem_db):
        from openclaw.agents.base import write_proposal
        pid = write_proposal(
            mem_db,
            generated_by="system_optimization",
            target_rule="BUY_SIGNAL_PCT",
            rule_category="config",
            proposed_value="0.003",
            supporting_evidence="勝率偏低",
            confidence=0.6,
            requires_human_approval=1,
            proposal_type="config_change",
        )
        row = mem_db.execute(
            "SELECT requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == 1


# ── call_agent_llm（fallback 測試）──────────────────────────────────────────

class TestCallAgentLlm:
    def test_returns_fallback_on_error(self):
        from openclaw.agents.base import call_agent_llm
        with patch("openclaw.agents.base.gemini_call", side_effect=RuntimeError("no key")):
            result = call_agent_llm("test prompt")
        assert result["action_type"] == "observe"
        assert result["confidence"] == 0.0
        assert "LLM 呼叫失敗" in result["summary"]
```

**Step 2: 執行測試，確認通過**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS

**Step 3: Commit**

```bash
git add src/tests/test_agents.py
git commit -m "test: add test_agents.py for Gemini-based base.py helpers"
```

---

## Task 3：SystemHealthAgent

**Files:**
- Create: `src/openclaw/agents/system_health.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestSystemHealthAgent:
    def test_writes_trace_on_healthy(self, mem_db):
        mock_resp = _mock_gemini("所有服務正常運作", confidence=0.95)
        with patch("openclaw.agents.system_health.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_health import run_system_health
            run_system_health(conn=mem_db)
        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row[0] == "system_health"

    def test_no_proposals_when_healthy(self, mem_db):
        mock_resp = _mock_gemini("健康", confidence=0.95, proposals=[])
        with patch("openclaw.agents.system_health.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_health import run_system_health
            result = run_system_health(conn=mem_db)
        assert len(result.proposals) == 0
```

**Step 2: 確認失敗**

```bash
python -m pytest src/tests/test_agents.py::TestSystemHealthAgent -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: 實作 `src/openclaw/agents/system_health.py`**

```python
"""agents/system_health.py — 系統健康監控 Agent。

執行時機：每 30 分鐘（市場時段）/ 每 2 小時（非市場時段）
工作：Python 收集 PM2 / DB / 磁碟資料，Gemini 進行健康評估
"""
from __future__ import annotations

import subprocess
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw.agents.base import (
    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    to_agent_result, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 SystemHealthAgent（系統健康監控員）。

## 當前系統狀態
執行時間：{now_utc}

### PM2 進程狀態
```
{pm2_status}
```

### Watcher 近 5 分鐘是否有活動
近 5 分鐘 watcher traces 數量：{watcher_recent_count}

### 磁碟空間
```
{disk_info}
```

## 任務
根據以上資訊評估系統健康度。
若任何服務 offline 或磁碟使用 > 90%，action_type 改為 "suggest" 並在 proposals 列出修復建議。

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.95,
  "action_type": "observe",
  "proposals": []
}}
```
"""


def _get_pm2_status() -> str:
    try:
        r = subprocess.run(
            ["pm2", "list", "--no-color"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout[:1000] if r.stdout else "PM2 不可用"
    except Exception as e:
        return f"PM2 查詢失敗：{e}"


def _get_disk_info() -> str:
    try:
        r = subprocess.run(
            ["df", "-h", str(_REPO_ROOT)],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout[:300] if r.stdout else "無法取得磁碟資訊"
    except Exception as e:
        return f"磁碟查詢失敗：{e}"


def _get_watcher_recent_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM llm_traces "
            "WHERE agent='watcher' AND created_at > strftime('%s','now','-5 minutes')"
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return -1


def run_system_health(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _conn = conn or open_conn(db_path or "")
    try:
        pm2_status = _get_pm2_status()
        disk_info = _get_disk_info()
        watcher_count = _get_watcher_recent_count(_conn)

        prompt = _PROMPT_TEMPLATE.format(
            now_utc=datetime.now(tz=timezone.utc).isoformat(),
            pm2_status=pm2_status,
            disk_info=disk_info,
            watcher_recent_count=watcher_count,
        )

        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="system_health", prompt=prompt[:500], result=result_dict)
        return to_agent_result(result_dict)
    finally:
        if conn is None:
            _conn.close()
```

**Step 4: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

**Step 5: Commit**

```bash
git add src/openclaw/agents/system_health.py src/tests/test_agents.py
git commit -m "feat: add SystemHealthAgent (Gemini-based)"
```

---

## Task 4：MarketResearchAgent

**Files:**
- Create: `src/openclaw/agents/market_research.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestMarketResearchAgent:
    def test_writes_trace_and_proposal(self, mem_db):
        # 插入測試用 EOD 數據
        mem_db.execute(
            "INSERT INTO eod_prices VALUES ('2026-03-02','TWSE','2330','台積電',900,15,50000)"
        )
        mem_db.commit()
        mock_resp = _mock_gemini(
            "半導體強勢，2330 漲幅最大",
            confidence=0.78,
            action_type="suggest",
            proposals=[{
                "target_rule": "SECTOR_FOCUS",
                "rule_category": "allocation",
                "proposed_value": "半導體",
                "supporting_evidence": "近日成交量大",
                "confidence": 0.78,
                "requires_human_approval": 0,
            }]
        )
        with patch("openclaw.agents.market_research.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.market_research import run_market_research
            result = run_market_research(conn=mem_db, trade_date="2026-03-02")

        assert result.action_type == "suggest"
        trace = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert trace[0] == "market_research"
        proposal = mem_db.execute("SELECT generated_by FROM strategy_proposals").fetchone()
        assert proposal[0] == "market_research"
```

**Step 2: 確認失敗**

```bash
python -m pytest src/tests/test_agents.py::TestMarketResearchAgent -v
```

**Step 3: 實作 `src/openclaw/agents/market_research.py`**

```python
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
```

**Step 4: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

**Step 5: Commit**

```bash
git add src/openclaw/agents/market_research.py src/tests/test_agents.py
git commit -m "feat: add MarketResearchAgent (Gemini-based)"
```

---

## Task 5：PortfolioReviewAgent

**Files:**
- Create: `src/openclaw/agents/portfolio_review.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestPortfolioReviewAgent:
    def test_writes_trace_on_empty_portfolio(self, mem_db):
        mock_resp = _mock_gemini("目前無持倉，無需再平衡", confidence=0.9, proposals=[])
        with patch("openclaw.agents.portfolio_review.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.portfolio_review import run_portfolio_review
            result = run_portfolio_review(conn=mem_db)
        trace = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert trace[0] == "portfolio_review"
        assert result.action_type == "observe"
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/portfolio_review.py`**

```python
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
```

**Step 3: 執行全部測試 + Commit**

```bash
python -m pytest src/tests/test_agents.py -v
git add src/openclaw/agents/portfolio_review.py src/tests/test_agents.py
git commit -m "feat: add PortfolioReviewAgent (Gemini-based)"
```

---

## Task 6：StrategyCommitteeAgent（三次序列 Gemini 呼叫）

**Files:**
- Create: `src/openclaw/agents/strategy_committee.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestStrategyCommitteeAgent:
    def test_three_llm_calls_and_proposal_requires_approval(self, mem_db):
        bull_resp = _mock_gemini("看多：半導體短期趨勢向上", confidence=0.7, action_type="suggest")
        bear_resp = _mock_gemini("看空：外資連續賣超，注意回檔", confidence=0.65, action_type="suggest")
        arbiter_resp = _mock_gemini(
            "整合評估：建議持平，不加倉",
            confidence=0.65,
            action_type="suggest",
            proposals=[{
                "target_rule": "STRATEGY_DIRECTION",
                "rule_category": "strategy",
                "proposed_value": "持平，不加倉",
                "supporting_evidence": "Bull/Bear 訊號拉鋸",
                "confidence": 0.65,
                "requires_human_approval": 1,
            }]
        )
        call_side_effects = [bull_resp, bear_resp, arbiter_resp]
        with patch("openclaw.agents.strategy_committee.call_agent_llm",
                   side_effect=call_side_effects):
            from openclaw.agents.strategy_committee import run_strategy_committee
            result = run_strategy_committee(conn=mem_db)

        # 3 次呼叫 → 3 筆 llm_traces
        count = mem_db.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 3
        # 策略提案必須 requires_human_approval=1
        proposal = mem_db.execute(
            "SELECT requires_human_approval FROM strategy_proposals"
        ).fetchone()
        assert proposal[0] == 1
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/strategy_committee.py`**

```python
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
```

**Step 3: 執行全部測試 + Commit**

```bash
python -m pytest src/tests/test_agents.py -v
git add src/openclaw/agents/strategy_committee.py src/tests/test_agents.py
git commit -m "feat: add StrategyCommitteeAgent (bull/bear/arbiter sequential Gemini calls)"
```

---

## Task 7：SystemOptimizationAgent

**Files:**
- Create: `src/openclaw/agents/system_optimization.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestSystemOptimizationAgent:
    def test_config_change_requires_approval(self, mem_db):
        mock_resp = _mock_gemini(
            "BUY_SIGNAL_PCT 建議從 0.002 提高至 0.003",
            confidence=0.7,
            action_type="config_change",
            proposals=[{
                "target_rule": "BUY_SIGNAL_PCT",
                "rule_category": "config",
                "proposed_value": "0.003",
                "supporting_evidence": "近 4 週勝率 35%",
                "confidence": 0.7,
                "requires_human_approval": 1,
            }]
        )
        with patch("openclaw.agents.system_optimization.call_agent_llm",
                   return_value=mock_resp):
            from openclaw.agents.system_optimization import run_system_optimization
            run_system_optimization(conn=mem_db)

        row = mem_db.execute(
            "SELECT target_rule, requires_human_approval FROM strategy_proposals"
        ).fetchone()
        assert row[0] == "BUY_SIGNAL_PCT"
        assert row[1] == 1

    def test_no_proposal_when_performance_ok(self, mem_db):
        mock_resp = _mock_gemini("近 4 週績效正常，無需調整", confidence=0.8,
                                  action_type="observe", proposals=[])
        with patch("openclaw.agents.system_optimization.call_agent_llm",
                   return_value=mock_resp):
            from openclaw.agents.system_optimization import run_system_optimization
            result = run_system_optimization(conn=mem_db)
        assert len(result.proposals) == 0
        count = mem_db.execute(
            "SELECT COUNT(*) FROM strategy_proposals"
        ).fetchone()[0]
        assert count == 0
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/system_optimization.py`**

```python
"""agents/system_optimization.py — 系統優化員 Agent。

執行時機：每週一 07:00，或 watcher 連續 3 日無成交時觸發
工作：Python 查近 4 週交易績效 → Gemini 評估訊號閾值是否需調整
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openclaw.agents.base import (
    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    query_db, to_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

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
```

**Step 3: 執行全部測試 + Commit**

```bash
python -m pytest src/tests/test_agents.py -v
git add src/openclaw/agents/system_optimization.py src/tests/test_agents.py
git commit -m "feat: add SystemOptimizationAgent (Gemini-based)"
```

---

## Task 8：agent_orchestrator.py（asyncio 排程 + 事件偵測）

**Files:**
- Create: `src/openclaw/agent_orchestrator.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增 Orchestrator 排程邏輯測試**

```python
class TestOrchestratorHelpers:
    def test_should_run_now_true(self):
        from datetime import timedelta
        from openclaw.agent_orchestrator import _should_run_now
        twn = timezone(timedelta(hours=8))
        t = datetime(2026, 3, 2, 8, 20, tzinfo=twn)
        assert _should_run_now("08:20", t) is True

    def test_should_run_now_false(self):
        from datetime import timedelta
        from openclaw.agent_orchestrator import _should_run_now
        twn = timezone(timedelta(hours=8))
        t = datetime(2026, 3, 2, 9, 15, tzinfo=twn)
        assert _should_run_now("08:20", t) is False

    def test_pm_review_event_detected(self, tmp_path):
        import json as _j
        from openclaw.agent_orchestrator import _pm_review_just_completed
        f = tmp_path / "state.json"
        f.write_text(_j.dumps({"reviewed_at": "2026-03-02T08:25:00"}))
        result = _pm_review_just_completed(str(f), last_seen=None)
        assert result == "2026-03-02T08:25:00"

    def test_pm_review_no_event_when_same(self, tmp_path):
        import json as _j
        from openclaw.agent_orchestrator import _pm_review_just_completed
        f = tmp_path / "state.json"
        f.write_text(_j.dumps({"reviewed_at": "2026-03-02T08:25:00"}))
        result = _pm_review_just_completed(str(f), last_seen="2026-03-02T08:25:00")
        assert result is None

    def test_watcher_no_fills_3days(self, mem_db):
        from openclaw.agent_orchestrator import _watcher_no_fills_3days
        assert _watcher_no_fills_3days(mem_db) is True  # fills table 是空的
```

**Step 2: 確認失敗**

```bash
python -m pytest src/tests/test_agents.py::TestOrchestratorHelpers -v
```

**Step 3: 實作 `src/openclaw/agent_orchestrator.py`**

```python
"""agent_orchestrator.py — 統一 Agent 排程 Orchestrator。

PM2 進程名稱：ai-trader-agents
架構：asyncio 排程器，每分鐘輪詢定時 + 事件任務
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("agent_orchestrator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = str(_REPO_ROOT / "config" / "daily_pm_state.json")
_TZ_TWN = timezone(timedelta(hours=8))
DB_PATH: str = os.environ.get("DB_PATH", str(_REPO_ROOT / "data" / "sqlite" / "trades.db"))


# ── 排程 helpers ──────────────────────────────────────────────────────────────

def _should_run_now(hhmm: str, now_twn: Optional[datetime] = None) -> bool:
    """True if 台灣當前時間 == hhmm（HH:MM）。"""
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.strftime("%H:%M") == hhmm


def _is_weekday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() < 5


def _is_monday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() == 0


# ── 事件偵測 ──────────────────────────────────────────────────────────────────

def _pm_review_just_completed(
    state_path: str = _STATE_PATH,
    last_seen: Optional[str] = None,
) -> Optional[str]:
    """回傳新的 reviewed_at，或 None（無新事件）。"""
    try:
        with open(state_path) as f:
            state = json.load(f)
        reviewed_at = state.get("reviewed_at")
        if reviewed_at and reviewed_at != last_seen:
            return reviewed_at
    except Exception:
        pass
    return None


def _watcher_no_fills_3days(conn: sqlite3.Connection) -> bool:
    """近 3 日無成交時回傳 True。"""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE ts_fill > datetime('now','-3 days')"
        ).fetchone()
        return (row[0] == 0) if row else False
    except Exception:
        return False


# ── Agent 執行包裝 ────────────────────────────────────────────────────────────

async def _run_agent(name: str, fn, *args, **kwargs) -> None:
    """隔離執行：一個 agent crash 不影響排程器。"""
    try:
        log.info("[ORCHESTRATOR] Starting %s …", name)
        await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))
        log.info("[ORCHESTRATOR] %s completed.", name)
    except Exception as e:
        log.error("[ORCHESTRATOR] %s failed: %s", name, e, exc_info=True)


# ── 主排程迴圈 ────────────────────────────────────────────────────────────────

async def run_orchestrator() -> None:
    from openclaw.agents.market_research import run_market_research
    from openclaw.agents.portfolio_review import run_portfolio_review
    from openclaw.agents.system_health import run_system_health
    from openclaw.agents.strategy_committee import run_strategy_committee
    from openclaw.agents.system_optimization import run_system_optimization

    log.info("Agent Orchestrator started | DB=%s", DB_PATH)

    last_pm_reviewed_at: Optional[str] = None
    last_health_run_utc: Optional[datetime] = None
    last_health_off_utc: Optional[datetime] = None
    last_opt_trigger_date: Optional[str] = None

    while True:
        now_twn = datetime.now(tz=_TZ_TWN)
        now_utc = datetime.now(tz=timezone.utc)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            # ── 定時任務 ──────────────────────────────────────────────────
            if _is_weekday_twn(now_twn):
                if _should_run_now("08:20", now_twn):
                    asyncio.create_task(_run_agent("MarketResearchAgent", run_market_research))

                if _should_run_now("14:30", now_twn):
                    asyncio.create_task(_run_agent("PortfolioReviewAgent", run_portfolio_review))

                # 每 30 分鐘系統健康（市場時段）
                if 9 <= now_twn.hour < 14:
                    if (last_health_run_utc is None or
                            (now_utc - last_health_run_utc).seconds >= 1800):
                        asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                        last_health_run_utc = now_utc

            # 每 2 小時系統健康（非市場時段）
            if not (9 <= now_twn.hour < 14):
                if (last_health_off_utc is None or
                        (now_utc - last_health_off_utc).seconds >= 7200):
                    asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                    last_health_off_utc = now_utc

            if _is_monday_twn(now_twn):
                if _should_run_now("07:00", now_twn):
                    asyncio.create_task(
                        _run_agent("SystemOptimizationAgent", run_system_optimization))
                if _should_run_now("07:30", now_twn):
                    asyncio.create_task(
                        _run_agent("StrategyCommitteeAgent", run_strategy_committee))

            # ── 事件任務 ──────────────────────────────────────────────────
            new_reviewed_at = _pm_review_just_completed(last_seen=last_pm_reviewed_at)
            if new_reviewed_at:
                log.info("[EVENT] PM review completed → StrategyCommitteeAgent")
                last_pm_reviewed_at = new_reviewed_at
                asyncio.create_task(
                    _run_agent("StrategyCommitteeAgent", run_strategy_committee))

            today_str = now_twn.strftime("%Y-%m-%d")
            if last_opt_trigger_date != today_str and _watcher_no_fills_3days(conn):
                log.info("[EVENT] 3-day no fills → SystemOptimizationAgent")
                last_opt_trigger_date = today_str
                asyncio.create_task(
                    _run_agent("SystemOptimizationAgent", run_system_optimization))

        except Exception as e:
            log.error("[ORCHESTRATOR] Main loop error: %s", e, exc_info=True)
        finally:
            conn.close()

        await asyncio.sleep(60)


def main() -> None:
    asyncio.run(run_orchestrator())


if __name__ == "__main__":
    main()
```

**Step 4: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS

**Step 5: Commit**

```bash
git add src/openclaw/agent_orchestrator.py src/tests/test_agents.py
git commit -m "feat: add agent_orchestrator.py with asyncio scheduler + event detection"
```

---

## Task 9：PM2 設定更新 + 最終驗收

**Files:**
- Modify: `ecosystem.config.js`
- Modify: `CLAUDE.md`

**Step 1: 查看 ecosystem.config.js 現有 cwd 路徑**

```bash
grep -n "cwd\|script\|name" ecosystem.config.js | head -20
```

**Step 2: 新增 ai-trader-agents 進程**

在 `ecosystem.config.js` 的 `apps` 陣列中加入（cwd 與其他進程保持一致）：

```javascript
{
  name: "ai-trader-agents",
  script: "src/openclaw/agent_orchestrator.py",
  interpreter: "python3",
  cwd: "<與其他進程相同的 cwd>",
  env_file: "frontend/backend/.env",
  autorestart: true,
  restart_delay: 10000,
  max_restarts: 5,
},
```

**Step 3: 執行完整測試套件**

```bash
python -m pytest src/tests/ --tb=short 2>&1 | tail -5
```

Expected: `XXX passed`（原 168 + 新增約 20 個）

**Step 4: 更新 CLAUDE.md**

在「核心引擎關鍵檔案」段落加入：

```
| `src/openclaw/agents/`    | Agent 角色模組（市場研究/Portfolio/健康監控/策略小組/優化）|
| `agent_orchestrator.py`   | Agent 統一排程 Orchestrator（PM2: ai-trader-agents） |
```

在 PM2 服務段落加入：

```
| ai-trader-agents | agent_orchestrator.py | 5 個 Gemini agent 角色排程 |
```

**Step 5: 最終 commit + push**

```bash
git add ecosystem.config.js CLAUDE.md
git commit -m "feat: complete agent roles v4.9.0 — 5 Gemini-based agents + orchestrator"
git push origin main
```

---

## 驗收標準

- [ ] `python -m pytest src/tests/` 全數通過（≥ 185 tests）
- [ ] `python3 -c "from openclaw.agents.base import write_trace; print('ok')"` 成功
- [ ] `python3 -c "from openclaw.agent_orchestrator import _should_run_now; print('ok')"` 成功
- [ ] `pm2 start ecosystem.config.js --only ai-trader-agents` 成功啟動
- [ ] 前端 LogTerminal 可看到 `agent='system_health'` 的 trace

---

## 注意事項

1. **GEMINI_API_KEY**：`frontend/backend/.env` 必須有此設定（現有系統應已存在）。
2. **`_REPO_ROOT` 路徑驗證**：`base.py` 中 `parents[3]`（`agents/` → `openclaw/` → `src/` → repo root），實作後執行 `python3 -c "from openclaw.agents.base import _REPO_ROOT; print(_REPO_ROOT)"` 確認路徑正確。
3. **StrategyCommittee 費用**：使用 `gemini-3.1-pro`，每次執行 3 次呼叫，成本較高，建議保持每週一 + 事件觸發頻率。
4. **mock 測試不呼叫真實 API**：所有單元測試 mock `call_agent_llm`，CI 不需要 API key。
5. **gemini_call 要求 JSON 回應**：已在 `llm_gemini.py` 設定 `response_mime_type: application/json`，prompt 中的輸出格式說明僅作為 schema 引導。
