# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 台股 AI 自動交易系統。詳細規範見 `.claude/rules/` 條件載入規則檔。

---

## ⚠️ 紅線禁止事項

- **禁止**手動修改 `config/system_state.json` — 一律透過 API 操作
- **禁止**硬編碼路徑 `/Users/openclaw` — 用 `Path(__file__)` 或 `OPENCLAW_ROOT_ENV`
- **禁止** commit secrets、API keys、`.env` 內容
- Deploy Baselines（`capital.json`, `drawdown_policy_v1.json` 等）修改**必須**走 PR
- 倉位調整、策略變更前**必須確認**

---

## 協作方針

**核心目標**：讓系統成為可靠、持續進化的交易助手。
**目前階段**：優化期（Auto-Memory Learning）

### 工作方式
- 先給結論，再給理由；偏實務、可執行
- 系統變更前先說明影響、風險與回滾方式

### Auto-Memory 學習重點
留意並記錄長期重複出現的操作模式：
- 交易節奏與決策流程
- 任務拆解與策略層級
- 對風險、異常與市場波動的反應

**原則**：只記長期模式，不記一次性操作。不確定是否該記憶 → 先詢問。

---

## 系統概覽

| 層級 | 路徑 | 說明 |
|------|------|------|
| 核心引擎 | `src/openclaw/` | Python：決策管線、PM 辯論、風控、選股 |
| FastAPI 後端 | `frontend/backend/` | REST API + SSE，SQLite |
| React 前端 | `frontend/web/` | Vite + Tailwind，即時儀表板 |
| 設定 | `config/` | system_state.json、daily_pm_state.json、watchlist.json |
| 資料庫 | `data/sqlite/trades.db` | 唯一共用 SQLite |

**分支策略**：`main` 是唯一活躍主線，feature branch per issue。

---

## 快速測試指令

```bash
pytest -q                                            # 核心引擎（repo root）
cd frontend/backend && python -m pytest tests/ -q    # FastAPI
cd frontend/web && npm test -- --run                  # 前端（vitest）
```

詳細測試規則見 `.claude/rules/testing.md`。

---

## 設計文件

- `doc/plans/` — 設計文件與實作計劃
- 命名：`YYYY-MM-DD-<feature>-design.md` / `-plan.md`

---

## 規則檔索引（`.claude/rules/`）

| 規則檔 | 觸發條件 | 內容 |
|--------|---------|------|
| `dev-environment.md` | — | 快速啟動、環境變數、Ports、Python venv |
| `architecture.md` | — | 核心引擎關鍵檔案對照表 |
| `services.md` | — | PM2 服務清單、Portable Path Convention |
| `tools-commands.md` | — | 常用 CLI 指令（CI / 測試 / 復盤 / PM2） |
| `safety-model.md` | — | 交易啟動條件、模式切換、Runtime State |
| `backend-api.md` | `frontend/backend/**` | API 路由表、Auth、DB 連線、Telegram、Reports |
| `trading-pipeline.md` | `src/openclaw/**` | 交易流程、成本、Broker、Gemini SDK |
| `frontend-structure.md` | `frontend/web/**` | 頁面、UI 約束、Drawer、主題系統 |
| `testing.md` | `tests/**`, `**/tests/**` | pytest/vitest 必讀規則 |
| `db-schema.md` | `data/**`, `**/db.py` | 完整資料表 Schema + 陷阱 |
