# Sprint 2 設計方案：Signal Aggregator + Trading Engine + LLM Cache

**日期**：2026-03-05
**版本**：v1.0（已整合 Opus 第三方評審）
**狀態**：已核准，進入實作計劃

---

## 一、Sprint 2 目標

Sprint 0.5 + Sprint 1 + v4.11.x 完成後，系統已具備：
- EOD 日線驅動信號（signal_generator）
- Proposal 執行鏈（proposal_executor + concentration_guard）
- Gemini 自動審查 + Telegram 通知（proposal_reviewer）
- T+2 交割追蹤、交易成本計算

Sprint 2 目標：**讓決策品質與持倉生命週期管理同步升級**。

| 模組 | 核心價值 |
|------|---------|
| `lm_signal_cache` | LLM 信號快取層（底層基礎設施） |
| `signal_aggregator.py` | Regime-based 動態權重融合，提升決策品質 |
| `trading_engine.py` | 持倉狀態機 + 時間止損，解決殭屍倉問題 |

---

## 二、架構設計

### 2.1 資料流（整合後）

```
ticker_watcher 掃盤（每 3 分鐘）
  │
  ├─ 1. trading_engine.tick(symbol, conn)
  │       → 以 EOD 日為單位計算持倉天數
  │       → 觸發時間止損 → 生成減倉 proposal（不直接下單）
  │       → 更新 position_state（同一 transaction）
  │
  ├─ 2. signal_aggregator.aggregate(symbol, conn, snap)
  │       → market_regime.classify（讀 eod_prices）
  │       → signal_generator.compute_signal（技術面）
  │       → lm_signal_cache 讀取（LLM 面）
  │       → 漲跌停板過濾（snap 現價）
  │       → 加權 → Signal(action, score, regime, weights_used, reasons)
  │
  ├─ 3. risk_engine.evaluate()（一票否決層，不參與加權）
  │
  └─ 4. 執行訂單 or proposal_executor（現有邏輯不變）
```

### 2.2 職責邊界（Opus 修正）

ticker_watcher 現在扮演 orchestrator 角色（market data + 決策協調 + 執行）。
此為 Strangler Fig 漸進重構的過渡狀態，可接受。
**Sprint 3** 再抽出獨立的 `trade_coordinator.py`，降低 ticker_watcher 複雜度。

---

## 三、lm_signal_cache（DB 快取層）

### 3.1 設計決策

- **來源**：只快取 `strategy_committee` agent 的辯論結論
- **寫入時機**：strategy_committee 每次執行後，由 agent 主動寫入
- **讀取者**：signal_aggregator（每次掃盤）
- **Cache miss 策略**：回傳 neutral score（0.5），**不即時呼叫 LLM**
- **TTL**：`expires_at = 執行時間 + 1 小時`（strategy_committee 週一 07:30 跑，若盤中事件觸發則更新）

### 3.2 DB Schema

```sql
CREATE TABLE IF NOT EXISTS lm_signal_cache (
    cache_id    TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,         -- 股票代號（NULL 表示全市場方向）
    score       REAL NOT NULL,         -- 0.0（極度看空）~ 1.0（極度看多）
    source      TEXT NOT NULL,         -- 'strategy_committee' | 'pm_review'
    direction   TEXT,                  -- 'bull' | 'bear' | 'neutral'（人類可讀）
    raw_json    TEXT,                  -- 完整辯論摘要（供 llm_traces 查詢）
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lm_cache_symbol ON lm_signal_cache (symbol, expires_at);
```

### 3.3 全市場 vs 個股快取

- `symbol = NULL` → 全市場方向（strategy_committee 辯論台股大盤）
- `symbol = '2330'` → 個股層級（未來擴展，Sprint 2 僅實作全市場）
- signal_aggregator 先查個股快取，miss 則 fallback 全市場快取

---

## 四、signal_aggregator.py

### 4.1 輸入 / 輸出

