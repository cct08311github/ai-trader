# OpenClaw v4 差異驅動重構 — Migration Plan（資料庫升級與回滾）

> 依據：v4 Gate 2/3（`ref_doc/OpenClaw_v4_強硬重構指令.md`）+ v4 規範 + `gap_matrix.md`。

## 0. 目標
1. **Gate 2 可驗證性**：db summary 能查到 v4 指定的核心表（decisions/risk_checks/orders/fills/order_events/llm_traces/memory/reflection/proposal/version）。
2. **Gate 3 可回滾性**：每個 migration 可重複執行（idempotent）、有可操作的 rollback/runbook。
3. **不中斷演進**：採「先新增、再雙寫、最後切換」策略，必要時用 view/對照表提供相容層。

---

## 1. 現況盤點（As-Is）
> 實際表結構以 `database/` 內的 init/migration 腳本與當前 `data/sqlite/*.db` 為準。

### 1.1 既有資料庫分工（假設）
- `ticks.db`：行情/EOD ticks（資料面）
- `trades.db`：交易主鏈 + 記憶/反思/提案/版本/trace（行為與稽核面）

### 1.2 已存在/已導入的 migration
- `database/add_execution_tables.py`：新增 `execution_orders/execution_fills/execution_settlements`（execution domain 方案A）
  - 風險：該腳本 FK 參照 `orders(order_id)`，但最終 canonical schema 需與 v4 Gate 2 對齊；需在 Phase 2/3 期間決定「orders 表」或提供 view。

---

## 2. v4 目標 canonical schema（To-Be）

### 2.1 必備表組（對齊 Gate 2）
- Execution / Audit：
  - `decisions`
  - `risk_checks`
  - `orders`
  - `fills`
  - `order_events`
  - `incidents`
- Observability：
  - `llm_traces`
  - `token_usage_monthly` / `token_budget_events`（若已存在則確認一致）
- Memory / Learning：
  - `working_memory`
  - `episodic_memory`
  - `semantic_memory`
  - `reflection_runs`
  - `strategy_proposals`
  - `strategy_versions`

### 2.2 與 execution tables 方案A 的相容策略
二選一（建議 Phase 2 結束前定案）：
- **方案 1：以 v4 canonical schema 為主**
  - 建立 `orders/fills/order_events`，並將 `execution_*` 視為 broker execution 細節表（可保留）。
- **方案 2：以 execution_* 為主，但提供對照 view**
  - 新增 `orders/fills/order_events` 的 `VIEW`（或 materialized-like 同步）映射到 `execution_*`，確保 Gate 2 可查詢。

---

## 3. 遷移分期（建議與 Refactor Phases 對齊）

### Phase 1（已完成）— 建表基礎與 WAL/分庫
- 若已完成：確認 `PRAGMA journal_mode=WAL`、兩庫存在、基本表可查。

### Phase 2（主攻）— 自主優化閉環所需表與欄位對齊
> 對應 v4：#24/#25/#26/#28/#29 + Gate 2/3

1. **引入 schema_versioning**（若尚無）
   - 新增 `schema_migrations`（id, name, applied_at, checksum）
   - 所有 migration 以檔名/ID 防重複。

2. **補齊/對齊 memory + reflection + proposals + versions**
   - 確認 3 層記憶表欄位（decay_score/is_archived/created_at 等）
   - `reflection_runs`：stage1/2/3 欄位（或 json_blob + stage tags）
   - `strategy_proposals`：proposal_json、status、review metadata、expiry
   - `strategy_versions`：active_version、parent_version、metrics snapshot、rollback metadata

3. **引入 authority/audit trail 欄位**
   - proposal/decision 需記錄 authority level、forbidden category 命中、人工審核者與時間。

### Phase 3 — Execution domain 正規化（若尚未完成）
> 對應 v4 Gate 2 的 execution 主鏈可查詢性

- 若現有僅有 `execution_*`：補 `orders/fills/order_events`（或提供 view）
- 若已有 `orders/fills/order_events`：補索引與外鍵一致性（decision_id → order_id → fill/event）

---

## 4. 回滾策略（Runbook）

### 4.1 原則
- **每次 migration 前必備份**（檔案層級）：
  - `data/sqlite/trades.db` → `trades.db.bak.<timestamp>`
  - `data/sqlite/ticks.db` → `ticks.db.bak.<timestamp>`
- **migration 必須可重複執行**：使用 `CREATE TABLE IF NOT EXISTS`、`CREATE INDEX IF NOT EXISTS`；欄位新增採 `ALTER TABLE ... ADD COLUMN` 並檢查是否已存在。

### 4.2 回滾觸發條件
- 服務無法啟動 / 核心查詢失敗
- Gate 2 db summary 無法產生或缺表
- 資料一致性檢查失敗（外鍵缺失、decision/order 無法關聯）

### 4.3 回滾步驟（可操作）
1. 停止所有交易/排程（包含 reflection/proposal job）。
2. 用 `.bak.<timestamp>` 覆蓋回原 db 檔。
3. 重新啟動並執行 smoke/dry-run 測試（至少涵蓋 decision → risk → trace）。
4. 產出事故記錄（incidents）與修復計畫。

---

## 5. 驗證與測試（Migration-level）
- **Schema 驗證**：列出所有必備表是否存在（sqlite_master）。
- **關聯驗證**：隨機抽樣 decision_id，能追到 risk_checks、orders、fills、order_events。
- **回滾演練**：在測試環境演練「升級→驗證→回滾→再驗證」。

> 具體測試命令與結果，應在每個 Phase 的 PR 回報中提供（符合強制回報格式）。
