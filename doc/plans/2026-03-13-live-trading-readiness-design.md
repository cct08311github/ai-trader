# Live Trading Readiness — 雙軌並行設計

> 日期：2026-03-13
> 目標：補完執行鏈 + 建回測框架，讓模擬盤跑通完整交易循環，同時快速迭代策略參數

---

## 背景與動機

系統就緒度約 6/10。架構完善（風控 7 層、broker adapter、DB schema），但存在結構性斷層：
- Sell 信號無自動觸發（只有 buy）
- Signal Aggregator 寫了但未接線
- Trailing Stop 函數存在但 ticker_watcher 未呼叫
- 無回測框架，策略參數無法快速迭代驗證

用戶反饋：策略不夠靈活，模擬盤仍需驗證。

---

## 方案選擇

**採用方案 B：雙軌並行**

- 軌道 1（Runtime）：執行鏈補完，改 ticker_watcher / risk_engine
- 軌道 2（Offline）：回測引擎 + 策略優化，純離線新增檔案

兩軌無依賴可完全平行。交匯點在 Sprint 3：最優參數回寫 config。

---

## 軌道 1：執行鏈補完

### 1A: Sell 自動觸發

**改動檔案**：`ticker_watcher.py`
**風險等級**：高（核心交易迴圈）

在 3 分鐘輪詢中，對每個已持倉 symbol 呼叫 `signal_logic.evaluate_exit()`：

```python
for symbol, pos in current_positions.items():
    if symbol in locked_symbols:
        continue  # locked = 禁賣白名單，可買不可賣
    closes = get_closes(symbol)
    exit_signal = signal_logic.evaluate_exit(
        closes, pos.avg_price, pos.high_water_mark, params
    )
    if exit_signal.action == "sell":
        # 建構 Decision 物件（risk_engine 的輸入是 Decision，非 OrderCandidate）
        decision = Decision(
            symbol=symbol, side="sell", qty=pos.quantity,
            reason=exit_signal.reason, opens_new_position=False
        )
        # evaluate_and_build_order 需要完整的 5 參數
        result = risk_engine.evaluate_and_build_order(
            decision, market_state, portfolio_state, limits, system_state
        )
        if result.approved:
            broker.submit_order(result.order_candidate)
```

**全倉 vs 部分出場**：目前所有 exit signal 一律全倉賣出（`qty=pos.quantity`）。
未來可擴展為部分出場（例如 trailing_stop 先賣 50%），但 MVP 階段先以全倉為主。

**Sell 理由與處理方式**：

| 理由 | 處理 | 說明 |
|------|------|------|
| `stop_loss` | 直接執行 | 機械式止損，延遲確認會錯過出場 |
| `take_profit` | 直接執行 | 機械式止盈 |
| `trailing_stop` | 直接執行 | 鎖利機制 |
| `time_stop` | 走 proposal 審查 | 持倉超 N 天無正報酬，需人工判斷 |

### 1B: 跌停止損例外

**改動檔案**：`risk_engine.py`
**風險等級**：高（風控層）
**狀態**：部分已實裝 — `risk_engine.py` line 273-287 已有平倉跳過 price deviation 的邏輯。
需驗證現有實作是否完整覆蓋 slippage 檢查，若不足則補齊。

預期行為：

```python
if candidate.opens_new_position:
    if slippage > limits["max_slippage_pct"]:
        return reject("SLIPPAGE_EXCEEDED")
    if price_dev > limits["max_price_deviation_pct"]:
        return reject("PRICE_DEVIATION_EXCEEDED")
# 平倉單直接通過，但仍保留 ORDER_RATE_LIMIT 和 BROKER_CONNECTIVITY 檢查
```

**重要規則**：LOCK_PROTECTION 層只攔 sell，buy locked symbol 直接放行。

### 1C: Signal Aggregator 接線

**改動檔案**：`ticker_watcher.py`
**風險等級**：中

替換簡單 buy/flat 邏輯，改為呼叫現有的 `signal_aggregator.aggregate()`：

```python
# 現有 API 簽名：aggregate(conn, symbol, snap, position_avg_price, high_water_mark)
# 內部自行呼叫 compute_signal() + classify_market_regime()
agg_result = signal_aggregator.aggregate(
    conn=db_conn,
    symbol=symbol,
    snap=current_snapshot,           # 盤中即時行情
    position_avg_price=pos.avg_price if pos else None,
    high_water_mark=pos.high_water_mark if pos else None,
)
# agg_result: AggregatedSignal(action, score, regime, components)
```

**注意**：不需外部傳入 regime 或 technical signal — aggregator 內部自行計算。
ticker_watcher 只需提供 DB connection 和即時行情快照。

### 1D: Trailing Stop 執行

