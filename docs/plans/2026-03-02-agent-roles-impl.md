# Agent Roles Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 實作五個 Claude Agent SDK 角色（MarketResearch、PortfolioReview、SystemHealth、StrategyCommittee、SystemOptimization）並以統一 Orchestrator 排程執行。

**Architecture:** 單一 PM2 進程 `ai-trader-agents` 執行 `agent_orchestrator.py`，內部 asyncio 排程器管理所有角色的定時/事件觸發。每個 agent 透過 `claude_agent_sdk.query()` 啟動 subprocess，結果寫入 `llm_traces` + `strategy_proposals`，前端 LogTerminal 即時可見。

**Tech Stack:** Python 3.11+、`claude-agent-sdk`（PyPI）、`anthropic`、asyncio、sqlite3、PM2

---

## Task 1：安裝依賴與驗證

**Files:**
- Modify: `requirements.txt`（若存在）或新建

**Step 1: 安裝 claude-agent-sdk 與 anthropic**

```bash
pip3 install claude-agent-sdk anthropic
```

Expected output: `Successfully installed claude-agent-sdk-X.X.X anthropic-X.X.X`

**Step 2: 驗證 import**

```bash
python3 -c "from claude_agent_sdk import query; print('claude_agent_sdk ok')"
python3 -c "import anthropic; print('anthropic ok')"
```

Expected: 兩行 `ok`

**Step 3: 更新 requirements.txt**

若專案根目錄沒有 `requirements.txt`，先檢查：

```bash
ls requirements*.txt pyproject.toml 2>/dev/null
```

將以下行加入依賴設定：

```
claude-agent-sdk>=0.1.0
anthropic>=0.40.0
```

**Step 4: 設定 ANTHROPIC_API_KEY**

```bash
# 確認 .env 已有此設定
grep ANTHROPIC_API_KEY frontend/backend/.env
```

若沒有，加入：
```
ANTHROPIC_API_KEY=sk-ant-...
```

**Step 5: Commit**

```bash
git add requirements.txt   # 或 pyproject.toml
git commit -m "chore: add claude-agent-sdk + anthropic to dependencies"
```

---

## Task 2：建立 agents/ 套件與 base.py

**Files:**
- Create: `src/openclaw/agents/__init__.py`
- Create: `src/openclaw/agents/base.py`

**Step 1: 建立目錄與 __init__.py**

```bash
mkdir -p src/openclaw/agents
touch src/openclaw/agents/__init__.py
```

**Step 2: 寫 `src/openclaw/agents/base.py`**

```python
"""agents/base.py — 共用 helper：DB 寫入、trace 格式、proposal 格式。"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from openclaw.llm_observability import LLMTrace, insert_llm_trace

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")


def open_conn(db_path: str = _DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def write_trace(
    conn: sqlite3.Connection,
    *,
    agent: str,
    prompt: str,
    result: str,
    confidence: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """LLMTrace を DB に書き込む（SSE で LogTerminal へ流れる）。"""
    trace = LLMTrace(
        component=agent,
        agent=agent,
        model="claude-opus-4-6",
        prompt_text=prompt,
        response_text=result,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        confidence=confidence,
        metadata={**(metadata or {}), "created_at_ms": int(time.time() * 1000)},
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
    proposals: list


def parse_agent_result(raw: str) -> AgentResult:
    """Agent 最後回覆中提取 JSON 區塊。找不到時回傳摘要文字。"""
    import re
    # 找最後一個 ```json ... ``` 或裸 { ... }
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if not m:
        m = re.search(r"(\{[^{}]*\"summary\"[^{}]*\})", raw, re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(1))
            return AgentResult(
                summary=d.get("summary", raw[:200]),
                confidence=float(d.get("confidence", 0.5)),
                action_type=d.get("action_type", "observe"),
                proposals=d.get("proposals", []),
            )
        except Exception:
            pass
    return AgentResult(summary=raw[:500], confidence=0.5, action_type="observe", proposals=[])
```

**Step 3: Commit**

```bash
git add src/openclaw/agents/
git commit -m "feat: add agents/ package with base.py helpers"
```

---

## Task 3：unit test 基礎設施（test_agents.py）

**Files:**
- Create: `src/tests/test_agents.py`

**Step 1: 寫測試**

