---
globs: ["data/**", "**/db.py", "**/db_*.py", "**/*_db.*"]
---

# 資料庫 Schema

**路徑**：`data/sqlite/trades.db`（唯一共用 SQLite）

| 表名 | 說明 |
|------|------|
| `orders` | 訂單（**order_id** PK TEXT, symbol, side, qty, price, status, **ts_submit TEXT ISO**, settlement_date） |
| `fills` | 成交明細（order_id FK, qty, price, fee, tax） |
| `positions` | 持倉（symbol PK, **quantity**, **avg_price**, current_price, unrealized_pnl, state, high_water_mark, entry_trading_day） |
| `decisions` | AI 決策紀錄 |
| `llm_traces` | LLM 呼叫 trace（v4：created_at INTEGER ms NOT NULL） |
| `strategy_proposals` | 策略提案（proposal_id, generated_by, target_rule, rule_category, status, confidence, created_at INTEGER ms）— **無 symbol 欄** |
| `risk_checks` | 風控檢查紀錄 |
| `incidents` | 異常事件 |
| `risk_limits` | 風控參數 |
| `eod_analysis_reports` | 盤後分析快照（**trade_date** PK TEXT, generated_at INTEGER ms） |
| `eod_prices` | 每日 OHLCV（trade_date/symbol/open/high/low/close/volume） |
| `system_candidates` | 選股結果（symbol, trade_date, label, score, source, reasons JSON） |
| `lm_signal_cache` | LLM 信號快取（cache_id, symbol, score, direction, expires_at） |
| `position_events` | 持倉事件（symbol, from_state, to_state, reason, trading_day） |
| `eod_institution_flows` | 法人買賣超（per symbol per date） |
| `eod_margin_data` | 融資融券（per symbol per date） |

> 舊版 `trades` 表已廢棄，API 改用 `orders JOIN fills`

## Schema 陷阱
- `orders.ts_submit`：TEXT ISO（非 epoch）
- `positions`：`quantity`/`avg_price`（非 qty/avg_cost）
- `strategy_proposals`：**無 symbol 欄**；`created_at`/`decided_at` INTEGER **ms**
- Timestamp 慣例：所有 proposal 用 ms（`timestamp() * 1000`）
