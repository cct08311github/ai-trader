# OpenClaw AI-Trader v4.0 — 待完成工作任務清單（Agent 接手用）

> **基準文件**：`ref_doc/OpenClaw_優化審查報告_v4.docx`（29 項）、`ref_doc/OpenClaw_前端監控系統_架構設計書.docx`
> **參考實作**：`ref_package/openclaw/`（19 模組）、`ref_package/sql/`（6 個 migration）、`ref_package/tests/`（13 個測試）
> **分析日期**：2026-02-28 | **當前後端完成度**：~90% | **當前前端完成度**：~40%

---

## 一、後端 B-1：補齊 SQL Migration 檔案 🔴 P0

### 問題描述
`src/sql/` 目前只有 **1** 個檔案：
- `migration_v1_2_0_observability_and_drawdown.sql`（建立 `llm_traces`、`daily_pnl_summary`、`strategy_health` 三張表）

`ref_package/sql/` 有 **6** 個檔案，缺少以下 **5** 個：

| 檔案 | 建立的表 | 說明 |
|------|---------|------|
| `migration_v1_1_0_core.sql` | `strategy_versions`, `risk_limits`, `decisions`, `risk_checks`, `orders`, `fills`, `portfolio_snapshots`, `incidents`, `trading_locks`, `schema_migrations` | 核心交易主鏈表，`orders` 表含 7 態狀態機（new/submitted/partially_filled/filled/cancelled/rejected/expired） |
| `migration_v1_1_1_order_events.sql` | `order_events` | 訂單事件追蹤 |
| `migration_v1_2_1_eod_data.sql` | `eod_prices`, `eod_ingest_runs` | 盤後價格資料 + 爬取紀錄 |
| `migration_v1_2_2_memory_reflection_proposals.sql` | `working_memory`, `episodic_memory`, `semantic_memory`, `reflection_runs`, `strategy_proposals`, `authority_policy`, `authority_actions` | v4 自主優化核心表 |
| `risk_limits_seed_v1_1.sql` | （INSERT 種子資料） | 風控預設參數 |

### 額外衝突檢查
`database/add_execution_tables.py` 建立了 `execution_orders`、`execution_fills`、`execution_settlements` 三張表，這些與 `migration_v1_1_0_core.sql` 的 `orders`/`fills` 表名不同但功能重疊。需決定：
- **方案 A**（建議）：以 `ref_package/sql/` 的 `orders`/`fills` 表為主（因為 `src/openclaw/` 模組如 `drawdown_guard.py`、`sentinel.py` 的 `risk_engine.OrderCandidate` 已引用此 schema），保留 `execution_*` 為擴充備用
- **方案 B**：合併兩套表，需同時修改 `database/add_execution_tables.py` 和所有引用的模組

### 具體步驟
1. **複製** `ref_package/sql/` 中缺少的 5 個 `.sql` 檔案到 `src/sql/`
2. **建立** `src/scripts/init_db.py`（可參考 `ref_package/openclaw/bootstrap_and_dry_run.py` 第 191-205 行的 migration 執行順序）：
   ```
   migration 執行順序（必須嚴格按此順序）：
   1. migration_v1_1_0_core.sql
   2. migration_v1_1_1_order_events.sql
   3. migration_v1_2_0_observability_and_drawdown.sql  ← 已存在
   4. migration_v1_2_1_eod_data.sql
   5. migration_v1_2_2_memory_reflection_proposals.sql
   6. risk_limits_seed_v1_1.sql
   ```
3. **確認** PRAGMA 設定：每次連線都應執行 `PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA synchronous = NORMAL; PRAGMA busy_timeout = 5000;`
4. **測試** 在 `:memory:` DB 上依序執行所有 migration，驗證無 SQL 錯誤

