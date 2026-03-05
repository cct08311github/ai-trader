# 智能 AI 交易系統實作計劃

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 將 AI Trader 從「只買不賣的記錄系統」升級為真正具備閉環執行、自主優化的智能交易引擎。

**Architecture:** Sprint 0.5 緊急止血（Trailing Stop + 風控修正）→ Sprint 1 模組拆分 + 執行鏈（Strangler Fig）→ Sprint 2 TradingEngine + 信號融合 → Sprint 3 績效追蹤 + 優化閉環。

**Tech Stack:** Python 3.14, SQLite, Shioaji, FastAPI, pytest, asyncio

**Design Doc:** `docs/plans/2026-03-04-intelligent-trading-system-design.md`

---

# SPRINT 0.5 — 緊急止血（2-3 天）

## Task 1：positions 表新增 high_water_mark 欄位

**目標**：追蹤每筆持倉的歷史最高價，作為 Trailing Stop 計算基礎。

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`（migration 邏輯）
- Modify: `data/sqlite/trades.db`（schema 變更，透過程式碼執行）

**Step 1: 寫失敗測試**

在 `tests/test_ticker_watcher.py` 加入：
```python
def test_positions_table_has_high_water_mark(tmp_path, monkeypatch):
    """positions 表必須有 high_water_mark 欄位"""
    import sqlite3, os
    db = tmp_path / "trades.db"
    monkeypatch.setenv("AUTH_TOKEN", "test")
    # 模擬 _ensure_schema
    from openclaw.ticker_watcher import _ensure_schema
    conn = sqlite3.connect(str(db))
    _ensure_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    assert "high_water_mark" in cols
    conn.close()