**改動檔案**：`ticker_watcher.py`

每輪更新 `positions.high_water_mark`（取 max(current, hwm)）。
signal_logic.evaluate_exit 已支援 trailing，只需在 1A 的迴圈中接線。

### 1E: 集中度自動減倉

**改動檔案**：`ticker_watcher.py`

每輪計算 `symbol_weight = position_value / NAV`：
- \> 60%：自動 sell 10% 持倉（locked symbols 除外）
- 40-60%：產生 proposal 待審查
- < 40%：正常

**需新增功能**：現有 `concentration_guard.py` 無 locked symbols 過濾邏輯。
需修改 `concentration_guard.check_concentration()` 加入 locked 白名單參數，
對 locked symbol 只產生 warning log 而不產生 sell proposal，避免無法執行的提案。

### 1F: Live 切換開關

**改動檔案**：`ticker_watcher.py`, `broker.py`
**風險等級**：高

新增環境變數 `TRADING_MODE=simulation|live`（預設 simulation）：

```python
simulation = os.getenv("TRADING_MODE", "simulation") == "simulation"
api = sj.Shioaji(simulation=simulation)
```

Live 模式安全要求：
- `trading_enabled=true` AND `.EMERGENCY_STOP` 不存在
- 切換 live 自動停用 auto trading（需手動 re-enable）
- 啟動時 log 明確標示 `[LIVE MODE]` 或 `[SIMULATION]`
- Reconciliation 整合：live 模式下 `broker_reconciliation` 的 `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
  不再視為預期差異（simulation 時 broker 持倉為空是正常的，live 不是）。
  需確保 `resolved_simulation` 標記在 live 模式不被設定。

### 1G: ShioajiAdapter 完整實裝

**改動檔案**：`broker.py`
**風險等級**：高

- 完成 `poll_order_status`（Shioaji callback 轉 OrderStatus）
- Partial fill 分批更新 fills 表
- Submit 失敗：3 次 exponential backoff retry 後放棄，記 incident
- 錯誤映射已有（`map_shioaji_error_to_reason_code()`）

---

## 軌道 2：回測引擎與策略優化

### 2A: 回測引擎 MVP

**新增檔案**：`src/openclaw/backtest_engine.py`
**風險等級**：低（離線，不碰 production code）

```python
@dataclass
class BacktestConfig:
    symbols: list[str]
    start_date: str
    end_date: str
    initial_capital: float        # 1_000_000
    signal_params: SignalParams
    max_positions: int            # 同時持倉上限
    max_single_pct: float         # 單檔上限 0.20

@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[float]
    metrics: PerfMetrics

def run_backtest(config: BacktestConfig, db_path: str) -> BacktestResult:
```

日線級回測，每個交易日：
1. 已持倉 → `signal_logic.evaluate_exit()` → sell（locked symbols 除外）
2. 未持倉 → `signal_logic.evaluate_entry()` → buy
3. 經 `cost_model` 計算手續費 + 稅
4. 更新虛擬持倉、現金、淨值

**資料來源**：`eod_prices` 表（已有 OHLCV 日線）。

**與 production 共用純函數**：
- `signal_logic.evaluate_entry()` / `evaluate_exit()`
- `cost_model.calculate_buy_cost()` / `calculate_sell_proceeds()`

**信號邏輯差異說明**：回測 MVP 只使用純技術面信號（`signal_logic`），
不整合 `signal_aggregator`（含 LLM score + regime 加權）。原因：
- LLM 信號無歷史資料，無法回測
- Regime 加權可在 Phase 2 加入（用大盤 MA 歷史資料模擬 regime）
- MVP 目標是驗證技術面參數的有效性，而非完整 production 邏輯

回測結果應理解為「純技術面的策略基線」，production 表現會因 aggregator 加權而有差異。

### 2B: 績效指標

**新增檔案**：`src/openclaw/perf_metrics.py`

```python
@dataclass
class PerfMetrics:
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float           # rf=1.5% 台灣定存
    max_drawdown_pct: float
    max_drawdown_days: int
    win_rate: float
    profit_factor: float
    avg_holding_days: float
    total_trades: int
    avg_profit_per_trade: float