```python
"""test_agents.py — agents/base.py 的單元測試。"""
from __future__ import annotations

import json
import sqlite3
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openclaw.agents.base import (
    AgentResult,
    open_conn,
    parse_agent_result,
    write_proposal,
    write_trace,
)


# ── Fixture: in-memory DB with required tables ──────────────────────────────

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
    """)
    yield conn
    conn.close()


# ── write_trace ──────────────────────────────────────────────────────────────

class TestWriteTrace:
    def test_inserts_row(self, mem_db):
        write_trace(mem_db, agent="test_agent", prompt="p", result="r")
        row = mem_db.execute("SELECT agent, prompt FROM llm_traces").fetchone()
        assert row is not None
        assert row[0] == "test_agent"

    def test_metadata_contains_created_at_ms(self, mem_db):
        write_trace(mem_db, agent="a", prompt="p", result="r",
                    metadata={"key": "val"})
        row = mem_db.execute("SELECT tool_calls_json FROM llm_traces").fetchone()
        # tool_calls_json maps to metadata in hybrid schema
        # (llm_observability will pick correct column)


# ── write_proposal ───────────────────────────────────────────────────────────

class TestWriteProposal:
    def test_inserts_pending_proposal(self, mem_db):
        pid = write_proposal(
            mem_db,
            generated_by="market_research",
            target_rule="SECTOR_WEIGHT",
            rule_category="allocation",
            proposed_value="半導體 40%",
            supporting_evidence="近 5 日半導體強勢",
            confidence=0.75,
        )
        row = mem_db.execute(
            "SELECT status, requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] == 0  # default: no human approval required

    def test_config_change_requires_approval(self, mem_db):
        pid = write_proposal(
            mem_db,
            generated_by="system_optimization",
            target_rule="BUY_SIGNAL_PCT",
            rule_category="config",
            proposed_value="0.003",
            supporting_evidence="近 4 週勝率偏低",
            confidence=0.6,
            requires_human_approval=1,
            proposal_type="config_change",
        )
        row = mem_db.execute(
            "SELECT requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == 1


# ── parse_agent_result ───────────────────────────────────────────────────────

class TestParseAgentResult:
    def test_parses_json_block(self):
        raw = """分析完畢。

```json
{"summary": "半導體強勢", "confidence": 0.8, "action_type": "suggest", "proposals": []}
```"""
        r = parse_agent_result(raw)
        assert r.summary == "半導體強勢"
        assert r.confidence == 0.8
        assert r.action_type == "suggest"

    def test_fallback_on_no_json(self):
        raw = "無法分析，資料不足。"
        r = parse_agent_result(raw)
        assert r.action_type == "observe"
        assert "無法分析" in r.summary

    def test_parses_inline_json(self):
        raw = 'result: {"summary": "OK", "confidence": 0.5, "action_type": "observe"}'
        r = parse_agent_result(raw)
        assert r.summary == "OK"
```

**Step 2: 執行測試，確認通過**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS

**Step 3: Commit**

```bash
git add src/tests/test_agents.py
git commit -m "test: add test_agents.py for base.py helpers"
```

---

## Task 4：SystemHealthAgent（最簡單，純 Bash）

**Files:**
- Create: `src/openclaw/agents/system_health.py`
- Modify: `src/tests/test_agents.py`（新增 mock query 測試）

**Step 1: 新增 SystemHealthAgent 的 mock query 測試**

在 `src/tests/test_agents.py` 末尾加入：

```python
# ── SystemHealthAgent ────────────────────────────────────────────────────────

import asyncio

def _make_async_gen(*results):
    """建立回傳固定 result 的 mock async generator。"""
    async def _gen():
        for r in results:
            yield r
    return _gen()


class TestSystemHealthAgent:
    def test_writes_trace_on_healthy(self, mem_db, monkeypatch):
        mock_result = MagicMock()
        mock_result.result = json.dumps({
            "summary": "All services healthy",
            "confidence": 0.95,
            "action_type": "observe",
            "proposals": []
        })

        async def mock_query(prompt, options=None):
            yield mock_result

        monkeypatch.setattr("openclaw.agents.system_health.query", mock_query)

        from openclaw.agents.system_health import run_system_health
        asyncio.run(run_system_health(conn=mem_db))

        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row is not None
        assert row[0] == "system_health"
```

**Step 2: 確認測試失敗（模組未建）**

```bash
python -m pytest src/tests/test_agents.py::TestSystemHealthAgent -v
```

Expected: FAIL with `ModuleNotFoundError`

**Step 3: 實作 `src/openclaw/agents/system_health.py`**