### 驗收標準
- ✅ `src/sql/` 包含全部 6 個 migration 檔案
- ✅ `src/scripts/init_db.py` 可從零建立完整 DB，無 SQL 錯誤
- ✅ 建立後的 DB 包含以下全部表（共 21 張，對應 v4 Gate 2 要求）：
  `schema_migrations`, `strategy_versions`, `risk_limits`, `decisions`, `risk_checks`, `orders`, `fills`, `order_events`, `portfolio_snapshots`, `incidents`, `trading_locks`, `llm_traces`, `daily_pnl_summary`, `strategy_health`, `eod_prices`, `eod_ingest_runs`, `working_memory`, `episodic_memory`, `semantic_memory`, `reflection_runs`, `strategy_proposals`, `authority_policy`, `authority_actions`
- ✅ `token_usage_monthly`、`token_budget_events` 表由 `token_budget.py` 運行時自建（不在 migration 中），確認不衝突即可

---

## 二、後端 B-2：補齊缺失的核心模組 🔴 P0

### 問題描述
以下 `ref_package/openclaw/` 模組在 `src/openclaw/` 中找不到同名檔案：

#### 2.1 `orders.py` — Order 狀態機（必須遷入）

**ref_package 路徑**：`ref_package/openclaw/orders.py`（60 行）

**功能**：定義 Order 狀態機，v4 #1 核心要求。包含：
- `TERMINAL_STATUSES = {"filled", "cancelled", "rejected", "expired"}`
- `ALLOWED_TRANSITIONS` — 7 個狀態的合法轉換表
- `can_transition(current, next)` → bool
- `get_order_status(conn, order_id)` → 從 `orders` 表讀取
- `transition_order_status(conn, order_id, next)` → 更新狀態（違規拋 `OrderStateError`）
- `summarize_fill_status(conn, order_id)` → 根據 `fills` 表計算實際成交狀態

**步驟**：複製 `ref_package/openclaw/orders.py` → `src/openclaw/orders.py`，無需修改 import（已使用標準 `sqlite3`）。

#### 2.2 `order_store.py` — 訂單持久化

**ref_package 路徑**：`ref_package/openclaw/order_store.py`（1737 bytes）

**功能**：將 `OrderCandidate` 寫入 `orders` 表、將成交回報寫入 `fills` 表、寫入 `order_events` 表。

**步驟**：複製到 `src/openclaw/order_store.py`，確認 import 路徑正確。

#### 2.3 `risk_store.py` — 風控決策持久化

**ref_package 路徑**：`ref_package/openclaw/risk_store.py`（1557 bytes）

**功能**：將 `EvaluationResult` 寫入 `risk_checks` 表。

**步驟**：複製到 `src/openclaw/risk_store.py`。

#### 2.4 `audit_store.py` — 稽核記錄

**ref_package 路徑**：`ref_package/openclaw/audit_store.py`（1376 bytes）

**功能**：將決策稽核事件寫入 `incidents` 表。

**步驟**：複製到 `src/openclaw/audit_store.py`。

#### 2.5 `broker.py` — 經紀商適配器

**ref_package 路徑**：`ref_package/openclaw/broker.py`（286 行 / 9889 bytes）

**功能**：
- `BrokerAdapter` Protocol（抽象介面，定義 `submit_order`, `poll_order_status`, `cancel_order`）
- `SimBrokerAdapter` — 模擬經紀商（本地測試用）
- `ShioajiAdapter` — 真實永豐金 Shioaji 整合（含 `map_shioaji_error_to_reason_code`, `map_shioaji_exec_status`）
- `BrokerSubmission`, `BrokerFill`, `BrokerOrderStatus` 資料類

**步驟**：複製到 `src/openclaw/broker.py`。注意：目前 `scripts/test_simulation_login.py` 已有 Shioaji 登入測試，確認不衝突。

#### 2.6 `eod_ingest.py` — 盤後資料管道

**ref_package 路徑**：`ref_package/openclaw/eod_ingest.py`（8916 bytes）

**功能**：TWSE/TPEx 盤後資料爬取 + 寫入 `eod_prices`/`eod_ingest_runs` 表。

