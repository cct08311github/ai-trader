# AI Trader — Agent 角色架構設計

**設計日期**：2026-03-02
**狀態**：已核准，待實作
**負責人**：Claude + openclaw

---

## 一、背景與目標

AI Trader 現有角色（PM 審核、Sentinel 哨兵、Ticker Watcher、Risk Engine、News Guard）均為規則驅動或單次 LLM 呼叫。本次設計新增五個 Claude Agent SDK 驅動的角色，填補以下缺口：

| 缺口 | 新角色 |
|------|--------|
| 無每日市場結構分析 | MarketResearchAgent |
| 無收盤後持倉健康度審查 | PortfolioReviewAgent |
| 無自動化系統健康監控 | SystemHealthAgent |
| 無多方辯論式策略建議 | StrategyCommitteeAgent |
| 無參數自我優化機制 | SystemOptimizationAgent |

---

## 二、架構決策

### 執行形式
**Claude Agent SDK（subprocess）**，使用 `@anthropic-ai/claude-agent-sdk` 的 Python 等效 `claude_agent_sdk`。

### 部署模式
**統一 Orchestrator（方案 A）**：單一 PM2 進程 `ai-trader-agents`，內部 asyncio 排程管理所有角色。

**選擇理由**：
- 與現有 `ticker_watcher.py` PM2 模式一致
- 單一進程管理簡單，共享 DB 連線
- asyncio `try/except` 隔離確保一個 agent crash 不影響排程器

### 執行節點
**混合（定時 + 事件）**：cron 為主，事件補充（PM 審核完成、Watcher 3 日無成交）。

### 輸出方式
**寫入 DB + SSE 串流**：結果寫 `llm_traces`（前端 LogTerminal 即時可見），建議寫 `strategy_proposals`。

---

## 三、檔案結構

```
src/openclaw/
  agent_orchestrator.py         ← 主進程（PM2 ai-trader-agents）
  agents/
    __init__.py
    base.py                     ← 共用：DB helper、trace 格式、錯誤處理
    market_research.py          ← MarketResearchAgent
    portfolio_review.py         ← PortfolioReviewAgent
    system_health.py            ← SystemHealthAgent
    strategy_committee.py       ← StrategyCommitteeAgent（含 sub-agents）
    system_optimization.py      ← SystemOptimizationAgent

src/tests/
  test_agents.py                ← 單元測試（mock query()）

ecosystem.config.js             ← 新增 ai-trader-agents 進程
```

---

## 四、五個角色職責

### 1. MarketResearchAgent（市場研究員）

| 欄位 | 說明 |
|------|------|
| **執行時機** | 每交易日 08:20（盤前，10 分鐘完成） |
| **觸發方式** | cron |
| **輸入** | `eod_prices`（近 5 日）、`decisions`（近期訊號） |
| **工作** | 分析大盤強弱、各板塊資金流向、異常成交量、整體多空氣氛 |
| **輸出** | `llm_traces`（agent='market_research'）+ `strategy_proposals`（板塊建議） |
| **allowedTools** | `Read`, `Bash` |
| **maxTurns** | 8 |

### 2. PortfolioReviewAgent（Portfolio 審查員）

| 欄位 | 說明 |
|------|------|
| **執行時機** | 每交易日 14:30（收盤後） |
| **觸發方式** | cron |
| **輸入** | `positions`、`daily_pnl_summary`、`orders JOIN fills` |
| **工作** | 持倉集中度風險、當日勝率/虧損分析、再平衡建議 |
| **輸出** | `llm_traces` + `strategy_proposals`（再平衡行動） |
| **allowedTools** | `Read`, `Bash` |
| **maxTurns** | 8 |

### 3. SystemHealthAgent（系統健康監控）

| 欄位 | 說明 |
|------|------|
| **執行時機** | 每 30 分鐘（市場時段）/ 每 2 小時（非市場時段） |
| **觸發方式** | cron |
| **輸入** | PM2 狀態、DB 回應時間、磁碟空間、最新 watcher scan 時間 |
| **工作** | 檢查服務在線、DB WAL 大小、watcher 心跳、寫入異常記錄 |
| **輸出** | `llm_traces`（agent='system_health'），異常時寫 `incidents` 表 |
| **allowedTools** | `Bash` |
| **maxTurns** | 5 |

### 4. StrategyCommitteeAgent（策略小組）

| 欄位 | 說明 |
|------|------|
| **執行時機** | PM 審核完成後（事件），或每週一 07:30（週期回顧） |
| **觸發方式** | event + cron |
| **工作** | 三個 sub-agent 串連辯論：布局方向、訊號閾值、停損/止盈最佳化 |
| **輸出** | `strategy_proposals`（requires_human_approval=1）+ `llm_traces` |
| **allowedTools** | `Read`, `Bash`, `Agent` |
| **maxTurns** | 15 |

**Sub-agents**：

