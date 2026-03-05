# AI Trader — Claude Code 專案說明

> 每次重大優化後更新此文件。這是給未來 Claude session 的完整工作背景。

---

## 一、系統概覽

**AI Trader** 是一套台股 AI 自動交易系統，整合 LLM 決策、風控引擎、Portfolio 管理與即時監控前端。

| 層級 | 路徑 | 說明 |
|------|------|------|
| 核心引擎 | `src/openclaw/` | Python，決策管線、PM 辯論、風控、選股 |
| FastAPI 後端 | `frontend/backend/` | REST API + SSE，SQLite 讀寫 |
| React 前端 | `frontend/web/` | Vite + Tailwind，即時儀表板 |
| 設定 | `config/` | system_state.json、daily_pm_state.json、watchlist.json |
| 資料庫 | `data/sqlite/trades.db` | 唯一共用 SQLite，前後端與 watcher 共用 |

---

## 二、系統安全模型

```
trading_enabled = true
  AND .EMERGENCY_STOP 不存在
  → 自動交易啟動
```

- `simulation_mode: true` = 模擬盤（預設）；`false` = 實際盤
- 切換至實際盤會自動停用 auto trading（雙重保險）
- `config/system_state.json` 為主開關，不要直接手動改，用 API

---

## 三、核心引擎關鍵檔案

| 檔案 | 功能 |
|------|------|
| `decision_pipeline_v4.py` | 主決策管線 |
| `pm_debate.py` | PM 辯論 / Review 邏輯 |
| `daily_pm_review.py` | 每日 PM 審核 |
| `risk_engine.py` | 風控計算 |
| `position_sizing.py` | 部位大小 |
| `proposal_engine.py` | 交易提案 |
| `ticker_watcher.py` | 每 3 分鐘掃盤、自動選股 |
| `sentinel.py` | 市場異常偵測 |
| `memory_store.py` | 跨次決策記憶 |
| `technical_indicators.py` | 技術指標純函數（MA/RSI/MACD/ATR/支撐壓力） |
| `signal_generator.py` | EOD 日線驅動信號（MA 黃金交叉 + RSI + Trailing Stop） |
| `concentration_guard.py` | 集中度守衛（>60% 自動減倉 / 40-60% Gemini 審查） |
| `proposal_executor.py` | approved proposal 自動執行（建立 sell 訂單） |
| `proposal_reviewer.py` | Gemini 自動審查 pending proposals + Telegram 通知 |
| `tg_notify.py` | Telegram Bot API 輕量通知工具 |
| `agents/eod_analysis.py` | 盤後分析 Agent（每交易日 16:35 TWN Cron） |
| `src/openclaw/agents/` | Agent 角色模組（市場研究/Portfolio/健康監控/策略小組/優化）|
| `agent_orchestrator.py` | Agent 統一排程 Orchestrator（PM2: ai-trader-agents） |

---

## 四、FastAPI 後端

**路徑**：`frontend/backend/`
**啟動**：由 PM2 `ai-trader-api` 管理（`ecosystem.config.js`）

### API 路由

| Router | 路徑前綴 | 說明 |
|--------|---------|------|
| auth | `/api/auth` | 登入取得 Bearer token |
| portfolio | `/api/portfolio` | 持倉、交易紀錄（查 `orders JOIN fills`） |
| strategy | `/api/strategy` | 提案、LLM traces |
| pm | `/api/pm` | PM review 觸發 |
| system | `/api/system` | 系統狀態開關 |
| chat | `/api/chat` | AI 助手 SSE 串流 |
| stream | `/api/stream` | Log SSE 串流 |
| control | `/api/control` | 緊急停止、模式切換 |
| settings | `/api/settings` | 系統設定讀寫 |
| analysis | `/api/analysis` | 盤後分析快照（latest/dates/{date}） |

**portfolio 路由重要 endpoint**：
- `GET /api/portfolio/quote/{symbol}` — 即時快照；Shioaji 失敗時 fallback 到 `eod_prices` 最後收盤（`source: "eod"`）
- `GET /api/portfolio/kline/{symbol}?days=60` — K 線歷史 OHLCV（查 `eod_prices`）
- `GET /api/portfolio/quote-stream/{symbol}` — BidAsk SSE（五檔即時推送）

### Auth Middleware

