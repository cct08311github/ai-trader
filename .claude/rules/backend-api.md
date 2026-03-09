---
globs: ["frontend/backend/**"]
---

# FastAPI 後端參考

## API 路由

| Router | 路徑前綴 | 說明 |
|--------|---------|------|
| auth | `/api/auth` | 登入取得 Bearer token |
| portfolio | `/api/portfolio` | 持倉、交易紀錄（`orders JOIN fills`） |
| strategy | `/api/strategy` | 提案、LLM traces |
| pm | `/api/pm` | PM review 觸發 |
| system | `/api/system` | 系統狀態開關 |
| chat | `/api/chat` | AI 助手 SSE 串流 |
| stream | `/api/stream` | Log SSE 串流 |
| control | `/api/control` | 緊急停止、模式切換 |
| settings | `/api/settings` | 系統設定讀寫 |
| analysis | `/api/analysis` | 盤後分析快照（latest/dates/{date}） |
| chips | `/api/chips` | 法人籌碼：institution-flows / margin / summary / dates |
| reports | `/api/reports` | 投資報告結構化資料（`/context?type=morning\|evening\|weekly`） |

## Portfolio 路由
- `GET /api/portfolio/quote/{symbol}` — 即時快照；Shioaji 失敗 fallback `eod_prices`（`source: "eod"`）
- `GET /api/portfolio/kline/{symbol}?days=60` — K 線 OHLCV（查 `eod_prices`）
- `GET /api/portfolio/quote-stream/{symbol}` — BidAsk SSE 五檔

## Reports 路由
- `GET /api/reports/context?type=morning|evening|weekly` — 需 Bearer token
- 回傳：`status`, `report_type`, `real_holdings`, `simulated_positions`, `technical_indicators`, `institution_chips`, `recent_trades`, `eod_analysis`, `system_state`
- `PORTFOLIO_JSON_PATH` 未設或不存在 → `real_holdings.holdings` 回空陣列（非錯誤）
- **Consumer Path**：
  - Python: `from openclaw.report_context_client import fetch_and_format_report_context`
  - CLI: `PYTHONPATH=src bin/venv/bin/python tools/fetch_report_context.py --type morning`

## Auth Middleware
- 強制 `Authorization: Bearer <token>`；AUTH_TOKEN 未設 → 自動生成隨機 token（非停用）
- SSE/URL 按鈕路徑：`/api/stream/` 和 `/proposals/` 額外接受 `?token=` query param

## DB 連線
- `db.get_conn()` = **readonly pool**（`mode=ro`）— 僅 SELECT
- `db.get_conn_rw()` = read-write — INSERT/UPDATE/DELETE 必須用此
- 陷阱：寫入用了 `get_conn()` → `OperationalError: attempt to write a readonly database`

## Telegram 提案審查（tg_approver）
- 通知發送至 `TELEGRAM_CHAT_ID`（預設 `-1003772422881`）
- URL 按鈕方案（非 callback_data）→ 直接打 API
- approve/reject：`GET /api/strategy/proposals/{id}/approve?token=...`
- 修改後需 `pm2 restart ai-trader-api`（middleware import-time 載入）
- `duplicate_alerts` → Telegram 顯示「重複告警」與相似度

## Strategy Committee
- 不再預設保守結論；最終方向依 Bull/Bear 證據
- `proposal_json` 保存 `committee_context`（market_data/bull/bear/arbiter）
- `STRATEGY_DIRECTION` 12 小時內去重：高相似 → suppress，但仍寫 `llm_traces` duplicate guard