**與現有模組的關係**：`src/openclaw/institution_ingest.py` 處理的是「三大法人買賣超」（#18），而 `eod_ingest.py` 處理的是「盤後股價資料」（#P1 資料管道），**兩者功能不同，不重疊**。

**步驟**：複製到 `src/openclaw/eod_ingest.py`。

#### 2.7 `bootstrap_and_dry_run.py` — 乾跑驗證腳本

**ref_package 路徑**：`ref_package/openclaw/bootstrap_and_dry_run.py`（212 行 / 7299 bytes）

**功能**：端到端乾跑驗證腳本，依序：
1. 執行所有 migration
2. 插入測試種子資料
3. 模擬 LLM 呼叫（`_mock_llm_call`）
4. 執行完整 pipeline（news_guard → pm_debate → episodic_memory → semantic_rule → reflection → proposal）
5. 列印 DB summary（驗證 12 張表都有資料）

**步驟**：
1. 複製到 `src/openclaw/bootstrap_and_dry_run.py`
2. 更新第 10-13 行 import 路徑（原始 import 使用 `from openclaw.xxx`，需確認 `src/openclaw/` 可被正確解析）
3. 特別注意第 12 行 `from openclaw.proposal_engine import ProposalInput`：`src/openclaw/proposal_engine.py` 使用的是 `StrategyProposal` dataclass 而非 `ProposalInput`，**需要調適**

### 驗收標準
- ✅ 以上 7 個檔案皆存在於 `src/openclaw/`
- ✅ `python -c "from openclaw.orders import can_transition; print(can_transition('new','submitted'))"` 輸出 `True`
- ✅ `python -m openclaw.bootstrap_and_dry_run --db :memory:` 可執行完成（或修改後的等價命令）
- ✅ `bootstrap_and_dry_run` 的 `print_summary` 輸出中，12 張表皆有 count > 0

---

## 三、後端 B-3：補齊測試檔案 🔴 P0

### 問題描述
`src/tests/` 為空目錄（僅有 `__pycache__/`）。`ref_package/tests/` 有 13 個測試檔。

### 具體步驟

#### 3.1 從 ref_package 遷入的測試（13 個）

| 檔案 | 測試的模組 | 大小 | 需修改的 import |
|------|-----------|------|----------------|
| `test_broker.py` | `broker.py` | 596B | `from openclaw.broker import ...` |
| `test_drawdown_guard.py` | `drawdown_guard.py` | 2124B | 同上 |
| `test_eod_ingest.py` | `eod_ingest.py` | 1469B | 同上 |
| `test_llm_observability.py` | `llm_observability.py` | 1407B | 同上 |
| `test_memory_store.py` | `memory_store.py` | 2186B | 同上 |
| `test_news_guard.py` | `news_guard.py` | 584B | 同上 |
| `test_order_store.py` | `order_store.py` | 1825B | 同上 |
| `test_orders.py` | `orders.py` | 2345B | 同上 |
| `test_position_sizing.py` | `position_sizing.py` | 967B | 同上 |
| `test_proposal_engine.py` | `proposal_engine.py` | 2011B | **需修改**：ref 使用 `ProposalInput`，src 使用 `StrategyProposal` |
| `test_reflection_loop.py` | `reflection_loop.py` | 1408B | 同上 |
| `test_risk_engine.py` | `risk_engine.py` | 4252B | 同上 |
| `test_store.py` | 整合 store 測試 | 3073B | 同上 |

#### 3.2 需新建的測試（16 個，對應 src/ 新增模組）

每個測試檔必須包含：
- **setup**：建立 `:memory:` SQLite 連線 + 執行必要的 migration
- **至少 3 個測試函數**：成功路徑 + 邊界條件 + 失敗路徑

