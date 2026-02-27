# OpenClaw v4 差異驅動重構 — 架構差異報告（As-Is vs To-Be）

> **Single Source of Truth**
> - v4 規範：`ref_doc/OpenClaw_優化審查報告_v4.docx`
> - 參考實作：`ref_doc/OpenClaw_v4_package/openclaw/`
> - Step 1 Gap Matrix：`gap_matrix.md`（v4 #1~#29）

## 0. 重構邊界（Boundary / Non-Goals）
- **目標**：把現有 OpenClaw AI-Trader 的「交易主鏈 + 自主優化核心 + 可觀測性/安全」重構到 v4 規範，並用可執行測試/乾跑證據驗收。
- **不在本次範圍**：
  - 未在 v4 #1~#29 列出的自由功能擴寫。
  - 任何繞過 Sentinel / Risk Engine / 授權邊界的捷徑實作。
  - 直接上線替換策略（必須走 #3 Shadow Mode、#26/#29 審核/授權）。

---

## 1. As-Is（目前架構）概覽
> 以 repo 目前已合併 Phase 1（PR #6/#7）為基礎：Sentinel 即時阻斷、token budget 模擬、LLM traces、重啟恢復協議、SQLite 初始化、Prompt injection guard、drawdown guard。

### 1.1 執行流程（Pipeline）
- `decision_pipeline`（決策產生）
- `risk_engine`（風控檢查：sentinel/drawdown/budget/…）
- `orders/broker`（下單與成交回寫）
- `llm_observability`（LLM traces）
- `database/*`（SQLite schema / migration scripts）

### 1.2 主要資料域（Domain）
- **風控域**：sentinel 熔斷、drawdown guard、token budget。
- **可觀測性域**：llm_traces、（部分）incident/稽核。
- **資料庫域**：已具備 v4 基礎 schema（WAL、分庫、部分 v4 表），另有「execution tables 方案A」migration 腳本。

### 1.3 As-Is 主要缺口（摘要）
> 詳細逐條以 `gap_matrix.md` 為準。
- **自主優化核心不足**：#24~#29 雖有部份骨架，但缺少完整狀態機、資料表對齊、反思與提案流程的驗收閉環。
- **工程化安全能力不足**：#12 secrets/keychain/IP allowlist、#13 model pin + smoke。
- **部署/變更治理不足**：#3 Shadow Mode 漸進部署 + 2h 自動回滾。

---

## 2. To-Be（v4 目標架構）概覽

### 2.1 v4 目標心智模型
v4 將系統分成三條主鏈：
1. **交易主鏈（Execution Mainline）**：Decision → Risk Checks → Order State Machine → Fills/Events → Audit/Incident
2. **自主優化主鏈（Autonomous Optimization Core）**：Memory（working/episodic/semantic）→ Reflection（3-stage）→ Strategy Proposal（JSON schema）→ Review/Authority Boundary → Strategy Versioning
3. **可觀測性/安全主鏈（Observability & Security）**：llm_traces 全量、prompt injection guard、secrets 管理、模型版本鎖定、smoke 測試

### 2.2 目標模組分層（建議邏輯分層，不代表一定要新增 package）
- **Domain Layer（純規則/狀態機，deterministic）**
  - Risk Engine / Sentinel / Drawdown / Budget / Authority
  - Order state machine（submitted/partial/filled/cancelled/rejected）
- **Application Layer（use-cases orchestration）**
  - Decision pipeline（整合 debate/news guard/LLM calls）
  - Reflection job（23:00）
  - Proposal review UI（Telegram buttons）
- **Infrastructure Layer（IO）**
  - SQLite stores（decision/order/fill/event/memory/reflection/proposal/version/trace）
  - Broker adapter
  - Secrets provider（Keychain + env fallback）
  - Model registry / smoke runner

### 2.3 v4 必備資料庫觀測面（規範 Gate 2 對齊）
必須能被查到（同一個 trades execution DB）：
- `decisions`
- `risk_checks`
- `orders` / `fills` / `order_events`（或等價 execution domain tables）
- `llm_traces`
- `working_memory` / `episodic_memory` / `semantic_memory`
- `reflection_runs`
- `strategy_proposals`
- `strategy_versions`

---

## 3. 參考實作（v4_package）與現況對比

### 3.1 參考實作模組清單
`ref_doc/OpenClaw_v4_package/openclaw/`：
- `decision_pipeline.py`, `risk_engine.py`, `sentinel.py`, `drawdown_guard.py`, `token_budget.py`
- `memory_store.py`, `reflection_loop.py`, `proposal_engine.py`
- `llm_observability.py`, `prompt_security.py`, `secrets.py`
- `orders.py`, `order_store.py`, `risk_store.py`, `audit_store.py`, `broker.py`
- `bootstrap_and_dry_run.py`, `main.py`, `news_guard.py`, `position_sizing.py`, `pm_debate.py`, `eod_ingest.py`

### 3.2 差異類型（重點）
1. **流程閉環差異**
   - As-Is：多數功能存在，但「反思 → 提案 → 授權 → 版本」閉環缺少可驗收狀態機。
   - To-Be：#24~#29 必須串成可回放、可稽核、可回滾閉環。

2. **資料對齊差異**
   - As-Is：既有 `database/add_execution_tables.py` 為 execution 方案A，但其 FK 依賴 `orders` 等表名；需與最終 schema 統一。
   - To-Be：以 v4 Gate 2 的可查詢表組為準，execution tables 必須能覆蓋 orders/fills/events 或提供 view/對照表。

3. **安全/治理差異**
   - As-Is：prompt injection guard 已有，但 secrets/model pin/shadow deployment 缺。
   - To-Be：#12/#13/#3 需補齊，且應影響 decision 的 gate（例如：未 pin 模型禁止 live）。

---

## 4. 架構落地策略（設計原則）
- **deterministic gate 優先**：Risk Engine / Authority Boundary 必須先能在不依賴 LLM 的情況下硬阻斷。
- **事件溯源（auditability）**：任何「決策/風控/下單/反思/提案」必須有可回放的 db record。
- **向後相容 + 可回滾**：migration 必須 idempotent；新舊表共存時以雙寫或 view 方式過渡。
- **測試先行**：每個 v4_id 必須能連到 `gap_matrix.md` 的 acceptance_criteria + test_case_id。

---

## 5. 風險與對策（架構層級）
- **Schema 演進風險**：execution domain 表名/關聯不一致 → 用 migration plan 定義最終 canonical schema + 兼容 view。
- **閉環流程風險**：反思/提案涉及 LLM 不確定性 → 以 schema 驗證 + authority gate + 明確狀態機降低風險。
- **部署風險**：策略改動直接影響資金 → 強制 Shadow Mode + 2h rollback（#3）。