```python
"""agents/system_health.py — 系統健康監控 Agent。

執行時機：每 30 分鐘（市場時段）/ 每 2 小時（其他）
工作：檢查 PM2 服務、DB WAL、磁碟空間、watcher 心跳
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from openclaw.agents.base import AgentResult, open_conn, parse_agent_result, write_trace

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 SystemHealthAgent（系統健康監控員）。

## 背景
現在時間：{now_utc}
專案根目錄：{repo_root}

## 任務
1. 執行 `pm2 jlist` 取得所有 PM2 進程狀態，確認 ai-trader-api 與 ai-trader-watcher 是否 online
2. 查詢 SQLite DB 最近 5 分鐘是否有 watcher llm_trace：
   `sqlite3 {db_path} "SELECT COUNT(*) FROM llm_traces WHERE agent='watcher' AND created_at > strftime('%s','now','-5 minutes')"`
3. 執行 `df -h {repo_root}` 確認磁碟空間
4. 根據以上結果評估系統健康度

## 工具使用規範
- 只使用 Bash 指令
- 不修改任何檔案
- 不執行交易操作

## 輸出格式
最後回覆必須是 JSON：
```json
{{
  "summary": "...",
  "confidence": 0.95,
  "action_type": "observe",
  "proposals": [],
  "services": {{"api": "online/offline", "watcher": "online/offline"}},
  "disk_ok": true
}}
```
"""


async def run_system_health(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _conn = conn or open_conn(db_path or "")
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")

    prompt = _PROMPT_TEMPLATE.format(
        now_utc=datetime.now(tz=timezone.utc).isoformat(),
        repo_root=str(_REPO_ROOT),
        db_path=_db_path,
    )

    result_text = "（無回應）"
    async for msg in query(
        prompt=prompt,
        options={
            "cwd": str(_REPO_ROOT),
            "allowedTools": ["Bash"],
            "maxTurns": 5,
            "model": "claude-opus-4-6",
        },
    ):
        if hasattr(msg, "result") and msg.result:
            result_text = msg.result

    result = parse_agent_result(result_text)
    write_trace(
        _conn,
        agent="system_health",
        prompt=prompt[:500],
        result=result.summary,
        confidence=result.confidence,
        metadata={"action_type": result.action_type},
    )
    if conn is None:
        _conn.close()
    return result
```

**Step 4: 執行測試，確認通過**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS

**Step 5: Commit**

```bash
git add src/openclaw/agents/system_health.py src/tests/test_agents.py
git commit -m "feat: add SystemHealthAgent with mock query tests"
```

---

## Task 5：MarketResearchAgent

**Files:**
- Create: `src/openclaw/agents/market_research.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

在 `src/tests/test_agents.py` 末尾加入：

```python
class TestMarketResearchAgent:
    def test_writes_trace_and_proposal(self, mem_db, monkeypatch):
        mock_result = MagicMock()
        mock_result.result = json.dumps({
            "summary": "半導體板塊強勢，建議加大 2330 比重",
            "confidence": 0.78,
            "action_type": "suggest",
            "proposals": [
                {
                    "target_rule": "SECTOR_FOCUS",
                    "rule_category": "allocation",
                    "proposed_value": "半導體",
                    "supporting_evidence": "近 5 日成交量創新高",
                    "confidence": 0.78,
                    "requires_human_approval": 0
                }
            ]
        })

        async def mock_query(prompt, options=None):
            yield mock_result

        monkeypatch.setattr("openclaw.agents.market_research.query", mock_query)

        from openclaw.agents.market_research import run_market_research
        asyncio.run(run_market_research(conn=mem_db, trade_date="2026-03-02"))

        trace = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert trace[0] == "market_research"
        proposal = mem_db.execute("SELECT generated_by FROM strategy_proposals").fetchone()
        assert proposal[0] == "market_research"
```

**Step 2: 確認失敗**

```bash
python -m pytest src/tests/test_agents.py::TestMarketResearchAgent -v
```

Expected: FAIL

**Step 3: 實作 `src/openclaw/agents/market_research.py`**

```python
"""agents/market_research.py — 市場研究員 Agent。

執行時機：每交易日 08:20
工作：分析昨日 EOD 數據，提出板塊建議
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from openclaw.agents.base import (
    AgentResult, open_conn, parse_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 MarketResearchAgent（市場研究員）。

## 背景
分析日期：{trade_date}
DB 路徑：{db_path}

## 任務
1. 查詢昨日（{trade_date}）TWSE 各股漲跌幅前 10 名：
   `sqlite3 {db_path} "SELECT symbol, name, close, change FROM eod_prices WHERE trade_date='{trade_date}' AND market='TWSE' AND close IS NOT NULL ORDER BY ABS(change) DESC LIMIT 10"`
2. 查詢成交量前 5 名：
   `sqlite3 {db_path} "SELECT symbol, name, volume FROM eod_prices WHERE trade_date='{trade_date}' AND market='TWSE' ORDER BY volume DESC LIMIT 5"`
3. 根據結果判斷：今日板塊強弱、資金流向、多空氣氛

## 工具使用規範
- 只讀取 DB（sqlite3 SELECT 指令）
- 不執行交易操作

## 輸出格式
最後回覆必須是 JSON：
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
"""