| 新測試檔 | 測試的模組 | 關鍵測試場景 |
|---------|-----------|-------------|
| `test_sentinel.py` | `sentinel.py` | trading_locked→阻斷, broker離線→阻斷, DB延遲>200ms→阻斷, 正常→通過, PM veto 為 soft |
| `test_shadow_mode.py` | `shadow_mode.py` | 10%→30%→100% 推進, 2h 內回滾, 一致性 hash 確定性, to_dict/from_dict 序列化 |
| `test_authority.py` | `authority.py` | Level 0 全手動, Level 3 禁區("stop_loss_logic")不可自動審核, set_level 寫入 audit log |
| `test_strategy_registry.py` | `strategy_registry.py` | create→draft, activate→active（舊版deprecated）, rollback→rolled_back, monthly report |
| `test_tw_session_rules.py` | `tw_session_rules.py` | 09:05→preopen, 10:00→regular, 13:35→afterhours, 14:00→closed, multiplier 正確應用 |
| `test_take_profit.py` | `take_profit.py` | 目標價→部分出場, 追蹤止損→全部出場, 時間衰減, 空倉時 hold |
| `test_order_slicing.py` | `order_slicing.py` | TWAP 5片 qty 總和, VWAP 按 volume_profile 分配, depth 檢查 |
| `test_correlation_guard.py` | `correlation_guard.py` | 高相關→breach, 正常→ok, 空 portfolio→ok, matrix 對稱性 |
| `test_institution_ingest.py` | `institution_ingest.py` | parse_institution_payload 正確解析, chip_health_score 範圍 0~1, 三方同向得分更高 |
| `test_token_budget.py` | `token_budget.py` | >=100%→halt, >=85%→throttle, >=70%→warn, budget=0→ok |
| `test_cash_mode.py` | `cash_mode.py` | 市場評級觸發觀察模式 |
| `test_edge_metrics.py` | `edge_metrics.py` | edge 計算邏輯 |
| `test_market_regime.py` | `market_regime.py` | 市場環境分類 |
| `test_trading_calendar.py` | `trading_calendar.py` | 交易日/非交易日判斷 |
| `test_prompt_security.py` | `prompt_security.py` | 注入攻擊被攔截 |
| `test_network_allowlist.py` | `network_allowlist.py` | IP 白名單驗證 |

#### 3.3 pytest 配置

確認 `pytest.ini`（根目錄已存在）的 `testpaths` 包含 `src/tests`：
```ini
[pytest]
testpaths = src/tests ref_package/tests
pythonpath = src
```

### 驗收標準
- ✅ `cd /Users/openclaw/.openclaw/shared/projects/ai-trader && python -m pytest src/tests/ -v --tb=short` 全部 PASS
- ✅ 測試數量 >= 80 個（13 遷入 × ~3 函數 + 16 新建 × ~3 函數）
- ✅ 無任何 `ImportError` 或 `ModuleNotFoundError`

---

## 四、後端 B-4：產出 Gap Matrix 🟡 P1

### 問題描述
`OpenClaw_v4_強硬重構指令.md` 第 21-33 行明確要求：建立 `gap_matrix.md`，逐條覆蓋 v4 #1~#29。

### 內容要求
在專案根目錄建立 `gap_matrix.md`，格式為 Markdown 表格，每行一條 v4 項目：

```markdown
| v4_id | requirement | current_state | gap | risk_level | target_modules | refactor_action | acceptance_criteria | test_case_id |
```

**每一欄填寫規則**：
- `v4_id`：#1 到 #29
- `requirement`：從 `OpenClaw_優化審查報告_v4.docx`「完整優化建議彙整總覽」的「問題項目」+「建議行動」欄位摘要
- `current_state`：填「已實作」/「部分實作」/「未實作」
- `gap`：若已實作填「無」；若有缺口，具體描述缺什麼
- `risk_level`：高/中/低
- `target_modules`：列出 `src/openclaw/` 中對應的 `.py` 檔案名稱
- `refactor_action`：若無缺口填「維護」；若有缺口，描述具體改法
- `acceptance_criteria`：可驗證的條件（如「xxxx.py 中 xx 函數返回 True」）
- `test_case_id`：對應 `src/tests/` 中的測試函數名