```python
agents = {
    "bull-analyst": {
        "description": "看多派分析師，從技術面與籌碼面找做多理由",
        "prompt": "分析近期走勢，提出加碼方向與目標價",
        "tools": ["Read", "Bash"],
    },
    "bear-analyst": {
        "description": "看空派分析師，找出風險與做空訊號",
        "prompt": "識別高風險部位與可能下跌的標的",
        "tools": ["Read", "Bash"],
    },
    "risk-arbiter": {
        "description": "風險仲裁者，整合兩方意見給出最終建議",
        "prompt": "整合 bull/bear 分析，輸出 confidence-weighted 最終建議",
        "tools": ["Read"],
    },
}
```

### 5. SystemOptimizationAgent（系統優化員）

| 欄位 | 說明 |
|------|------|
| **執行時機** | 每週一 07:00，或 watcher 連續 3 日無成交時觸發 |
| **觸發方式** | cron + event |
| **工作** | 分析近 4 週交易，評估 `BUY_SIGNAL_PCT` / `TAKE_PROFIT_PCT` / `STOP_LOSS_PCT` 是否需調整，更新 `reflection_loop` 記憶 |
| **輸出** | `strategy_proposals`（type='config_change'，requires_human_approval=1）|
| **allowedTools** | `Read`, `Bash` |
| **maxTurns** | 10 |

---

## 五、Orchestrator 核心邏輯

```python
# agent_orchestrator.py（概念）

# 定時任務
scheduler.add_cron("08:20 Mon-Fri", MarketResearchAgent)
scheduler.add_cron("14:30 Mon-Fri", PortfolioReviewAgent)
scheduler.add_interval(minutes=30,  SystemHealthAgent, market_only=True)
scheduler.add_interval(hours=2,     SystemHealthAgent, off_market=True)
scheduler.add_cron("Mon 07:00",     SystemOptimizationAgent)
scheduler.add_cron("Mon 07:30",     StrategyCommitteeAgent)

# 事件監聽（每 60 秒輪詢）
event_watcher.on("pm_review_completed", StrategyCommitteeAgent)
event_watcher.on("watcher_3days_no_fill", SystemOptimizationAgent)
```

**事件偵測（輕量輪詢，不用 message queue）**：

| 事件 | 偵測方式 |
|------|---------|
| PM 審核完成 | 讀 `config/daily_pm_state.json`，比較 `reviewed_at` 是否比上次新 |
| Watcher 3 日無成交 | `SELECT COUNT(*) FROM fills WHERE ts_fill > datetime('now','-3 days')` |

---

## 六、共用 Prompt 框架

```
你是 AI Trader 系統的 {角色名}。

## 背景
{當日日期 / 市場狀況摘要}

## 任務
{具體分析指令}

## 工具使用規範
- 只讀取 data/sqlite/trades.db（禁止寫入，除非明確指示）
- bash 查詢限用 sqlite3 指令，不執行任何交易操作
- 輸出必須包含：summary（繁中）、confidence（0-1）、action_type

## 輸出格式
最後回覆必須是 JSON：
{
  "summary": "...",
  "confidence": 0.8,
  "action_type": "observe|suggest|config_change",
  "proposals": [...]
}
```

---

## 七、DB 寫入規範

| 輸出類型 | 寫入目標 | `requires_human_approval` |
|---------|---------|--------------------------|
| 觀察報告 | `llm_traces`（agent=角色名） | 不適用 |
| 一般建議 | `strategy_proposals` | `0` |
| 參數變更 | `strategy_proposals`（type='config_change'） | `1`（必須人工確認） |
| 系統異常 | `incidents` | 不適用 |

---

## 八、安全護欄

- 所有 agent 使用 `permissionMode: "acceptEdits"` + `disallowedTools: ["Write"]`
- `SystemOptimizationAgent` 可使用 `Edit`，但限制路徑為 `data/drafts/`（不可直接改 `config/`）
- 任何 agent 不可直接修改 `config/system_state.json`（僅允許透過 `/api/system` API）
- 參數變更類提案（`config_change`）強制 `requires_human_approval=1`

---

## 九、測試策略

### 單元測試（`src/tests/test_agents.py`）
- Mock `query()` 回傳固定 JSON，驗證 `write_llm_trace` 和 `write_proposal` 邏輯
- 驗證 prompt 格式化函數（日期注入、DB 摘要生成）
- 驗證事件偵測邏輯（mock `daily_pm_state.json`、mock fills 查詢）

### 整合測試（本地手動，CI 跳過）
- 標記 `@pytest.mark.integration`
- 使用 `--run-integration` flag 啟用

### Orchestrator 排程測試
- Mock `datetime.now` 加速時鐘，驗證各 cron 在正確時間觸發

---

## 十、PM2 設定（新增）

```javascript
// ecosystem.config.js 新增
{
  name: "ai-trader-agents",
  script: "src/openclaw/agent_orchestrator.py",
  interpreter: "python3",
  env_file: "frontend/backend/.env",
  autorestart: true,
  restart_delay: 10000,
  max_restarts: 5,
}
```

---

## 十一、版本標記

- 完成後版本升為 **v4.9.0**
- 更新 `CLAUDE.md`（新增 ai-trader-agents PM2 進程、agents/ 模組說明）