- `AuthMiddleware` 強制所有請求帶 `Authorization: Bearer <token>`
- **AUTH_TOKEN 未設定時**：middleware 自動生成隨機 token（並不是停用驗證）
- 測試必須明確設定 `AUTH_TOKEN` 環境變數

---

## 五、前端

**路徑**：`frontend/web/`（Vite + React 18 + Tailwind CSS）

### 頁面

| 頁面 | 路徑 | 說明 |
|------|------|------|
| Dashboard | `/` | 總覽 |
| Portfolio | `/portfolio` | 持倉、KPI、損益曲線 |
| Inventory | `/inventory` | 庫存總覽 |
| Strategy | `/strategy` | 提案、LLM trace 透明化 |
| Trades | `/trades` | 訂單 / 成交紀錄 |
| System | `/system` | 主開關、設定 |
| Analysis | `/analysis` | 盤後分析（3 Tab：市場概覽/個股技術/AI 策略） |

### 版本號

- 來源：`frontend/web/package.json` → `"version"` 欄位
- Vite 注入 `__APP_VERSION__` → `System.jsx` 自動顯示
- 版本更新：只改 `package.json`（不改 System.jsx）
- Vite content hash 跟著檔案內容變；要強制清快取 → 升版號

### UI 約束

- `FloatingLogout`：`fixed bottom:24px right:24px z-index:99999`（不可覆蓋）
- `ChatButton`：`fixed bottom-6 right-20`（偏移至 80px，避免被 FloatingLogout 遮蓋）
- Chat 視窗：`360×480px` 浮動，不使用 backdrop，不遮擋主畫面

### PositionDetailDrawer（持倉側邊抽屜）

點擊 Portfolio 持倉列觸發，包含：
1. **即時報價（QuotePanel）**：開盤時接 Shioaji SSE 五檔；休市時 fallback 顯示 `eod_prices` 最後收盤，標籤改為「最後收盤資料（YYYY-MM-DD）」
2. **K 線圖（KlineChart）**：純 SVG 元件，查 `/api/portfolio/kline/{symbol}` 顯示日線蠟燭 + 成交量（60 日）
3. 持倉摘要、決策鏈、止損/止盈、籌碼趨勢

---

## 六、資料庫

**唯一路徑**：`data/sqlite/trades.db`（絕對路徑，不走 db_router）

### 主要資料表

| 表名 | 說明 |
|------|------|
| `orders` | 訂單（symbol, side, qty, price, status, ts_submit…） |
| `fills` | 成交明細（order_id FK, qty, price, fee, tax） |
| `decisions` | AI 決策紀錄 |
| `llm_traces` | LLM 呼叫 trace（v4 schema：created_at INTEGER NOT NULL） |
| `strategy_proposals` | 策略提案 |
| `risk_checks` | 風控檢查紀錄 |
| `incidents` | 異常事件 |
| `risk_limits` | 風控參數 |
| `eod_analysis_reports` | 盤後分析快照（market_summary/technical/strategy JSON，每日一筆） |
| `eod_prices` | 每日 OHLCV（trade_date/symbol/open/high/low/close/volume），K 線來源 |

> **注意**：舊版 `trades` 表已廢棄，API 查詢改為 `orders JOIN fills`

---

## 七、PM2 服務

| 服務名 | 說明 |
|--------|------|
| `ai-trader-api` | FastAPI 後端 |
| `ai-trader-web` | React Vite Dev Server（port 3000） |
| `ai-trader-watcher` | ticker_watcher，每 3 分鐘掃盤，使用真實 Shioaji 行情 |
| `ai-trader-agents` | agent_orchestrator.py，5 個 Gemini agent 角色排程 |

```bash
pm2 status                  # 查看所有服務
pm2 restart ai-trader-api   # 重啟 API
pm2 logs ai-trader-watcher  # 看掃盤 log
```

**Broker 說明**：
- Shioaji 憑證已設定於 `frontend/backend/.env`（`SHIOAJI_API_KEY` / `SHIOAJI_SECRET_KEY`）
- watcher 啟動時會自動登入，行情為**真實市場資料**
- 目前程式碼固定 `sj.Shioaji(simulation=True)` → 永豐模擬帳戶下單，不影響真實部位
- 切換為實際下單：修改 `ticker_watcher.py` 中 `simulation=True` → `False`