```python
@dataclass(frozen=True)
class AggregatedSignal:
    action: str           # 'buy' | 'sell' | 'flat'
    score: float          # 0.0 ~ 1.0
    regime: str           # 'bull' | 'bear' | 'range'
    weights_used: dict    # {'technical': 0.5, 'llm': 0.2, 'risk_adj': 0.3}
    reasons: list[str]    # 人類可讀決策理由（寫入 llm_traces）
    limit_filtered: bool  # True = 被漲跌停板過濾，score 已壓低
```

### 4.2 Regime 權重 Mapping

```python
REGIME_WEIGHTS = {
    "bull":  {"technical": 0.50, "llm": 0.20, "risk_adj": 0.30},
    "bear":  {"technical": 0.30, "llm": 0.20, "risk_adj": 0.50},
    "range": {"technical": 0.40, "llm": 0.20, "risk_adj": 0.40},
}
```

**重要說明**：
- `risk_adj` 是「市場風險環境調整」信號（由 MarketRegimeResult.risk_multipliers 衍生），不是 risk_engine
- **risk_engine 維持一票否決層**，完全獨立於 signal_aggregator，不參與加權
- Regime 切換**不追溯**進行中訂單（已 ENTRY 的持倉以下單當時 regime 為準）

### 4.3 技術面信號轉換

signal_generator 輸出 `"buy" | "sell" | "flat"`，轉換為 score：
```python
SIGNAL_TO_SCORE = {"buy": 0.8, "flat": 0.5, "sell": 0.2}
```

### 4.4 漲跌停板過濾（Opus 新增）

```python
# 已漲停（漲幅 >= 9.5%）→ buy score 壓到 0.3（無法買入）
if snap.close >= snap.reference * 1.095:
    tech_score = min(tech_score, 0.3)
    reasons.append(f"{symbol} 漲停板，壓低 buy score")

# 已跌停（跌幅 <= -9.5%）→ sell score 壓到 0.7（流動性風險，不追殺）
if snap.close <= snap.reference * 0.905:
    tech_score = max(tech_score, 0.7)
    reasons.append(f"{symbol} 跌停板，sell score 調整（流動性警示）")
```

注意：跌停板時 sell score 不壓低（止損需求保留），但 risk_engine 的 slippage 豁免已確保平倉單不被攔截（v4.11.x 已完成）。

### 4.5 加權計算

```python
final_score = (
    weights["technical"] * tech_score +
    weights["llm"]       * llm_score  +     # cache miss → 0.5
    weights["risk_adj"]  * risk_adj_score    # MarketRegimeResult 衍生
)

# 轉換為 action
if final_score >= 0.65:   action = "buy"
elif final_score <= 0.35: action = "sell"
else:                      action = "flat"
```

---

## 五、trading_engine.py

### 5.1 持倉狀態機

```
CANDIDATE ──(風控通過+下單)──► ENTRY ──(成交確認)──► HOLDING
    │                           │                      │
    │ (1 交易日過期)             │ (部分成交)           ├─(時間止損/trailing)──► EXITING
    ▼                           ▼                      │
  [清除]                   HOLDING_PARTIAL             └─(全數成交)──► CLOSED
                           (等待剩餘成交)
```

**狀態說明：**

| 狀態 | 說明 |
|------|------|
| `CANDIDATE` | 信號觸發，尚未通過風控或尚未下單 |
| `ENTRY` | 訂單已提交，等待成交 |
| `HOLDING` | 完整持倉中 |
| `HOLDING_PARTIAL` | 部分成交（台股流動性低個股常見） |
| `EXITING` | 止損/止盈/時間止損提案已生成，等待執行 |
| `CLOSED` | 全數出清 |

### 5.2 時間止損規則（Opus 修正：以 EOD 日計算）

```
虧損持倉（current_price < avg_price）：
  → 連續 10 個交易日無出場信號 → 強制生成 POSITION_REBALANCE proposal（status=approved）

獲利持倉（current_price >= avg_price）：
  → 連續 30 個交易日無出場信號 → 生成 POSITION_REBALANCE proposal（status=pending，需人工審核）
```