```

### 2C: Grid Search 參數掃描

**新增檔案**：`src/openclaw/param_optimizer.py`

```python
PARAM_GRID = {
    "ma_short": [3, 5, 8],
    "ma_long": [15, 20, 30],
    "rsi_entry_max": [60, 70, 80],
    "stop_loss_pct": [0.03, 0.05, 0.07],
    "take_profit_pct": [0.05, 0.08, 0.10],
    "trailing_pct": [0.03, 0.05, 0.08],
}
# 729 組合，ProcessPoolExecutor 平行化
# 預估執行時間：每組合 ~1s（10 支股票 × 300 交易日）
# 729 組合 / 8 cores ≈ 90s；50 支股票池 ≈ 8 分鐘
# 若超過 15 分鐘，啟用早期截斷：in-sample Sharpe < 0.5 的組合跳過 out-of-sample
```

**防過擬合**：
- 資料切分 70% in-sample / 30% out-of-sample
- 只選 out-of-sample Sharpe > 1.0 的組合
- 取前 3 名的交集參數帶（非單一最優）

### 2D: 參數回寫

最優參數寫入 `config/signal_params.json`（Git tracked）：

```json
{
  "optimized_at": "2026-03-15",
  "in_sample": "2025-01-01 ~ 2026-01-31",
  "out_of_sample": "2026-02-01 ~ 2026-03-13",
  "params": { "ma_short": 5, "ma_long": 20, ... },
  "out_of_sample_sharpe": 1.32,
  "out_of_sample_mdd": -0.087
}
```

`signal_logic` 和 `ticker_watcher` 讀此檔取參數，fallback 到硬編碼預設值。

---

## Sprint 排程

### Sprint 1（P0 + 回測 MVP）

| 軌道 | 任務 | 估計複雜度 |
|------|------|-----------|
| 1 | 1A Sell 自動觸發 | 中 |
| 1 | 1B 跌停止損例外 | 低 |
| 1 | 1C Signal Aggregator 接線 | 中 |
| 2 | 2A 回測引擎 MVP | 中 |
| 2 | 2B 績效指標計算 | 低 |

### Sprint 2（P1 + 策略優化）

| 軌道 | 任務 | 估計複雜度 |
|------|------|-----------|
| 1 | 1D Trailing Stop 執行 | 低（1A 已鋪路） |
| 1 | 1E 集中度自動減倉 | 中 |
| 1 | 1F Live 切換開關 | 中 |
| 2 | 2C Grid Search 參數掃描 | 中 |
| 2 | 2D 最優參數回寫 config | 低 |

### Sprint 3（收斂）

| 軌道 | 任務 | 估計複雜度 |
|------|------|-----------|
| 1 | 1G ShioajiAdapter 完整實裝 | 高 |
| — | 回測最優參數 feed 回模擬盤觀察 | — |

---

## 任務依賴圖

```
軌道 1（Runtime）:
1A (Sell觸發) ─┐
1B (跌停例外) ─┤─→ 1D (Trailing Stop) ─→ 1F (Live開關) ─→ 1G (ShioajiAdapter)
1C (Agg接線)  ─┘         ↑
                          │ 1E (集中度) 可平行

軌道 2（Offline）:
2A (回測MVP) ─→ 2B (績效指標) ─→ 2C (Grid Search) ─→ 2D (參數回寫)

軌道 1 與 2 無交叉依賴，可完全平行。
```

---

## 關鍵規則備忘

- **Locked symbols**：可買入，不可賣出。1A exit evaluation 跳過 locked；risk_engine LOCK_PROTECTION 只攔 sell。
- **Sell 確認**：stop_loss / take_profit / trailing_stop 直接執行，不走 Telegram。time_stop 走 proposal 審查。
- **回測粒度**：日線級（eod_prices），與盤中 3 分鐘輪詢粒度不同但足以驗證策略方向。
- **防過擬合**：70/30 資料切分，out-of-sample Sharpe > 1.0 才採用。

---

## 測試策略

每個任務對應獨立測試：

| 任務 | 測試檔案 | 重點 |
|------|---------|------|
| 1A | `test_ticker_watcher.py` | sell 觸發 + locked 跳過 |
| 1B | `test_risk_engine.py` | 平倉跳過 slippage；買入 locked 放行 |
| 1C | `test_signal_aggregator.py` | regime 分類 + 權重計算 |
| 1D | `test_ticker_watcher.py` | hwm 更新 + trailing 觸發 |
| 1E | `test_concentration_guard.py` | >60% auto sell + locked 例外 |
| 1F | `test_ticker_watcher.py` | env 切換 + fail-safe |
| 1G | `test_broker.py` | partial fill + retry + error mapping |
| 2A | `test_backtest_engine.py` | 已知數據的確定性結果 |
| 2B | `test_perf_metrics.py` | 手算驗證 Sharpe/MDD |
| 2C | `test_param_optimizer.py` | 70/30 切分 + 排序邏輯 |

**整合測試**：Sprint 1 完成後新增 `test_ticker_watcher_integration.py`，
模擬完整 3 分鐘輪詢週期：signal_logic → signal_aggregator → risk_engine →
concentration_guard → broker submit。用 mock broker 驗證 buy + sell 的端到端流程，
確保多模組交互正確（特別是 locked symbol 過濾在各層的行為一致）。