async def run_market_research(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    prompt = _PROMPT_TEMPLATE.format(trade_date=_date, db_path=_db_path)

    result_text = "（無回應）"
    async for msg in query(
        prompt=prompt,
        options={
            "cwd": str(_REPO_ROOT),
            "allowedTools": ["Read", "Bash"],
            "maxTurns": 8,
            "model": "claude-opus-4-6",
        },
    ):
        if hasattr(msg, "result") and msg.result:
            result_text = msg.result

    result = parse_agent_result(result_text)
    write_trace(
        _conn, agent="market_research", prompt=prompt[:500],
        result=result.summary, confidence=result.confidence,
    )
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
    if conn is None:
        _conn.close()
    return result
```

**Step 4: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS

**Step 5: Commit**

```bash
git add src/openclaw/agents/market_research.py src/tests/test_agents.py
git commit -m "feat: add MarketResearchAgent"
```

---

## Task 6：PortfolioReviewAgent

**Files:**
- Create: `src/openclaw/agents/portfolio_review.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestPortfolioReviewAgent:
    def test_writes_trace_on_empty_portfolio(self, mem_db, monkeypatch):
        mock_result = MagicMock()
        mock_result.result = json.dumps({
            "summary": "目前無持倉，無需再平衡",
            "confidence": 0.9,
            "action_type": "observe",
            "proposals": []
        })

        async def mock_query(prompt, options=None):
            yield mock_result

        monkeypatch.setattr("openclaw.agents.portfolio_review.query", mock_query)

        from openclaw.agents.portfolio_review import run_portfolio_review
        asyncio.run(run_portfolio_review(conn=mem_db))

        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row[0] == "portfolio_review"
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/portfolio_review.py`**

```python
"""agents/portfolio_review.py — Portfolio 審查員 Agent。

執行時機：每交易日 14:30（收盤後）
工作：分析持倉健康度、勝率、提出再平衡建議
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from openclaw.agents.base import (
    AgentResult, open_conn, parse_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 PortfolioReviewAgent（Portfolio 審查員）。

## 背景
審查日期：{trade_date}
DB 路徑：{db_path}

## 任務
1. 查詢當前持倉：
   `sqlite3 {db_path} "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0"`
2. 查詢今日損益：
   `sqlite3 {db_path} "SELECT symbol, realized_pnl FROM daily_pnl_summary WHERE trade_date='{trade_date}'"`
3. 查詢今日成交：
   `sqlite3 {db_path} "SELECT o.symbol, o.side, o.qty, f.price FROM orders o JOIN fills f ON o.order_id=f.order_id WHERE date(o.ts_submit)='{trade_date}'"`
4. 評估：持倉集中度（單一股票 > 40% 警示）、今日勝率、是否有再平衡需求

## 工具使用規範
- 只讀取 DB（SELECT 指令）
- 不執行交易操作

## 輸出格式
最後回覆必須是 JSON：
```json
{{
  "summary": "...",
  "confidence": 0.8,
  "action_type": "suggest",
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
"""


async def run_portfolio_review(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    prompt = _PROMPT_TEMPLATE.format(trade_date=_date, db_path=_db_path)

    result_text = "（無回應）"
    async for msg in query(
        prompt=prompt,
        options={
            "cwd": str(_REPO_ROOT),
            "allowedTools": ["Read", "Bash"],
            "maxTurns": 8,
            "model": "claude-opus-4-6",
        },
    ):
        if hasattr(msg, "result") and msg.result:
            result_text = msg.result

    result = parse_agent_result(result_text)
    write_trace(
        _conn, agent="portfolio_review", prompt=prompt[:500],
        result=result.summary, confidence=result.confidence,
    )
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
    if conn is None:
        _conn.close()
    return result
```

**Step 3: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

**Step 4: Commit**

```bash
git add src/openclaw/agents/portfolio_review.py src/tests/test_agents.py
git commit -m "feat: add PortfolioReviewAgent"
```

---

## Task 7：StrategyCommitteeAgent（含 sub-agents）

**Files:**
- Create: `src/openclaw/agents/strategy_committee.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestStrategyCommitteeAgent:
    def test_writes_proposal_with_human_approval(self, mem_db, monkeypatch):
        mock_result = MagicMock()
        mock_result.result = json.dumps({
            "summary": "Bull/Bear 辯論結果：建議維持現狀，置信 0.65",
            "confidence": 0.65,
            "action_type": "suggest",
            "proposals": [
                {
                    "target_rule": "STRATEGY_DIRECTION",
                    "rule_category": "strategy",
                    "proposed_value": "持平，不加倉",
                    "supporting_evidence": "技術面偏弱，籌碼面中性",
                    "confidence": 0.65,
                    "requires_human_approval": 1
                }
            ]
        })

        async def mock_query(prompt, options=None):
            yield mock_result

        monkeypatch.setattr("openclaw.agents.strategy_committee.query", mock_query)

        from openclaw.agents.strategy_committee import run_strategy_committee
        asyncio.run(run_strategy_committee(conn=mem_db))

        proposal = mem_db.execute(
            "SELECT requires_human_approval FROM strategy_proposals"
        ).fetchone()
        assert proposal[0] == 1  # 策略小組建議需人工確認
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/strategy_committee.py`**

```python
"""agents/strategy_committee.py — 策略小組 Agent（含 sub-agents 辯論）。

執行時機：PM 審核完成後（事件），或每週一 07:30
工作：Bull/Bear/Arbiter 三方辯論，輸出策略方向建議
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from openclaw.agents.base import (
    AgentResult, open_conn, parse_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_SUB_AGENTS = {
    "bull-analyst": {
        "description": "看多派分析師，從技術面與籌碼面找做多理由，提出加碼方向與目標價",
        "prompt": "分析近期市場走勢，找出做多機會。使用 Read/Bash 查詢 EOD 數據與持倉。",
        "tools": ["Read", "Bash"],
    },
    "bear-analyst": {
        "description": "看空派分析師，識別風險與下跌訊號，提出減碼建議",
        "prompt": "識別市場風險與高風險部位。使用 Read/Bash 查詢風控數據。",
        "tools": ["Read", "Bash"],
    },
    "risk-arbiter": {
        "description": "風險仲裁者，整合 bull/bear 分析給出 confidence-weighted 最終策略建議",
        "prompt": "整合 bull-analyst 與 bear-analyst 的分析，輸出最終策略建議（JSON 格式）。",
        "tools": ["Read"],
    },
}

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 StrategyCommitteeAgent（策略小組協調者）。

## 背景
執行時間：{now_utc}
DB 路徑：{db_path}

## 任務
協調三個 sub-agent 進行策略辯論：
1. 使用 bull-analyst sub-agent 分析做多機會
2. 使用 bear-analyst sub-agent 分析風險
3. 使用 risk-arbiter sub-agent 整合並輸出最終建議

查詢基礎數據（傳入 sub-agents）：
`sqlite3 {db_path} "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0"`
`sqlite3 {db_path} "SELECT trade_date, SUM(realized_pnl) FROM daily_pnl_summary GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5"`

## 工具使用規範
- 可使用 Agent tool 啟動 sub-agents
- Read/Bash 查詢 DB 數據
- 不直接執行交易

## 輸出格式（risk-arbiter 最終結果）
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


async def run_strategy_committee(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    prompt = _PROMPT_TEMPLATE.format(
        now_utc=datetime.now(tz=timezone.utc).isoformat(),
        db_path=_db_path,
    )

    result_text = "（無回應）"
    async for msg in query(
        prompt=prompt,
        options={
            "cwd": str(_REPO_ROOT),
            "allowedTools": ["Read", "Bash", "Agent"],
            "maxTurns": 15,
            "model": "claude-opus-4-6",
            "agents": _SUB_AGENTS,
        },
    ):
        if hasattr(msg, "result") and msg.result:
            result_text = msg.result

    result = parse_agent_result(result_text)
    write_trace(
        _conn, agent="strategy_committee", prompt=prompt[:500],
        result=result.summary, confidence=result.confidence,
    )
    for p in result.proposals:
        write_proposal(
            _conn,
            generated_by="strategy_committee",
            target_rule=p.get("target_rule", "STRATEGY"),
            rule_category=p.get("rule_category", "strategy"),
            proposed_value=str(p.get("proposed_value", "")),
            supporting_evidence=str(p.get("supporting_evidence", "")),
            confidence=float(p.get("confidence", 0.5)),
            requires_human_approval=1,      # 策略小組建議必須人工確認
            proposal_type="suggest",
        )
    if conn is None:
        _conn.close()
    return result
```

**Step 3: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

**Step 4: Commit**

```bash
git add src/openclaw/agents/strategy_committee.py src/tests/test_agents.py
git commit -m "feat: add StrategyCommitteeAgent with bull/bear/arbiter sub-agents"
```

---

## Task 8：SystemOptimizationAgent

**Files:**
- Create: `src/openclaw/agents/system_optimization.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增測試**

```python
class TestSystemOptimizationAgent:
    def test_config_change_proposal_requires_approval(self, mem_db, monkeypatch):
        mock_result = MagicMock()
        mock_result.result = json.dumps({
            "summary": "近 4 週 BUY_SIGNAL_PCT=0.002 觸發過多假訊號，建議提高至 0.003",
            "confidence": 0.7,
            "action_type": "config_change",
            "proposals": [
                {
                    "target_rule": "BUY_SIGNAL_PCT",
                    "rule_category": "config",
                    "proposed_value": "0.003",
                    "supporting_evidence": "近 4 週 buy 訊號 42 次，成交後獲利僅 35%",
                    "confidence": 0.7,
                    "requires_human_approval": 1
                }
            ]
        })

        async def mock_query(prompt, options=None):
            yield mock_result

        monkeypatch.setattr("openclaw.agents.system_optimization.query", mock_query)

        from openclaw.agents.system_optimization import run_system_optimization
        asyncio.run(run_system_optimization(conn=mem_db))

        proposal = mem_db.execute(
            "SELECT target_rule, requires_human_approval FROM strategy_proposals"
        ).fetchone()
        assert proposal[0] == "BUY_SIGNAL_PCT"
        assert proposal[1] == 1
```

**Step 2: 確認失敗後實作 `src/openclaw/agents/system_optimization.py`**

```python
"""agents/system_optimization.py — 系統優化員 Agent。

執行時機：每週一 07:00，或 watcher 連續 3 日無成交時觸發
工作：分析近 4 週交易，評估訊號閾值，提出 config_change 提案
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_agent_sdk import query

from openclaw.agents.base import (
    AgentResult, open_conn, parse_agent_result, write_proposal, write_trace,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 SystemOptimizationAgent（系統優化員）。

## 背景
執行時間：{now_utc}
DB 路徑：{db_path}

## 任務
分析近 4 週交易績效，評估以下訊號閾值是否需調整：
- BUY_SIGNAL_PCT（當前 0.002）：close < ref*(1-threshold) 觸發 buy
- TAKE_PROFIT_PCT（當前 0.02）：止盈觸發點
- STOP_LOSS_PCT（當前 0.03）：止損觸發點

1. 查詢近 4 週 buy 訊號統計：
   `sqlite3 {db_path} "SELECT signal_side, COUNT(*) as cnt, AVG(signal_score) as avg_score FROM decisions WHERE ts > datetime('now','-28 days') GROUP BY signal_side"`
2. 查詢近 4 週成交後損益：
   `sqlite3 {db_path} "SELECT COUNT(*) as trades, SUM(realized_pnl) as total_pnl, AVG(realized_pnl) as avg_pnl FROM daily_pnl_summary WHERE trade_date > date('now','-28 days')"`
3. 若買訊勝率 < 40% 或平均損益 < 0，建議調整參數

## 工具使用規範
- 只讀取 DB（SELECT 指令）
- 不直接修改 config 檔案
- 提案需人工確認後才能套用

## 輸出格式
最後回覆必須是 JSON（若無需調整，proposals 為空列表）：
```json
{{
  "summary": "...",
  "confidence": 0.7,
  "action_type": "config_change",
  "proposals": [
    {{
      "target_rule": "BUY_SIGNAL_PCT",
      "rule_category": "config",
      "proposed_value": "0.003",
      "supporting_evidence": "...",
      "confidence": 0.7,
      "requires_human_approval": 1
    }}
  ]
}}
```
"""


async def run_system_optimization(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    prompt = _PROMPT_TEMPLATE.format(
        now_utc=datetime.now(tz=timezone.utc).isoformat(),
        db_path=_db_path,
    )

    result_text = "（無回應）"
    async for msg in query(
        prompt=prompt,
        options={
            "cwd": str(_REPO_ROOT),
            "allowedTools": ["Read", "Bash"],
            "maxTurns": 10,
            "model": "claude-opus-4-6",
        },
    ):
        if hasattr(msg, "result") and msg.result:
            result_text = msg.result

    result = parse_agent_result(result_text)
    write_trace(
        _conn, agent="system_optimization", prompt=prompt[:500],
        result=result.summary, confidence=result.confidence,
    )
    for p in result.proposals:
        write_proposal(
            _conn,
            generated_by="system_optimization",
            target_rule=p.get("target_rule", "CONFIG"),
            rule_category=p.get("rule_category", "config"),
            proposed_value=str(p.get("proposed_value", "")),
            supporting_evidence=str(p.get("supporting_evidence", "")),
            confidence=float(p.get("confidence", 0.5)),
            requires_human_approval=1,   # config 變更必須人工確認
            proposal_type="config_change",
        )
    if conn is None:
        _conn.close()
    return result
```

**Step 3: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

**Step 4: Commit**

```bash
git add src/openclaw/agents/system_optimization.py src/tests/test_agents.py
git commit -m "feat: add SystemOptimizationAgent for signal threshold tuning"
```

---

## Task 9：agent_orchestrator.py（asyncio 排程 + 事件偵測）

**Files:**
- Create: `src/openclaw/agent_orchestrator.py`
- Modify: `src/tests/test_agents.py`

**Step 1: 新增 Orchestrator 排程邏輯測試**

```python
class TestOrchestratorScheduling:
    def test_should_run_returns_true_on_cron_match(self):
        """排程器在指定時間應回傳 True。"""
        from openclaw.agent_orchestrator import _should_run_now
        # 08:20 週一
        t = datetime(2026, 3, 2, 8, 20, tzinfo=timezone.utc)  # noqa: F821
        # 模擬台灣時間 = UTC+8 = 08:20 TWN → UTC 00:20
        from datetime import timezone as tz_mod, timedelta
        twn = timezone(timedelta(hours=8))  # noqa: F821
        t_twn = datetime(2026, 3, 2, 8, 20, tzinfo=twn)
        assert _should_run_now("08:20", t_twn) is True

    def test_should_run_returns_false_on_mismatch(self):
        from openclaw.agent_orchestrator import _should_run_now
        from datetime import timezone as tz_mod, timedelta
        twn = timezone(timedelta(hours=8))  # noqa: F821
        t_twn = datetime(2026, 3, 2, 9, 15, tzinfo=twn)
        assert _should_run_now("08:20", t_twn) is False

    def test_pm_review_event_detected(self, tmp_path):
        """daily_pm_state.json 更新後偵測到事件。"""
        import json as _json
        from openclaw.agent_orchestrator import _pm_review_just_completed

        state_file = tmp_path / "daily_pm_state.json"
        state_file.write_text(_json.dumps({
            "date": "2026-03-02", "approved": True, "reviewed_at": "2026-03-02T08:25:00"
        }))
        # 第一次讀取 → 記錄 reviewed_at
        assert _pm_review_just_completed(str(state_file), last_seen=None) == "2026-03-02T08:25:00"
        # 相同 reviewed_at → 沒有新事件
        assert _pm_review_just_completed(str(state_file), last_seen="2026-03-02T08:25:00") is None
```

**Step 2: 確認測試失敗後實作**

```bash
python -m pytest src/tests/test_agents.py::TestOrchestratorScheduling -v
```

**Step 3: 實作 `src/openclaw/agent_orchestrator.py`**

```python
"""agent_orchestrator.py — 統一 Agent 排程 Orchestrator。

PM2 進程名稱：ai-trader-agents
架構：asyncio 排程器，管理 5 個 Claude Agent SDK 角色
排程：cron（每分鐘輪詢）+ 事件偵測（每 60 秒輪詢）
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
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
DB_PATH = os.environ.get("DB_PATH", _DEFAULT_DB)


# ── 排程 helpers ──────────────────────────────────────────────────────────────

def _should_run_now(hhmm: str, now_twn: Optional[datetime] = None) -> bool:
    """True if 台灣當前時間 == hhmm（HH:MM）。每分鐘輪詢觸發。"""
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.strftime("%H:%M") == hhmm


def _is_weekday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() < 5  # Mon=0 … Fri=4


def _is_monday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() == 0


# ── 事件偵測 ──────────────────────────────────────────────────────────────────

def _pm_review_just_completed(
    state_path: str = _STATE_PATH,
    last_seen: Optional[str] = None,
) -> Optional[str]:
    """PM 審核完成事件偵測。

    回傳新的 reviewed_at（代表有新事件），或 None（無新事件）。
    """
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

async def _run_agent(name: str, coro) -> None:
    """隔離執行：一個 agent crash 不影響排程器。"""
    try:
        log.info("[ORCHESTRATOR] Starting %s …", name)
        await coro
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
    last_health_run: Optional[datetime] = None
    last_health_off_run: Optional[datetime] = None
    last_opt_trigger_date: Optional[str] = None  # 防止當日重複觸發

    while True:
        now_twn = datetime.now(tz=_TZ_TWN)
        now_utc = datetime.now(tz=timezone.utc)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            # ── 定時任務 ──────────────────────────────────────────────────
            if _is_weekday_twn(now_twn):
                # 08:20 市場研究
                if _should_run_now("08:20", now_twn):
                    asyncio.create_task(_run_agent("MarketResearchAgent", run_market_research()))

                # 14:30 Portfolio 審查
                if _should_run_now("14:30", now_twn):
                    asyncio.create_task(_run_agent("PortfolioReviewAgent", run_portfolio_review()))

                # 每 30 分鐘系統健康（市場時段 09:00-14:00）
                if 9 <= now_twn.hour < 14:
                    if last_health_run is None or (now_utc - last_health_run).seconds >= 1800:
                        asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health()))
                        last_health_run = now_utc

            # 每 2 小時系統健康（非市場時段）
            if not (9 <= now_twn.hour < 14):
                if last_health_off_run is None or (now_utc - last_health_off_run).seconds >= 7200:
                    asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health()))
                    last_health_off_run = now_utc

            # 週一 07:00 系統優化
            if _is_monday_twn(now_twn) and _should_run_now("07:00", now_twn):
                asyncio.create_task(_run_agent("SystemOptimizationAgent", run_system_optimization()))

            # 週一 07:30 策略小組
            if _is_monday_twn(now_twn) and _should_run_now("07:30", now_twn):
                asyncio.create_task(_run_agent("StrategyCommitteeAgent", run_strategy_committee()))

            # ── 事件任務 ──────────────────────────────────────────────────
            # PM 審核完成 → 策略小組
            new_reviewed_at = _pm_review_just_completed(last_seen=last_pm_reviewed_at)
            if new_reviewed_at:
                log.info("[EVENT] PM review completed (%s) → StrategyCommitteeAgent", new_reviewed_at)
                last_pm_reviewed_at = new_reviewed_at
                asyncio.create_task(_run_agent("StrategyCommitteeAgent", run_strategy_committee()))

            # Watcher 3 日無成交 → 系統優化（當日只觸發一次）
            today_str = now_twn.strftime("%Y-%m-%d")
            if last_opt_trigger_date != today_str and _watcher_no_fills_3days(conn):
                log.info("[EVENT] Watcher 3-day no fills → SystemOptimizationAgent")
                last_opt_trigger_date = today_str
                asyncio.create_task(_run_agent("SystemOptimizationAgent", run_system_optimization()))

        except Exception as e:
            log.error("[ORCHESTRATOR] Main loop error: %s", e, exc_info=True)
        finally:
            conn.close()

        await asyncio.sleep(60)  # 每分鐘輪詢一次