**計算基準**：以 `eod_prices` 資料筆數計算持倉天數，不以 ticker_watcher 掃盤次數計算。
每個交易日收盤後，`eod_ingest` 寫入新資料 → trading_engine 在次日開盤第一次 tick 時更新天數。

### 5.3 position_events 表（持倉狀態 audit log）

```sql
CREATE TABLE IF NOT EXISTS position_events (
    event_id    TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    from_state  TEXT,                 -- NULL = 首次建立
    to_state    TEXT NOT NULL,
    reason      TEXT,                 -- 觸發原因（時間止損/trailing/手動）
    trading_day TEXT,                 -- YYYY-MM-DD（EOD 基準，非 timestamp）
    ts          INTEGER NOT NULL      -- 事件發生的 Unix ms（精確時間）
);
CREATE INDEX IF NOT EXISTS idx_pos_events_symbol ON position_events (symbol, ts);
```

### 5.4 整張限制（Opus 新增）

ENTRY 狀態觸發訂單時，qty 必須為 1000 的整數倍：
```python
qty = (position_sizing.calculate(...) // 1000) * 1000
if qty <= 0:
    # 不下單，維持 CANDIDATE 等下一輪
    return
```

### 5.5 Transaction 一致性（Opus 強調）

持倉狀態轉換與訂單建立**必須在同一個 SQLite transaction** 內完成：

```python
with conn:   # SQLite autocommit off
    conn.execute("INSERT INTO position_events ...")
    conn.execute("INSERT INTO orders ...")
    conn.execute("UPDATE positions SET state=? ...", (new_state,))
    # commit 或 rollback（任一失敗全部 rollback）
```

### 5.6 CANDIDATE 過期清理

CANDIDATE 狀態最多保留 **1 個交易日**。
`trading_engine.tick()` 每次呼叫時自動清理過期的 CANDIDATE：

```python
conn.execute(
    "DELETE FROM position_candidates WHERE trading_day < ?",
    (yesterday_trading_day,)
)
```

CANDIDATE 不存入 `positions` 表（`positions` 只記錄實際持倉），
改用獨立的 `position_candidates` 輕量表記錄待確認信號。

---

## 六、新增 DB 表彙整

| 表名 | 說明 | Sprint |
|------|------|--------|
| `lm_signal_cache` | LLM 快取（symbol, score, source, expires_at） | Sprint 2 |
| `position_events` | 持倉狀態轉換 audit log（trading_day 基準） | Sprint 2 |
| `position_candidates` | CANDIDATE 狀態輕量記錄（1 交易日過期） | Sprint 2 |

`positions` 表新增欄位：
```sql
ALTER TABLE positions ADD COLUMN state TEXT DEFAULT 'HOLDING';
ALTER TABLE positions ADD COLUMN entry_trading_day TEXT;   -- 進場交易日（EOD 基準）
```

---

## 七、延後至 Sprint 3 的項目（Opus 建議）

- **回填測試（Backfill）**：針對 `eod_prices` 歷史資料跑信號回測，驗證 regime weights 是否有效；Sprint 3 的 `performance_tracker.py` 一併實作
- **trade_coordinator 抽離**：將 ticker_watcher 的 orchestrator 邏輯獨立成 `trade_coordinator.py`，降低複雜度

---

## 八、測試策略

所有新模組遵循 TDD（先寫失敗測試，再實作）：

| 模組 | 關鍵測試案例 |
|------|------------|
| lm_signal_cache | 寫入/讀取/過期清理；cache miss 回傳 0.5 |
| signal_aggregator | Bull/Bear/Range 各 regime 加權正確；漲停板壓低 score；cache miss 仍可運作 |
| trading_engine | 狀態轉換正確；時間止損以 EOD 日計；CANDIDATE 過期清理；整張限制；Transaction rollback |

目標：新模組 100% 覆蓋，全套測試（262 → 目標 320+）繼續 CI 綠燈。