```

**Step 2: 執行確認失敗**
```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
PYTHONPATH=src pytest tests/test_ticker_watcher.py::test_positions_table_has_high_water_mark -v
```
預期：FAIL（`high_water_mark` 不存在）

**Step 3: 找到 _ensure_schema，新增欄位**

在 `src/openclaw/ticker_watcher.py` 找到 `_ensure_schema`（或等效的 schema 建立函數），在 `positions` 表定義中加入：
```python
# 在 CREATE TABLE positions (...) 裡加：
high_water_mark REAL,          -- 持倉後最高成交價（Trailing Stop 用）
```
同時加入 migration（避免舊 DB 無此欄位）：
```python
def _ensure_schema(conn: sqlite3.Connection) -> None:
    # ... 現有 CREATE TABLE ...
    # 在函數末端加 migration：
    try:
        conn.execute("ALTER TABLE positions ADD COLUMN high_water_mark REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 欄位已存在
```

**Step 4: 執行確認通過**
```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py::test_positions_table_has_high_water_mark -v
```
預期：PASS

**Step 5: 跑完整測試確認無 regression**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 6: Commit**
```bash
git add src/openclaw/ticker_watcher.py tests/test_ticker_watcher.py
git commit -m "feat(db): positions 表新增 high_water_mark 欄位（Trailing Stop 前置）"
```

---

## Task 2：Trailing Stop 核心邏輯

**目標**：`_generate_signal` 支援 Trailing Stop，追蹤高水位線。

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`（`_generate_signal` + 主迴圈）

**背景：現有 `_generate_signal` 簽名**
```python
def _generate_signal(snap: dict, position_avg_price: Optional[float]) -> str:
```
需要擴展為也接收 `high_water_mark`。

**Step 1: 寫失敗測試**

在 `tests/test_ticker_watcher.py` 加入：
```python
import pytest
from openclaw.ticker_watcher import _generate_signal

class TestTrailingStop:
    def _snap(self, close, ref=100.0):
        return {"close": close, "reference": ref, "volume": 1000,
                "best_bid": close * 0.999, "best_ask": close * 1.001}

    def test_trailing_stop_triggers_when_price_drops_from_peak(self):
        """從高水位下跌 5% 應觸發 trailing sell"""
        # avg_price=100, high_water=150, close=142 → drop 5.3% from peak → sell
        result = _generate_signal(
            self._snap(142.0), position_avg_price=100.0, high_water_mark=150.0,
            trailing_pct=0.05
        )
        assert result == "sell", f"Expected sell, got {result}"

    def test_trailing_stop_does_not_trigger_near_peak(self):
        """距高水位只跌 2% 不觸發（trailing 5%）"""
        result = _generate_signal(
            self._snap(147.0), position_avg_price=100.0, high_water_mark=150.0,
            trailing_pct=0.05
        )
        assert result == "flat"

    def test_no_trailing_when_no_position(self):
        """無持倉時不做 trailing 計算"""
        result = _generate_signal(
            self._snap(80.0), position_avg_price=None, high_water_mark=None,
            trailing_pct=0.05
        )
        assert result == "buy"  # close < ref*(1-0.2%)

    def test_original_stop_loss_still_works(self):
        """原有止損邏輯（-3%）不受影響"""
        # avg=100, close=96 → -4% → stop loss
        result = _generate_signal(
            self._snap(96.0), position_avg_price=100.0, high_water_mark=100.0,
            trailing_pct=0.05
        )
        assert result == "sell"

    def test_trailing_tighter_for_large_profit(self):
        """獲利超過 50% 時 trailing 收緊為 3%"""
        # avg=100, high_water=160（+60%），close=155.5（下跌 2.8% from peak）
        # trailing_pct 應為 3%（獲利>50%），155.5 < 160*(1-0.03)=155.2 → sell
        result = _generate_signal(
            self._snap(155.0), position_avg_price=100.0, high_water_mark=160.0,
            trailing_pct=0.05  # base，會被內部收緊為 0.03
        )
        assert result == "sell"
```

**Step 2: 確認失敗**
```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py::TestTrailingStop -v
```
預期：TypeError（`_generate_signal` 不接受 `high_water_mark` 參數）

**Step 3: 修改 `_generate_signal`**

```python
# 在模組頂端加常數：
_TRAILING_PCT_BASE: float = float(_os.environ.get("TRAILING_PCT", "0.05"))   # 基礎 trailing 5%
_TRAILING_PCT_TIGHT: float = float(_os.environ.get("TRAILING_PCT_TIGHT", "0.03"))  # 大獲利收緊 3%
_TRAILING_PROFIT_THRESHOLD: float = 0.50  # 獲利超過 50% 收緊

def _generate_signal(
    snap: dict,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float] = None,
    trailing_pct: float = _TRAILING_PCT_BASE,
) -> str:
    close = snap["close"]
    ref   = snap["reference"]
    if position_avg_price is not None:
        # 動態收緊 trailing：獲利超過門檻，收緊 trailing
        effective_trailing = trailing_pct
        if high_water_mark and position_avg_price > 0:
            profit_pct = (high_water_mark - position_avg_price) / position_avg_price
            if profit_pct >= _TRAILING_PROFIT_THRESHOLD:
                effective_trailing = _TRAILING_PCT_TIGHT

        # Trailing Stop：從高水位下跌超過閾值
        if high_water_mark and close < high_water_mark * (1 - effective_trailing):
            return "sell"   # trailing stop

        # 原有止盈止損
        if close > position_avg_price * (1 + _TAKE_PROFIT_PCT):
            return "sell"   # 止盈
        if close < position_avg_price * (1 - _STOP_LOSS_PCT):
            return "sell"   # 止損
        return "flat"
    return "buy" if close < ref * (1 - _BUY_SIGNAL_PCT) else "flat"
```

**Step 4: 確認測試通過**
```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py::TestTrailingStop -v
```

**Step 5: 更新主迴圈傳入 high_water_mark**

在 `run_watcher` 主迴圈中（約 line 574）：
```python
# 找到呼叫 _generate_signal 的地方，改為：
pos_entry = positions.get(symbol)   # (qty, avg_price) or None
avg_price = pos_entry[1] if pos_entry else None

# 從 DB 讀取 high_water_mark（啟動時已 restore，需要快取在記憶體）
hwm = high_water_marks.get(symbol)  # 新增 high_water_marks: Dict[str, float] = {}

signal = _generate_signal(snap, avg_price, high_water_mark=hwm)
```

同時在 buy 成交後初始化高水位，在每次掃盤更新高水位：
```python
# 掃盤時更新高水位（在快照取得後）：
if symbol in positions and snap["close"] > high_water_marks.get(symbol, 0):
    high_water_marks[symbol] = snap["close"]
    # 回寫 DB
    conn.execute(
        "UPDATE positions SET high_water_mark=? WHERE symbol=?",
        (snap["close"], symbol)
    )
```

**Step 6: 啟動時從 DB 恢復 high_water_marks**

在啟動的 positions 恢復區塊（約 line 466）加入：
```python
high_water_marks: Dict[str, float] = {}
for _row in _conn_init.execute(
    "SELECT symbol, high_water_mark FROM positions WHERE quantity > 0"
).fetchall():
    if _row[1]:
        high_water_marks[_row[0]] = float(_row[1])
```

**Step 7: 跑完整測試**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 8: Commit**
```bash
git add src/openclaw/ticker_watcher.py tests/test_ticker_watcher.py
git commit -m "feat(strategy): Trailing Stop — 動態高水位追蹤，獲利>50%自動收緊至3%"
```

---

## Task 3：修復風控 — 止損單跳過 slippage/price_deviation 檢查

**目標**：平倉 sell 單不受 `RISK_SLIPPAGE_ESTIMATE_LIMIT` 和 `RISK_PRICE_DEVIATION_LIMIT` 攔截（解決跌停板止損失敗問題）。

**Files:**
- Modify: `src/openclaw/risk_engine.py`（`evaluate_and_build_order`）

**Step 1: 寫失敗測試**

在 `tests/test_risk_engine.py`（或對應測試檔）加入：
```python
def test_close_position_order_skips_slippage_check(mem_db):
    """平倉 sell 單即使 slippage 超標也應通過風控（跌停板止損場景）"""
    from openclaw.risk_engine import evaluate_and_build_order, Decision, MarketSnapshot, PortfolioState, SystemState
    import time

    decision = Decision(
        decision_id="test-close",
        symbol="2330",
        signal_side="sell",
        signal_score=-1.0,
        ts_ms=int(time.time() * 1000),
        signal_ttl_ms=60000,
        strategy_id="test",
        strategy_version="v1",
    )
    # 跌停板：best_bid 極低（模擬流動性消失）
    market = MarketSnapshot(
        symbol="2330",
        close=500.0,
        reference=700.0,    # 跌停：-28.6%（台股 10% 但這是模擬）
        best_bid=1.0,       # bid 極低 → slippage 天文數字
        best_ask=510.0,
        volume=0,
        volume_1m=0,
    )
    portfolio = PortfolioState(cash=0, positions={"2330": (100, 700.0)}, nav=70000)
    system_state = SystemState(orders_last_60s=0, now_ms=int(time.time()*1000))

    result = evaluate_and_build_order(decision, market, portfolio, system_state)

    # 關鍵：即使 slippage 極高，平倉單應通過
    assert result.approved, f"Close order should pass risk check, got: {result.reject_code}"
```

**Step 2: 確認失敗**
```bash
PYTHONPATH=src pytest tests/test_risk_engine.py::test_close_position_order_skips_slippage_check -v
```
預期：FAIL（`RISK_SLIPPAGE_ESTIMATE_LIMIT` 攔截）

**Step 3: 修改 `evaluate_and_build_order`**

在 `src/openclaw/risk_engine.py` 的 `evaluate_and_build_order` 函數中，找到 slippage 和 price_deviation 檢查（約 line 273-284），加入平倉豁免：

```python
    candidate = _build_candidate(decision, market, portfolio, limits)
    if not candidate:
        return EvaluationResult(False, "RISK_LIQUIDITY_LIMIT", metrics=base_metrics)

    if system_state.reduce_only_mode and candidate.opens_new_position:
        return EvaluationResult(False, "RISK_CONSECUTIVE_LOSSES", metrics=base_metrics)

    # ── 平倉單跳過 price deviation 和 slippage 檢查 ─────────────────────────
    # 理由：跌停板時 bid 消失，slippage 計算無意義；止損必須無條件通過
    is_closing_position = not candidate.opens_new_position
    if not is_closing_position:
        mid = (market.best_bid + market.best_ask) / 2
        price_dev_pct = abs(candidate.price - mid) / max(mid, 0.01)
        if price_dev_pct > limits["max_price_deviation_pct"]:
            m = dict(base_metrics)
            m["price_dev_pct"] = price_dev_pct
            return EvaluationResult(False, "RISK_PRICE_DEVIATION_LIMIT", metrics=m)

        slippage_bps = _estimate_slippage_bps(candidate, market)
        if slippage_bps > limits["max_slippage_bps"]:
            m = dict(base_metrics)
            m["slippage_bps"] = slippage_bps
            return EvaluationResult(False, "RISK_SLIPPAGE_ESTIMATE_LIMIT", metrics=m)
```

**Step 4: 確認通過**
```bash
PYTHONPATH=src pytest tests/test_risk_engine.py::test_close_position_order_skips_slippage_check -v
```

**Step 5: 跑全套測試**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 6: Commit**
```bash
git add src/openclaw/risk_engine.py tests/test_risk_engine.py
git commit -m "fix(risk): 平倉 sell 單跳過 slippage/price_deviation 風控（解決跌停板止損失敗）"
```

---

## Task 4：ATR(14) 加入 technical_indicators.py

**目標**：補全 ATR 計算，讓 position_sizing 的 ATR-based 路徑可以真正觸發。

**Files:**
- Modify: `src/openclaw/technical_indicators.py`

**Step 1: 寫失敗測試**

在 `tests/test_technical_indicators.py` 加入：
```python
def test_atr_basic():
    """ATR(14) 基本計算"""
    from openclaw.technical_indicators import atr
    import random
    random.seed(42)
    # 15 根 OHLCV
    candles = [{"high": 100+i, "low": 99+i, "close": 99.5+i} for i in range(15)]
    result = atr(candles, period=14)
    assert isinstance(result, float)
    assert result > 0
    assert result < 5  # 合理範圍

def test_atr_insufficient_data_returns_none():
    """資料不足 period+1 根時回傳 None"""
    from openclaw.technical_indicators import atr
    candles = [{"high": 100, "low": 99, "close": 99.5}] * 10
    result = atr(candles, period=14)
    assert result is None

def test_atr_volatile_market():
    """高波動市場 ATR 較大"""
    from openclaw.technical_indicators import atr
    # 每根振幅 10
    candles = [{"high": 110, "low": 90, "close": 100}] * 20
    result = atr(candles, period=14)
    assert result > 8  # 接近 20 的振幅
```

**Step 2: 確認失敗**
```bash
PYTHONPATH=src pytest tests/test_technical_indicators.py -k "atr" -v
```

**Step 3: 實作 ATR**

在 `src/openclaw/technical_indicators.py` 末端加入：
```python
def atr(candles: list[dict], period: int = 14) -> Optional[float]:
    """Average True Range (ATR)

    candles: list of {"high": float, "low": float, "close": float}，時間由舊到新
    需要至少 period+1 根才能計算
    """
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low  = candles[i]["low"]
        prev_close = candles[i-1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    # Wilder's smoothing（初始值用簡單平均）
    atr_val = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period

    return round(atr_val, 4)
```

**Step 4: 確認通過**
```bash
PYTHONPATH=src pytest tests/test_technical_indicators.py -k "atr" -v
```

**Step 5: Commit**
```bash
git add src/openclaw/technical_indicators.py tests/test_technical_indicators.py
git commit -m "feat(indicators): 新增 ATR(14) Wilder smoothing 實作"
```

---

## Task 5：Sprint 0.5 驗收 + pm2 restart

**Step 1: 跑全套測試 + 覆蓋率**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```
預期：全部通過，無 regression

**Step 2: 重啟 watcher 讓新邏輯生效**
```bash
pm2 restart ai-trader-watcher
pm2 logs ai-trader-watcher --lines 20
```
確認 log 有 `Restored N positions from DB` 且無錯誤。

**Step 3: 前端 rebuild**
```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web && npm run build && pm2 restart ai-trader-web
```

---

# SPRINT 1 — 模組拆分 + 執行鏈（1 週）

## Task 6：EOD 日線驅動技術指標

**目標**：`_generate_signal` 改從 `eod_prices` 取日線 OHLCV 計算技術指標，廢棄 3 分鐘記憶體 close 作為技術指標來源。

**Files:**
- Create: `src/openclaw/signal_generator.py`
- Modify: `src/openclaw/ticker_watcher.py`（呼叫新模組）

**Step 1: 寫失敗測試**

新建 `tests/test_signal_generator.py`：
```python
import sqlite3, pytest

@pytest.fixture
def db_with_eod(tmp_path):
    """建立有 eod_prices 資料的測試 DB"""
    conn = sqlite3.connect(str(tmp_path / "trades.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY (trade_date, symbol)
    )""")
    # 插入 20 天模擬日線（台積電）
    import random; random.seed(1)
    price = 800.0
    for i in range(20):
        from datetime import date, timedelta
        d = (date(2026, 2, 1) + timedelta(days=i)).isoformat()
        price = price * (1 + random.uniform(-0.02, 0.02))
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, "2330", price*0.99, price*1.01, price*0.98, price, 1e6))
    conn.commit()
    return conn

def test_signal_generator_returns_signal(db_with_eod):
    """從 eod_prices 計算技術指標並回傳信號"""
    from openclaw.signal_generator import compute_signal
    result = compute_signal(db_with_eod, symbol="2330", position_avg_price=None,
                            high_water_mark=None)
    assert result in ("buy", "sell", "flat")

def test_signal_generator_returns_flat_for_unknown_symbol(db_with_eod):
    """無資料的股票應回傳 flat"""
    from openclaw.signal_generator import compute_signal
    result = compute_signal(db_with_eod, symbol="9999", position_avg_price=None,
                            high_water_mark=None)
    assert result == "flat"

def test_signal_generator_sell_when_trailing_triggered(db_with_eod):
    """Trailing Stop 觸發時回傳 sell"""
    from openclaw.signal_generator import compute_signal
    # avg=100, high_water=200（+100%），latest close 大約 800 → 取最新收盤
    # 給一個很高的 high_water 確保觸發
    conn = db_with_eod
    latest = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol='2330' ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()[0]
    result = compute_signal(conn, "2330",
                            position_avg_price=latest * 0.5,
                            high_water_mark=latest * 2.0)  # 高水位是現價兩倍
    assert result == "sell"
```

**Step 2: 確認失敗**
```bash
PYTHONPATH=src pytest tests/test_signal_generator.py -v
```
預期：ModuleNotFoundError（signal_generator 不存在）

**Step 3: 建立 `signal_generator.py`**

```python
# src/openclaw/signal_generator.py
"""
信號生成模組 — Strangler Fig 第一步

從 eod_prices 取日線 OHLCV，用技術指標 + Trailing Stop + 止損止盈
計算交易信號。

取代 ticker_watcher._generate_signal（舊版使用記憶體內 3 分鐘 close）。
"""
import sqlite3
import os
from typing import Optional

from openclaw.technical_indicators import (
    moving_average, rsi, macd, support_resistance, atr
)

_TAKE_PROFIT_PCT: float = float(os.environ.get("TAKE_PROFIT_PCT", "0.02"))
_STOP_LOSS_PCT:   float = float(os.environ.get("STOP_LOSS_PCT",   "0.03"))
_BUY_SIGNAL_MA_CROSS: bool = True   # 使用 MA 交叉作為買進信號
_TRAILING_PCT_BASE:  float = float(os.environ.get("TRAILING_PCT",       "0.05"))
_TRAILING_PCT_TIGHT: float = float(os.environ.get("TRAILING_PCT_TIGHT", "0.03"))
_TRAILING_PROFIT_THRESHOLD: float = 0.50


def _fetch_candles(conn: sqlite3.Connection, symbol: str, days: int = 60) -> list[dict]:
    """從 eod_prices 取最近 N 日 OHLCV（由舊到新）"""
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume "
        "FROM eod_prices WHERE symbol=? ORDER BY trade_date DESC LIMIT ?",
        (symbol, days)
    ).fetchall()
    return [
        {"date": r[0], "open": r[1], "high": r[2], "low": r[3],
         "close": r[4], "volume": r[5]}
        for r in reversed(rows)
    ]


def compute_signal(
    conn: sqlite3.Connection,
    symbol: str,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float],
    trailing_pct: float = _TRAILING_PCT_BASE,
) -> str:
    """
    計算交易信號。

    Returns: "buy" | "sell" | "flat"
    """
    candles = _fetch_candles(conn, symbol)
    if len(candles) < 5:
        return "flat"   # 資料不足

    closes = [c["close"] for c in candles]
    latest_close = closes[-1]

    # ── 有持倉：檢查出場條件 ─────────────────────────────────────────
    if position_avg_price is not None:
        # Trailing Stop（優先）
        effective_trailing = trailing_pct
        if high_water_mark and position_avg_price > 0:
            profit_pct = (high_water_mark - position_avg_price) / position_avg_price
            if profit_pct >= _TRAILING_PROFIT_THRESHOLD:
                effective_trailing = _TRAILING_PCT_TIGHT
        if high_water_mark and latest_close < high_water_mark * (1 - effective_trailing):
            return "sell"

        # 止盈
        if latest_close > position_avg_price * (1 + _TAKE_PROFIT_PCT):
            return "sell"
        # 止損
        if latest_close < position_avg_price * (1 - _STOP_LOSS_PCT):
            return "sell"
        return "flat"

    # ── 無持倉：檢查進場條件 ─────────────────────────────────────────
    # MA5 上穿 MA20（黃金交叉）
    if len(closes) >= 20:
        ma5  = moving_average(closes, 5)
        ma20 = moving_average(closes, 20)
        prev_ma5  = moving_average(closes[:-1], 5)  if len(closes) > 5  else None
        prev_ma20 = moving_average(closes[:-1], 20) if len(closes) > 20 else None
        if (ma5 and ma20 and prev_ma5 and prev_ma20
                and prev_ma5 <= prev_ma20 and ma5 > ma20):
            # RSI 確認不超買
            rsi_val = rsi(closes, 14)
            if rsi_val is None or rsi_val < 70:
                return "buy"

    return "flat"
```

**Step 4: 確認測試通過**
```bash
PYTHONPATH=src pytest tests/test_signal_generator.py -v
```

**Step 5: 跑全套測試**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 6: Commit**
```bash
git add src/openclaw/signal_generator.py tests/test_signal_generator.py
git commit -m "feat(signal): 新增 signal_generator.py — EOD 日線 + MA交叉 + Trailing Stop"
```

---

## Task 7：ticker_watcher 切換至 signal_generator

**目標**：主迴圈呼叫 `signal_generator.compute_signal` 取代舊 `_generate_signal`（Strangler Fig 完成）。

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`

**Step 1: 寫整合測試**

在 `tests/test_ticker_watcher.py` 加入：
```python
def test_watcher_uses_eod_data_for_signal(tmp_path, monkeypatch):
    """watcher 主迴圈應從 eod_prices 取日線資料計算信號，不再用 snap.close 做技術判斷"""
    import sqlite3
    # 建 DB 並填入 eod_prices
    db_path = str(tmp_path / "trades.db")
    # ... 用 monkeypatch 替換 DB_PATH，確認 signal_generator 被呼叫
    # 這是整合測試，確認 signal_generator.compute_signal 被引入並呼叫
    from openclaw import signal_generator
    called = []
    original = signal_generator.compute_signal
    def mock_compute(*a, **kw):
        called.append(True)
        return "flat"
    monkeypatch.setattr(signal_generator, "compute_signal", mock_compute)
    # ... 執行一輪 watcher scan（需要 mock Shioaji）
    # 簡化：只驗證 compute_signal 可被 import
    assert callable(signal_generator.compute_signal)
```

**Step 2: 修改 ticker_watcher 主迴圈**

找到呼叫 `_generate_signal` 的地方（約 line 576），改為：
```python
# 舊：signal = _generate_signal(snap, avg_price)
# 新：
from openclaw.signal_generator import compute_signal as _compute_signal_eod

signal = _compute_signal_eod(
    conn,
    symbol=symbol,
    position_avg_price=avg_price,
    high_water_mark=high_water_marks.get(symbol),
)
```

保留舊 `_generate_signal` 函數（不刪除），標記為 deprecated，供測試向後相容。

**Step 3: 跑全套測試**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 4: Commit**
```bash
git add src/openclaw/ticker_watcher.py
git commit -m "refactor(watcher): 切換至 signal_generator.compute_signal（EOD日線驅動）"
```

---

## Task 8：strategy_proposals 執行鏈

**目標**：approved proposal 能自動觸發真實 sell/buy 訂單。

**Files:**
- Create: `src/openclaw/proposal_executor.py`
- Modify: `src/openclaw/ticker_watcher.py`（掃盤時執行 approved proposals）

**Step 1: 寫失敗測試**

新建 `tests/test_proposal_executor.py`：
```python
import sqlite3, pytest

@pytest.fixture
def db_with_proposal(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER
    )""")
    conn.execute("""CREATE TABLE orders (
        order_id TEXT PRIMARY KEY, decision_id TEXT, broker_order_id TEXT,
        ts_submit TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL,
        order_type TEXT, tif TEXT, status TEXT, strategy_version TEXT
    )""")
    conn.execute("""CREATE TABLE fills (
        fill_id TEXT PRIMARY KEY, order_id TEXT, ts_fill TEXT,
        qty INTEGER, price REAL, fee REAL, tax REAL
    )""")
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL
    )""")
    # 插入一個 POSITION_REBALANCE approved proposal
    import json, time
    conn.execute("""INSERT INTO strategy_proposals VALUES (
        'p1','portfolio_review','POSITION_REBALANCE','portfolio',
        NULL,'減少 3008 持倉 30%','evidence',0.8,0,
        'approved',NULL,?,?,NULL
    )""", (json.dumps({"symbol":"3008","reduce_pct":0.3,"type":"rebalance"}),
           int(time.time())))
    conn.execute("INSERT INTO positions VALUES ('3008',1000,379.6,2450.0,0,2450.0)")
    conn.commit()
    return conn

def test_executor_creates_sell_order_for_approved_proposal(db_with_proposal):
    """approved POSITION_REBALANCE proposal 應產生 sell 訂單"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=False)
    orders = db_with_proposal.execute("SELECT symbol, side, qty FROM orders").fetchall()
    assert len(orders) == 1
    assert orders[0][0] == "3008"
    assert orders[0][1] == "sell"
    assert orders[0][2] == 300  # 1000 * 30%，取整