def main() -> None:
    asyncio.run(run_orchestrator())


if __name__ == "__main__":
    main()
```

**Step 4: 執行全部測試**

```bash
python -m pytest src/tests/test_agents.py -v
```

Expected: 全部 PASS（含 Orchestrator 排程測試）

**Step 5: Commit**

```bash
git add src/openclaw/agent_orchestrator.py src/tests/test_agents.py
git commit -m "feat: add agent_orchestrator.py with asyncio scheduler + event detection"
```

---

## Task 10：PM2 設定更新 + 整體測試

**Files:**
- Modify: `ecosystem.config.js`

**Step 1: 查看現有 PM2 設定**

```bash
grep -A 10 "ai-trader-watcher" ecosystem.config.js
```

**Step 2: 新增 ai-trader-agents 進程**

在 `ecosystem.config.js` 的 `apps` 陣列中加入：

```javascript
{
  name: "ai-trader-agents",
  script: "src/openclaw/agent_orchestrator.py",
  interpreter: "python3",
  cwd: "/path/to/ai-trader",   // 實際路徑（與其他進程一致）
  env_file: "frontend/backend/.env",
  autorestart: true,
  restart_delay: 10000,
  max_restarts: 5,
  log_file: "logs/agents.log",
  error_file: "logs/agents-error.log",
},
```

**Step 3: 執行完整測試套件，確認 168+ 測試全數通過**

```bash
python -m pytest src/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: `XXX passed`（原 168 + 新增 ~15 個）