**數據來源**：可直接參考 `v4_feature_completeness_report.md`（位於 brain artifact 目錄）中的 29 項比對結果。

### 驗收標準
- ✅ `gap_matrix.md` 位於專案根目錄
- ✅ #1~#29 共 29 行，無遺漏
- ✅ 所有 `current_state` 為「已實作」的項目必須有對應的 `test_case_id`

---

## 五、前端 F-1：系統監控模組強化 🔴 P0

### 問題描述
`frontend/web/src/pages/System.jsx`（97 行）目前僅有：
- 靜態服務狀態卡片（硬編碼綠燈/黃燈，非動態）
- `ControlPanel` 元件（主開關、緊急停止）
- `LogTerminal` 元件（SSE 日誌推送）

設計書要求 **7 項核心元素**，目前僅 1 項動態（LogTerminal），其餘 6 項需實作：

### 需新增的後端 API（位於 `frontend/backend/app/api/`）

#### API-1：`GET /api/system/health`
**建立檔案**：擴充 `frontend/backend/app/api/control.py` 或新建 `health.py`

**回傳格式**：
```json
{
  "services": {
    "fastapi": {"status": "online", "latency_ms": 12},
    "shioaji": {"status": "simulation", "latency_ms": null},
    "sqlite": {"status": "online", "latency_ms": 3},
    "sentinel": {"last_heartbeat": "2026-02-28T22:00:00+08:00", "today_circuit_breaks": 0}
  },
  "resources": {
    "cpu_percent": 23.5,
    "memory_percent": 45.2,
    "disk_used_gb": 12.3,
    "disk_total_gb": 256.0
  },
  "db_health": {
    "wal_size_bytes": 1048576,
    "write_latency_p99_ms": 15,
    "last_checkpoint": "2026-02-28T14:00:00+08:00"
  }
}
```
**數據來源**：
- `services.sqlite`: `PRAGMA quick_check` + 計時
- `services.sentinel`: 讀 `sentinel_status` 表（若表不存在則 fallback 為 `last_heartbeat=null`）、讀 `incidents` 表 `WHERE source='sentinel' AND ts >= date('now')`
- `resources`: 使用 Python `psutil` 套件（需加入 `frontend/backend/requirements.txt`）
- `db_health.wal_size_bytes`: `PRAGMA wal_checkpoint` 或檢查 `.db-wal` 檔案大小
- `db_health.write_latency_p99_ms`: 執行一次 `INSERT` + `DELETE` 到臨時表計時

#### API-2：`GET /api/system/quota`
**回傳格式**：
```json
{
  "month": "2026-02",
  "budget_twd": 650.0,
  "used_twd": 312.5,
  "used_percent": 48.1,
  "status": "ok",
  "daily_trend": [
    {"date": "2026-02-27", "cost_twd": 18.2},
    {"date": "2026-02-28", "cost_twd": 22.1}
  ]
}
```
**數據來源**：讀 `token_usage_monthly` 表（由 `src/openclaw/token_budget.py` 寫入）

#### API-3：`GET /api/system/risk`
**回傳格式**：
```json
{
  "today_realized_pnl": -3200,
  "monthly_drawdown_pct": 0.052,
  "monthly_drawdown_limit_pct": 0.15,
  "drawdown_remaining_pct": 0.098,
  "losing_streak_days": 2,
  "risk_mode": "normal"
}
```
**數據來源**：讀 `daily_pnl_summary` 表最新一行

#### API-4：`GET /api/system/events`
**回傳格式**：
```json
{
  "events": [
    {"ts": "2026-02-28T09:00:00", "severity": "info", "source": "sentinel", "code": "SENTINEL_OK", "detail": "..."}
  ]
}
```
**數據來源**：讀 `incidents` 表 `WHERE ts >= date('now') ORDER BY ts DESC LIMIT 100`