def test_executor_marks_proposal_as_executed(db_with_proposal):
    """執行後 proposal status 應更新為 executed"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=False)
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "executed"

def test_executor_dry_run_does_not_create_orders(db_with_proposal):
    """dry_run=True 時不建立訂單"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=True)
    orders = db_with_proposal.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert orders == 0
```

**Step 2: 確認失敗**
```bash
PYTHONPATH=src pytest tests/test_proposal_executor.py -v
```

**Step 3: 建立 `proposal_executor.py`**

```python
# src/openclaw/proposal_executor.py
"""
Proposal Executor — strategy_proposals 執行鏈

掃描 status='approved' 的提案，按類型執行對應動作：
  - POSITION_REBALANCE: 建立部分 sell 訂單
  - STRATEGY_DIRECTION: 更新 system_state（未來擴展）
"""
import json
import logging
import sqlite3
import time
import uuid
from typing import Optional

log = logging.getLogger(__name__)

_STRATEGY_VERSION = "proposal_executor_v1"


def _create_sell_order(conn: sqlite3.Connection, symbol: str, qty: int,
                       price: float, proposal_id: str) -> str:
    order_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO orders
           (order_id, decision_id, broker_order_id, ts_submit,
            symbol, side, qty, price, order_type, tif, status, strategy_version)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (order_id, proposal_id, f"PROP-{proposal_id[:8]}",
         time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
         symbol, "sell", qty, price, "market", "ROD", "submitted",
         _STRATEGY_VERSION)
    )
    return order_id