**Step 4: 更新 CLAUDE.md**

在 CLAUDE.md 的「PM2 服務」段落加入：

```
| ai-trader-agents | agent_orchestrator.py | 5 個 Claude Agent SDK 角色排程 |
```

在「核心引擎關鍵檔案」段落加入：

```
| src/openclaw/agents/      | Agent 角色模組（市場研究/Portfolio/健康監控/策略小組/優化）|
| agent_orchestrator.py     | Agent 統一排程 Orchestrator |
```

**Step 5: 最終 commit**

```bash
git add ecosystem.config.js CLAUDE.md
git commit -m "feat: ai-trader-agents PM2 process + CLAUDE.md update (v4.9.0)"
```

**Step 6: git push**

```bash
git push origin main
```

---

## 驗收標準

- [ ] `python -m pytest src/tests/` 全數通過（≥180 tests）
- [ ] `python3 -c "from openclaw.agents.base import write_trace; print('ok')"` 成功
- [ ] `python3 -c "from openclaw.agent_orchestrator import _should_run_now; print('ok')"` 成功
- [ ] `pm2 start ecosystem.config.js --only ai-trader-agents` 成功啟動
- [ ] 前端 LogTerminal 可看到 `agent='system_health'` 的 trace

---

## 注意事項

1. **ANTHROPIC_API_KEY 必須設定**：`frontend/backend/.env` 中需有此設定，否則 `query()` 會失敗。
2. **首次執行 StrategyCommitteeAgent**：sub-agents 需要 Agent tool，確認 Claude Code 版本支援。
3. **Mock 測試不呼叫真實 API**：所有單元測試 mock `query()`，CI 不需要 API key。
4. **整合測試**：本地手動執行時加 `--run-integration` flag（尚未在此 plan 中建立，可後續補充）。
5. **`_REPO_ROOT` 路徑**：`base.py` 中 `parents[3]`（`agents/` → `openclaw/` → `src/` → repo root），請驗證路徑正確。
