# AI Trader — Claude Code 專案說明

> 台股 AI 自動交易系統。詳細規範見 `.claude/rules/` 條件載入規則檔。

---

## 協作方針

**核心目標**：讓系統成為可靠、持續進化的交易助手。
**目前階段**：優化期（Auto-Memory Learning）

### 工作方式
- 先給結論，再給理由；偏實務、可執行
- 系統變更前先說明影響、風險與回滾方式
- 倉位調整、策略變更前必須確認

### Auto-Memory 學習重點
留意並記錄長期重複出現的操作模式：
- 交易節奏與決策流程
- 任務拆解與策略層級
- 對風險、異常與市場波動的反應

**原則**：只記長期模式，不記一次性操作。不確定是否該記憶 → 先詢問。記憶目的在降低操作摩擦，非增加交易風險。

---

## 系統概覽

| 層級 | 路徑 | 說明 |
|------|------|------|
| 核心引擎 | `src/openclaw/` | Python：決策管線、PM 辯論、風控、選股 |
| FastAPI 後端 | `frontend/backend/` | REST API + SSE，SQLite |
| React 前端 | `frontend/web/` | Vite + Tailwind，即時儀表板 |
| 設定 | `config/` | system_state.json、daily_pm_state.json、watchlist.json |
| 資料庫 | `data/sqlite/trades.db` | 唯一共用 SQLite |

**分支策略**：`main` 是唯一活躍主線，直接對 `main` 操作。

---

## 系統安全模型

```
trading_enabled = true AND .EMERGENCY_STOP 不存在 → 自動交易啟動
```

- `simulation_mode: true` = 模擬盤（預設）；切換實際盤會自動停用 auto trading
- `config/system_state.json` 為主開關，用 API 操作，不手動改

### Config 治理
- **Deploy Baselines**（`capital.json`, `drawdown_policy_v1.json` 等）：**必須** Git 追蹤，修改走 PR
- **Runtime State**（`system_state.json`, `daily_pm_state.json`）：`.gitignore`，系統自動 fail-safe（預設 `trading_enabled=False`）

---

## 核心引擎關鍵檔案

| 檔案 | 功能 |
|------|------|
| `decision_pipeline_v4.py` | 主決策管線 |
| `risk_engine.py` | 風控計算（7 層） |
| `ticker_watcher.py` | 每 3 分鐘掃盤 + 自動選股 |
| `signal_generator.py` | EOD 信號（MA + RSI + Trailing Stop） |
| `signal_aggregator.py` | Regime-based 動態權重融合 |
| `trading_engine.py` | 持倉狀態機 + 時間止損 |
| `concentration_guard.py` | 集中度守衛（>60% 自動減倉） |
| `proposal_executor.py` | SellIntent 執行 |
| `proposal_reviewer.py` | Gemini 審查 + Telegram |
| `agents/strategy_committee.py` | Bull/Bear/Arbiter 辯論 + 12h 去重 |
| `agent_orchestrator.py` | Agent 排程 Orchestrator |
| `eod_ingest.py` | 盤後 OHLCV + 法人籌碼 |
| `strategy_optimizer.py` | 自主優化三層架構 |

---

## PM2 服務

| 服務名 | 說明 |
|--------|------|
| `ai-trader-api` | FastAPI 後端 |
| `ai-trader-web` | React Vite Dev Server（port 3000） |
| `ai-trader-watcher` | ticker_watcher（每 3 分鐘，真實 Shioaji 行情） |
| `ai-trader-agents` | agent_orchestrator（5 Gemini agent） |
| `ai-trader-ops-summary` | 每 15 分鐘 ops summary |
| `ai-trader-reconciliation` | 每交易日 16:45 reconciliation |
| `ai-trader-incident-hygiene` | 每交易日 16:55 incident 去重 |

### Portable Path Convention
Production 代碼**禁止硬編碼** `/Users/openclaw`：
- Shell: `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"`
- Python: `Path(__file__).resolve().parents...` 或 `OPENCLAW_ROOT_ENV`

---

## 設計文件

- `doc/plans/` — 設計文件與實作計劃
- 命名：`YYYY-MM-DD-<feature>-design.md` / `-plan.md`

---

## 常用指令

```bash
# CI
gh run list --limit 5
gh run view <run-id> --log-failed

# 測試
cd frontend/backend && python -m pytest tests/ -q   # FastAPI
pytest -q                                            # 核心引擎
cd frontend/web && npm test -- --run                 # 前端

# 復盤
sqlite3 data/sqlite/trades.db "SELECT * FROM orders WHERE date(ts_submit)='YYYY-MM-DD';"

# API 測試
curl -sk -X POST https://127.0.0.1:8080/api/pm/review \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"

# PM2
pm2 status && pm2 logs ai-trader-watcher
tail -80 ~/.pm2/logs/ai-trader-api-error-1.log
```

---

## 條件載入規則檔（`.claude/rules/`）

| 規則檔 | 觸發條件 | 內容 |
|--------|---------|------|
| `backend-api.md` | `frontend/backend/**` | API 路由表、Auth、DB 連線、Telegram、Reports |
| `trading-pipeline.md` | `src/openclaw/**` | 交易流程、成本、Broker、Gemini SDK |
| `frontend-structure.md` | `frontend/web/**` | 頁面、UI 約束、Drawer |
| `testing.md` | `tests/**`, `**/tests/**` | pytest/vitest 必讀規則 |
| `db-schema.md` | `data/**`, `**/db.py` | 完整資料表 Schema + 陷阱 |