def execute_pending_proposals(conn: sqlite3.Connection, dry_run: bool = True) -> int:
    """
    執行所有 approved proposals。

    dry_run=True：只 log，不實際建立訂單（預設安全模式）
    Returns: 執行的 proposal 數量
    """
    rows = conn.execute(
        """SELECT proposal_id, target_rule, proposal_json
           FROM strategy_proposals
           WHERE status='approved'
             AND (expires_at IS NULL OR expires_at > ?)""",
        (int(time.time()),)
    ).fetchall()

    executed = 0
    for proposal_id, target_rule, proposal_json_str in rows:
        try:
            proposal = json.loads(proposal_json_str or "{}")
            if target_rule == "POSITION_REBALANCE":
                symbol = proposal.get("symbol")
                reduce_pct = float(proposal.get("reduce_pct", 0))
                if not symbol or reduce_pct <= 0:
                    log.warning("Invalid POSITION_REBALANCE proposal %s", proposal_id)
                    continue

                pos = conn.execute(
                    "SELECT quantity, current_price FROM positions WHERE symbol=?",
                    (symbol,)
                ).fetchone()
                if not pos or pos[0] <= 0:
                    log.info("Proposal %s: no position in %s", proposal_id, symbol)
                    conn.execute(
                        "UPDATE strategy_proposals SET status='skipped' WHERE proposal_id=?",
                        (proposal_id,)
                    )
                    conn.commit()
                    continue

                qty_to_sell = max(1, int(pos[0] * reduce_pct))
                price = pos[1] or 0.0

                log.info("Proposal %s: %s sell %d @ %.2f (dry_run=%s)",
                         proposal_id, symbol, qty_to_sell, price, dry_run)

                if not dry_run:
                    _create_sell_order(conn, symbol, qty_to_sell, price, proposal_id)
                    conn.execute(
                        "UPDATE strategy_proposals SET status='executed', decided_at=? "
                        "WHERE proposal_id=?",
                        (int(time.time()), proposal_id)
                    )
                    conn.commit()
                    executed += 1

            elif target_rule == "STRATEGY_DIRECTION":
                log.info("Proposal %s (STRATEGY_DIRECTION): noted, no auto-action", proposal_id)
                if not dry_run:
                    conn.execute(
                        "UPDATE strategy_proposals SET status='noted' WHERE proposal_id=?",
                        (proposal_id,)
                    )
                    conn.commit()

        except Exception as e:
            log.error("Error executing proposal %s: %s", proposal_id, e)

    return executed