### 需修改的前端元件

**修改檔案**：`frontend/web/src/pages/System.jsx`

**新增元素**（按設計書 4.4 節規格）：
1. **服務狀態卡片** — 改為動態：每 5 秒 fetch `/api/system/health`，根據 `status` 顯示綠燈（online）/ 黃燈（simulation/delayed）/ 紅燈（offline）
2. **Sentinel 心跳面板** — 新增：顯示 `services.sentinel.last_heartbeat` 和 `today_circuit_breaks`
3. **API 配額進度條** — 新增：fetch `/api/system/quota`，以進度條顯示 `used_percent`，超 80% 紅色
4. **系統資源監控** — 新增：CPU/記憶體/磁碟 進度條
5. **風控狀態儀表板** — 新增：fetch `/api/system/risk`，顯示回撤進度條
6. **事件時間軸** — 新增：fetch `/api/system/events`，以時間軸列表顯示

**視覺規格**（設計書 4.4）：
- 任一服務離線超過 30 秒 → 紅燈
- Sentinel 超過 60 秒未心跳 → 告警
- API 配額 > 80% → 黃色警告
- CPU > 80% 持續 → 紅色
- 虧損空間 < 20% → 紅色

### 驗收標準
- ✅ 4 個新 API 端點可正常回傳 JSON
- ✅ System 頁面顯示所有 6 項動態數據
- ✅ 顏色告警邏輯正確（可通過 mock 數據驗證）
- ✅ 每 5-60 秒自動刷新

---

## 六、前端 F-2：策略執行模組補強 🟡 P1

### 問題描述
`frontend/web/src/pages/Strategy.jsx`（321 行）已有：
- ✅ 即時 AI 決策日誌（SSE `LogTerminal`）
- ✅ 策略提案審核台（`ProposalModal` 元件）

缺少 3 項：

### F-2a：今日市場評級卡片

**新增後端 API**：`GET /api/strategy/market-rating`
**數據來源**：讀 `llm_traces` 表中今日 `agent='PM'` 的最新一筆，從 `response_text` 解析市場評級（A/B/C）
**前端顯示**：A 綠色 / B 黃色 / C 紅色 大字卡片 + 評級依據文字

### F-2b：語義記憶庫瀏覽器

**新增後端 API**：`GET /api/strategy/semantic-memory?sort=confidence&order=desc&limit=50`
**數據來源**：讀 `semantic_memory` 表，欄位：`rule_id`, `rule_text`, `confidence`, `sample_count`, `last_validated_date`, `status`
**前端顯示**：表格列表，每行點擊可展開 `source_episodes_json` 的情節連結

### F-2c：多空辯論記錄

**新增後端 API**：`GET /api/strategy/debates?date=today`
**數據來源**：讀 `llm_traces` 表 `WHERE agent='PM' AND prompt_text LIKE '%bull_case%'`（辯論 trace 特徵）
**前端顯示**：三欄對比：多方 vs 空方 vs PM 最終判斷

### 驗收標準
- ✅ Strategy 頁面新增 3 個面板
- ✅ 語義記憶瀏覽器可按 confidence 排序

---

## 七、前端 F-3：庫存總覽補強 🟡 P1

### F-3a：持倉詳情抽屜

**修改檔案**：`frontend/web/src/pages/Portfolio.jsx`
**新增後端 API**：`GET /api/portfolio/position-detail/{symbol}`
**數據來源**：`trades` 表（進場理由）JOIN `llm_traces` 表（PM 授權原文）
**前端互動**：點擊持倉列表任一行 → 右側滑出 `Drawer` 面板（使用 CSS `transform: translateX`），顯示：
- 進場理由（從關聯的 `llm_traces.response_text` 取）
- 止損/止盈設定（從 `take_profit` 模組設定取）
- PM 授權原文
- 籌碼趨勢歷史（從 `institution_flows` 表取該 symbol 近 10 日資料）

