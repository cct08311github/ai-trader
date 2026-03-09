---
globs: ["src/openclaw/**"]
---

# 交易管線與核心引擎

## 自動策略審查流程

```
08:30 cron → trigger_pm_review.py → POST /api/pm/review
  → Gemini 多空辯論 → episodic_memory + llm_traces → Telegram 通知

盤中每 3 分鐘 ticker_watcher:
  → signal_generator（MA 黃金交叉 + RSI + Trailing Stop）
  → risk_engine 7 層風控 → 自動下單（止損單跳過滑點/偏離）
  → concentration_guard（>60% 自動減倉 / 40-60% pending；dedup: 有 submitted 賣單時跳過）
  → proposal_reviewer（Gemini 審查 pending）→ approve/reject + Telegram
  → proposal_executor → SellIntent 清單 → ticker_watcher broker 執行 → mark_intent_executed/failed

16:35 EOD:
  → eod_ingest (OHLCV + T86 + MI_MARGN) → stock_screener → eod_analysis_reports
```

## 交易成本
- 手續費：`price × qty × 0.1425%`（買賣雙向）
- 證交稅：`price × qty × 0.3%`（sell only）
- T+2 交割日：買單自動填入 `orders.settlement_date`

## Telegram 通知
- `TELEGRAM_BOT_TOKEN` — 從 `~/.openclaw/.env` 載入
- `TELEGRAM_CHAT_ID` — 預設 `1017252031`

## Broker（Shioaji）
- 憑證：`frontend/backend/.env`（`SHIOAJI_API_KEY` / `SHIOAJI_SECRET_KEY`）
- 目前固定 `sj.Shioaji(simulation=True)` → 模擬帳戶下單
- 切換實際：`ticker_watcher.py` 中 `simulation=True` → `False`

## Reconciliation
- `broker_reconciliation` 診斷 `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED` → 自動關 `trading_enabled` + 寫 `auto_lock_*`
- Operator 必須確認後手動 re-enable

## Google Gemini SDK（v4.12.x+）
- 套件：`google-genai>=1.0`（非舊版 `google.generativeai`）
- API：`Client(api_key=...).models.generate_content(model=..., contents=..., config=GenerateContentConfig(...))`
- 測試 mock：`google.genai` 模組 + `Client` + `types.GenerateContentConfig`
- PM Review 診斷：直接 `curl -X POST .../api/pm/review` 驗證，不看 `daily_pm_state.json`