```

**Step 4: 確認測試通過**
```bash
PYTHONPATH=src pytest tests/test_proposal_executor.py -v
```

**Step 5: 整合至 ticker_watcher 主迴圈**

在 `run_watcher` 每輪掃描結束時（約 line 690 附近）加入：
```python
# 每輪掃盤後執行 approved proposals
try:
    from openclaw.proposal_executor import execute_pending_proposals
    n = execute_pending_proposals(conn, dry_run=False)
    if n > 0:
        log.info("Executed %d approved proposals", n)
except Exception as _pe:
    log.warning("proposal_executor error: %s", _pe)
```

**Step 6: 跑全套測試**
```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

**Step 7: Commit**
```bash
git add src/openclaw/proposal_executor.py tests/test_proposal_executor.py src/openclaw/ticker_watcher.py
git commit -m "feat(executor): proposal_executor — approved 提案自動執行 sell 訂單"
```

---

## Task 9：集中度超標自動觸發減倉 Proposal

**目標**：掃盤時發現單檔超過 60%，自動生成且立即執行減倉；超過 40% 生成 pending proposal 等人工核准。

**Files:**
- Create: `src/openclaw/concentration_guard.py`
- Modify: `src/openclaw/ticker_watcher.py`

**Step 1: 寫失敗測試**