### F-3b：籌碼健康度進度條

**修改位置**：Portfolio 持倉列表每行新增一欄
**視覺規格**：0–3 紅色(#FF4D4F) / 4–6 黃色(#FAAD14) / 7–10 綠色(#00C48C)

### F-3c：板塊 40% 集中度警示

**修改元件**：`frontend/web/src/components/charts/AllocationDonut.jsx`
**邏輯**：計算 `buildAllocationData` 中各板塊佔比，超 40% 的區塊加紅色邊框 (`stroke: #FF4D4F, strokeWidth: 3`)

### 驗收標準
- ✅ 點擊持倉行可開啟右側面板
- ✅ 面板顯示的數據與 DB 中一致
- ✅ 籌碼進度條顏色正確（可用 0/5/9 分值測試）

---

## 八、前端 F-4：交易明細補強 🟡 P1

### F-4a：決策因果鏈展開

**修改檔案**：`frontend/web/src/pages/Trades.jsx`
**新增後端 API**：`GET /api/portfolio/trade-causal/{trade_id}`
**回傳格式**：
```json
{
  "decision": {"decision_id": "...", "signal_side": "buy", "reason_json": "..."},
  "risk_check": {"passed": true, "reject_code": null},
  "llm_traces": [{"agent": "PM", "prompt_text": "...", "response_text": "..."}],
  "fills": [{"fill_id": "...", "qty": 1000, "price": 580.0}]
}
```
**前端互動**：點擊交易行 → 展開子區塊，用時間線樣式顯示 PM 決策 → Trader 執行 → 成交回報

### F-4b：月度統計摘要

**新增後端 API**：`GET /api/portfolio/monthly-summary?month=2026-02`
**數據來源**：`trades` 表聚合
**顯示**：本月成交金額、手續費+稅金淨成本、勝率、平均持倉天數、最大單筆獲利/虧損

### F-4c：執行品質分析（滑價趨勢）

**數據來源**：`trades` 表的 `price` vs `decision` 當下的 `market_state.best_bid/ask`
**顯示**：滑價 (bps) 折線圖

### 驗收標準
- ✅ 因果鏈展開可追溯到 LLM trace
- ✅ 月度摘要數字經過人工驗算確認正確

---

## 九、測試執行命令彙整

```bash
# 1. 後端單元測試
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
source .venv/bin/activate
python -m pytest src/tests/ -v --tb=short

# 2. 後端整合測試（乾跑）
python -m openclaw.bootstrap_and_dry_run --db /tmp/test_dry_run.db --reset

# 3. 前端單元測試
cd frontend/web
npx vitest run

# 4. 後端 API 測試
cd frontend/backend
python -m pytest tests/ -v

# 5. SSE 煙霧測試
cd frontend/backend
python tools/sse_smoke_test.py
```

---

## 十、執行優先順序

```
Phase 0（基礎設施，1-2 天）              ← 後續任務依賴此階段
  ├─ B-1：SQL Migration 補齊
  ├─ B-2：缺失模組遷入（orders.py 等 7 檔）
  └─ B-3：測試檔案遷入 + 新建

Phase 1（前端後端新 API，2-3 天）
  ├─ F-1 後端：新增 4 個 /api/system/ 端點
  ├─ F-1 前端：System.jsx 6 項動態元素
  └─ B-4：Gap Matrix 產出

Phase 2（前端進階功能，2-3 天）
  ├─ F-2：策略執行 3 項補強
  ├─ F-3：庫存總覽 3 項補強
  └─ F-4：交易明細 3 項補強

Phase 3（收尾驗證，1 天）
  ├─ 全部測試執行 + 修復
  └─ bootstrap_and_dry_run 端到端驗證
```

---

*文件版本：v2.0 | 產出日期：2026-02-28 | 基於 v4_feature_completeness_report 分析*
*專案路徑：`/Users/openclaw/.openclaw/shared/projects/ai-trader/`*
