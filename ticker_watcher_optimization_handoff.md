# ticker_watcher 完整功能優化 — 分析進度交接

**分析日期**: 2026-03-02
**基礎狀態**: 全部 145 個現有測試通過，ticker_watcher imports 正常

---

## 現狀評估

### 已實作
| 功能 | 說明 |
|------|------|
| 基本行情掃描 (mock/Shioaji) | 每 3 分鐘輪詢，`POLL_INTERVAL_SEC=180` |
| rule-based 訊號 | buy/sell/flat（close < ref*0.998 買；> avg*1.01 賣）|
| risk_engine 7層風控 | `evaluate_and_build_order` |
| SimBroker 下單 + 成交 | fills/orders/order_events 寫 DB |
| SSE trace 推前端 | `insert_llm_trace` → `/api/stream/logs` |
| Top movers 每日篩選 | `_screen_top_movers` 從 universe 選 max_active 支 |
| PM 每日授權檢查 | `get_daily_pm_approval()` |

### 缺口（待整合）
| 模組 | 缺口說明 | 優先級 |
|------|---------|--------|
| `trading_calendar.py` | 現在用自己的 `_is_market_open()`，未考慮國定假日、除息季 | P1 |
| `tw_session_rules.py` | 開盤(×2風險)/標準/收倉三時段風控差異化，未套用 | P1 |
| `cash_mode.py` / `market_regime.py` | 市場評級 C 應空手，未檢查 `CashModeManager` 狀態 | P1 |
| `order_slicing.py` | 應 TWAP/VWAP 分批下單，現在一次全下 | P2 |
| `take_profit.py` | 現在只有硬編碼 1% 止盈，應替換為 `take_profit.py` 的四類止盈邏輯 | P2 |
| `correlation_guard.py` | 無同板塊集中度檢查（v4 #22 要求 40% 上限）| P2 |
| `institution_ingest.py` | 篩選 top movers 未考慮籌碼健康度評分 | P3 |
| `test_ticker_watcher.py` | 完全缺失，需新建 | P1 |

---

## 建議實作順序

```
Phase 1（安全/正確性）
  ├─ trading_calendar 整合：替換 _is_market_open()
  ├─ tw_session_rules 整合：每輪掃描取得當前時段，調整 risk 參數
  ├─ cash_mode 整合：掃描前檢查 CashModeManager 狀態
  └─ test_ticker_watcher.py：基礎測試（market closed / PM not approved / signal gen）

Phase 2（執行品質）
  ├─ order_slicing 整合：approved 後用 TWAP/VWAP 切片
  └─ take_profit 替換：持倉管理改用 take_profit.py

Phase 3（訊號品質）
  └─ institution_ingest + correlation_guard 整合
```

---

## 關鍵檔案路徑

- 主檔案: `src/openclaw/ticker_watcher.py`
- 測試目錄: `src/tests/`（目前無 `test_ticker_watcher.py`）
- 相關模組: `src/openclaw/{trading_calendar,tw_session_rules,cash_mode,order_slicing,take_profit,correlation_guard,institution_ingest}.py`
- 專案根目錄: `/Users/openclaw/.openclaw/shared/projects/ai-trader/`

---

## 注意事項

- `SIM_NAV=2_000_000` / `SIM_CASH=1_800_000` 為硬編碼，考慮改為從 DB 讀取
- `positions: Dict[str, float]` 為 in-memory，重啟後清空（已記錄於 docstring，可接受）
- `tw_session_rules` 整合時注意：開盤 preopen 時段風控應更嚴格（×2 門檻）