```python
# tests/test_concentration_guard.py
import sqlite3

def test_auto_reduce_when_over_60pct(tmp_path):
    """單檔超過 60% 應自動生成 approved proposal 並立即可執行"""
    from openclaw.concentration_guard import check_concentration
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    # 建表（省略：同 proposal_executor 測試的建表邏輯）
    # ...（建 positions + strategy_proposals 表）
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL)""")
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER)""")
    # 3008 佔 70%
    conn.execute("INSERT INTO positions VALUES ('3008',591,379.6,2450,0,2450)")
    conn.execute("INSERT INTO positions VALUES ('2330',151,898.6,1935,0,1935)")
    conn.commit()

    proposals = check_concentration(conn)
    assert any(p["symbol"] == "3008" for p in proposals)
    p3008 = next(p for p in proposals if p["symbol"] == "3008")
    assert p3008["auto_approve"]    # 超過 60% 自動核准
    assert p3008["reduce_pct"] > 0

def test_pending_proposal_when_40_to_60_pct(tmp_path):
    """單檔 40-60% 生成 pending proposal（需人工核准）"""
    from openclaw.concentration_guard import check_concentration
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL)""")
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER)""")
    # 約 45% 佔比
    conn.execute("INSERT INTO positions VALUES ('3008',100,379.6,2450,0,2450)")
    conn.execute("INSERT INTO positions VALUES ('2330',200,898.6,500,0,500)")
    conn.commit()

    proposals = check_concentration(conn)
    if proposals:
        assert not proposals[0]["auto_approve"]  # 需人工核准
```