### 自動策略審查流程（v4.11.x）

```
08:30 cron
  → trigger_pm_review.py → POST /api/pm/review
  → Gemini 多空辯論（持倉/近期交易/7日損益 作為 context）
  → 寫 episodic_memory（審查紀錄）+ llm_traces（完整 prompt/response）
  → Telegram 通知：✅ 授權 / 🚫 封鎖 + 多空論點

盤中每 3 分鐘
  → signal_generator（EOD MA 黃金交叉 + RSI + Trailing Stop）
  → risk_engine 7 層風控 → 自動下單（止損單跳過滑點/偏離檢查）
  → concentration_guard（>60% 自動減倉 / 40-60% 生成 pending）
  → proposal_reviewer（Gemini 審查 pending）
      → approve/reject + Telegram 通知
  → proposal_executor（執行 approved）
```

**Telegram 通知環境變數**：
- `TELEGRAM_BOT_TOKEN` — 從 `~/.openclaw/.env` 載入
- `TELEGRAM_CHAT_ID` — 預設 `1017252031`（可覆蓋）

**交易成本（v4.11.x）**：
- 手續費：`price × qty × 0.1425%`（買賣雙向）
- 證交稅：`price × qty × 0.3%`（sell only）
- T+2 交割日：買單自動填入 `orders.settlement_date`

---

## 八、測試規範

### 後端 Python（pytest）

```bash
# FastAPI 測試
cd frontend/backend && python -m pytest tests/ -q

# 核心引擎測試
pytest -q   # 根目錄 pytest.ini
```

**必讀規則**：
- 所有 FastAPI 測試 fixture 必須加：
  ```python
  monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
  ```
- 使用 `monkeypatch.setenv`，**禁用** `os.environ =`（不自動清理，污染跨測試）
- 測試 DB 要建 `orders + fills` 表，不是舊版 `trades`
- 兩個獨立 FastAPI 測試目錄，各有自己的 `conftest.py`：
  - `frontend/backend/tests/`
  - `tests/frontend_backend/`
- **FastAPI `conn_dep` generator 500 路徑**：不能 patch `conn_dep` 本身；必須 `monkeypatch.setattr(db_mod, "get_conn", broken_ctx)` + `monkeypatch.setattr(aa, "db", db_mod)`
- **FastAPI route 覆蓋率**：成功路徑（`return`）與錯誤路徑（`raise HTTPException`）需各自獨立測試，不能只測其中一個

### 前端 JavaScript（vitest）

```bash
cd frontend/web && npm test -- --run
```

**必讀規則**：
- 同一文字出現在多個元素時，用 `queryAllByText` 取代 `getByText`（後者遇多個匹配拋錯）
- 元件已本地化為繁體中文，loading 文字為 `讀取中…` / `讀取庫存資料中...`，不是 `Loading…`

---

## 九、設計文件

- `doc/` — 所有文件統一歸檔目錄
  - `doc/plans/` — Brainstorming / Writing Plans 產出，設計文件與實作計劃
  - `doc/tailscale/` — Tailscale 部署與客戶端指南
- 命名規則：`YYYY-MM-DD-<feature>-design.md` / `YYYY-MM-DD-<feature>-plan.md`

---

## 十、常用 CI 指令

```bash
gh run list --limit 5          # 查看最近 CI
gh run watch <run-id>          # 即時監控 CI
gh run view <run-id> --log-failed   # 查看失敗 log
```

---

## 十一、變更歷史摘要

| 版本 | 重點 |
|------|------|
| v4.6.x | PM review 連接 Strategy debate panel；LLM trace 透明化；PmStatusCard 移至 Portfolio |
| v4.7.x | ticker_watcher 啟動；API 從 trades 遷移至 orders/fills；前端重構 |
| v4.8.x | Chat 功能（浮動視窗）；CI 全面修復（auth、schema、loading 文字） |
| v4.9.x | 盤後分析頁面（/analysis）；eod_analysis agent；technical_indicators 模組；三新模組 100% 覆蓋 |
| v4.10.x | 持倉 Drawer K 線圖（純 SVG）；quote EOD fallback；設定頁 dirty 狀態修正 |
| v4.11.x | Strangler Fig 信號重構；Trailing Stop；T+2 交割追蹤；實際費率；Gemini 全自動策略審查；Telegram 雙向通知 |