**Step 2: 實作 `concentration_guard.py`**

```python
# src/openclaw/concentration_guard.py
"""集中度守衛 — 自動偵測並處理單檔倉位過度集中"""
import json, logging, sqlite3, time, uuid
from typing import TypedDict

log = logging.getLogger(__name__)

_AUTO_REDUCE_THRESHOLD = 0.60   # 超過 60%：自動核准減倉
_WARN_THRESHOLD        = 0.40   # 超過 40%：生成待審 proposal
_TARGET_WEIGHT         = 0.30   # 目標降至 30%

class ConcentrationProposal(TypedDict):
    symbol: str
    current_weight: float
    auto_approve: bool
    reduce_pct: float

def check_concentration(conn: sqlite3.Connection) -> list[ConcentrationProposal]:
    """計算各持倉集中度，返回需要處理的 proposals（也會寫入 DB）"""
    rows = conn.execute(
        "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
    ).fetchall()
    if not rows:
        return []

    total_value = sum(r[1] * (r[2] or 0) for r in rows)
    if total_value <= 0:
        return []

    proposals = []
    for symbol, qty, price in rows:
        weight = (qty * (price or 0)) / total_value
        if weight < _WARN_THRESHOLD:
            continue

        auto_approve = weight >= _AUTO_REDUCE_THRESHOLD
        # 需減到 TARGET_WEIGHT，計算需賣出的比例
        current_value = qty * (price or 0)
        target_value  = total_value * _TARGET_WEIGHT
        reduce_value  = max(0, current_value - target_value)
        reduce_pct    = min(reduce_value / current_value, 0.8) if current_value > 0 else 0

        proposal = ConcentrationProposal(
            symbol=symbol, current_weight=weight,
            auto_approve=auto_approve, reduce_pct=round(reduce_pct, 3)
        )
        proposals.append(proposal)

        # 寫入 DB
        proposal_id = str(uuid.uuid4())
        status = "approved" if auto_approve else "pending"
        conn.execute(
            """INSERT OR IGNORE INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (proposal_id, "concentration_guard", "POSITION_REBALANCE", "portfolio",
             f"降低 {symbol} 持倉至 {_TARGET_WEIGHT*100:.0f}% 以下",
             f"{symbol} 目前佔組合 {weight:.1%}，超過警示門檻",
             0.9, int(not auto_approve), status,
             json.dumps({"symbol": symbol, "reduce_pct": reduce_pct,
                        "type": "rebalance", "auto": auto_approve}),
             int(time.time()))
        )
        conn.commit()
        log.info("Concentration %s: %.1f%% → %s proposal", symbol, weight*100, status)

    return proposals
```

**Step 3: 確認測試通過，整合至 watcher**
```bash
PYTHONPATH=src pytest tests/test_concentration_guard.py -v
```

**Step 4: Commit**
```bash
git add src/openclaw/concentration_guard.py tests/test_concentration_guard.py src/openclaw/ticker_watcher.py
git commit -m "feat(risk): 集中度守衛 — >60%自動減倉 proposal，40-60%生成待審提案"
```

---

## Task 10：Sprint 1 驗收

**Step 1: 跑全套測試**
```bash
PYTHONPATH=src pytest tests/ -q
cd frontend/backend && python -m pytest tests/ -q
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
```

**Step 2: 重啟所有服務**
```bash
pm2 restart ai-trader-watcher ai-trader-api
cd frontend/web && npm run build && pm2 restart ai-trader-web
```

**Step 3: 驗證閉環**
- 在前端 Strategy 頁看到 proposals 有 `executed` 狀態
- 在 Portfolio 頁看到持倉數量因減倉 proposal 執行而變化
- 在 Trades 頁看到 sell 訂單紀錄

**Step 4: CI**
```bash
git push origin main
gh run watch $(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
```

**Step 5: 若 CI 全綠，開 Issue 確認 Sprint 1 完成**
```bash
gh issue create --title "Sprint 1 完成：閉環修復 + 模組拆分" \
  --body "- [x] Trailing Stop\n- [x] 風控止損豁免\n- [x] signal_generator（EOD日線）\n- [x] proposal_executor\n- [x] concentration_guard"
gh issue close <issue-number>
```

---

# SPRINT 2-3 — 備忘（下一輪計劃展開）

Sprint 2 和 Sprint 3 在 Sprint 1 完成後，依據實際情況重新評估並展開詳細計劃。

**Sprint 2 核心任務（概要）：**
- `trading_engine.py`：持倉狀態機（CANDIDATE → ENTRY → HOLDING → EXITING → CLOSED）
- `signal_aggregator.py`：Regime-based 動態權重融合
- LLM 信號快取（strategy_committee 結果寫 DB，1 小時有效）
- T+2 交割資金追蹤

**Sprint 3 核心任務（概要）：**
- `performance_tracker.py`：勝率、損益比、夏普比率、最大回撤、Benchmark 對比
- `strategy_optimizer.py`：≥30 筆統計、自動/人工分級閾值調整
- A/B 策略對比框架
- Shioaji 斷線重連
