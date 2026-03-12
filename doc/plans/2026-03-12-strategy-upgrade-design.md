# AI Trader Strategy & Data Layer Upgrade — Design Spec

> Date: 2026-03-12
> Status: Draft
> Scope: Backtest framework + strategy signal enhancement + data integration + observability

---

## 1. Problem Statement

The AI Trader system has accumulated 5.5 months of EOD data (60K+ records) and executed 52 trades, but lacks the infrastructure to validate strategy changes before deploying them. Current pain points:

1. **Weak entry signals** — Only MA(5/20) golden cross + RSI(14) filter; no volume confirmation, no momentum, no institutional flow integration. Last buy was 2026-03-04.
2. **Static exit thresholds** — Take-profit +2%, stop-loss -3%, trailing 5% are hardcoded constants that don't adapt to volatility. ATR is already computed but unused.
3. **Chips data disconnected** — Institutional flows (T86) and margin data (MI_MARGN) are ingested daily but only fed to EOD Gemini prompts, not to real-time trading signals.
4. **No backtest framework** — No way to validate parameter changes against historical data. Strategy optimizer uses only a 28-day rolling window.
5. **No performance attribution** — PnL is tracked but there's no system to attribute gains/losses to signal source, regime, or holding period.
6. **No intraday persistence** — Ticker watcher polls every 3 minutes but discards snapshots; no intraday pattern analysis possible.

## 2. Approach: Backtest-First, Then Iterate

Route: **D (backtest) → A+B+C (strategy) → E+F (observability)**

Rationale: Without a backtest framework, every strategy change is a blind modification. Building the validation infrastructure first ensures every subsequent improvement (dynamic stops, chips integration, new signals) can be measured against the 60K-record historical baseline.

Architecture: **Hybrid mode** — Extract pure-function signal logic shared by both production pipeline and backtest engine. Production keeps its DB-writing/Telegram-notifying wrapper; backtest uses the same signal functions with zero side effects.

```
[Pure Function Layer — shared]
  technical_indicators.py  (already pure ✓)
  signal_logic.py          (extracted from signal_generator.py)
  cost_model.py            (commission + tax + slippage)

[Production Driver]
  signal_generator.py  → calls signal_logic + writes DB
  ticker_watcher.py    → calls signal_generator + places orders

[Backtest Driver]
  backtest/engine.py   → calls signal_logic + accumulates simulated PnL
  backtest/scanner.py  → calls engine × N parameter combinations
```

## 3. Phase 1 — Backtest Infrastructure

### 3.1 Pure Function Extraction: `signal_logic.py`

New module: `src/openclaw/signal_logic.py`

Extracts core decision logic from `signal_generator.py` into stateless pure functions.

```python
@dataclass
class SignalParams:
    take_profit_pct: float = 0.02        # +2%
    stop_loss_pct: float = 0.03          # -3%
    trailing_pct: float = 0.05           # 5%
    trailing_pct_tight: float = 0.03     # 3% (after profit > threshold)
    trailing_profit_threshold: float = 0.50  # 50% profit triggers tight trailing
    ma_short: int = 5
    ma_long: int = 20
    rsi_period: int = 14
    rsi_upper: float = 70.0

@dataclass
class SignalResult:
    action: str          # "buy" | "sell" | "flat"
    reason: str          # "trailing_stop" | "take_profit" | "stop_loss" | "ma_cross" | "flat"
    confidence: float    # 0.0~1.0
    indicators: dict     # snapshot of current indicator values
```

**Two core functions:**

- `evaluate_exit(closes, high_water_mark, avg_price, qty, params) -> SignalResult` — For positions: trailing stop → take profit → stop loss → flat
- `evaluate_entry(closes, volumes, params) -> SignalResult` — For non-positions: MA golden cross + RSI filter → buy or flat

**Refactoring strategy:** `signal_generator.py` becomes a thin wrapper that calls `signal_logic` functions, then writes results to DB and updates `positions` table. Existing API and behavior unchanged.

### 3.2 Cost Model: `cost_model.py`

New module: `src/openclaw/cost_model.py`

```python
@dataclass
class CostParams:
    commission_rate: float = 0.001425   # 0.1425% both sides
    tax_rate: float = 0.003             # 0.3% sell only
    slippage_bps: float = 0.0           # reserved for Phase 3
```

**Functions:**
- `calc_buy_cost(price, qty, params) -> float` — Total outlay including commission
- `calc_sell_proceeds(price, qty, params) -> float` — Net proceeds after commission + tax
- `calc_round_trip_pnl(buy_price, sell_price, qty, params) -> float` — Single round-trip PnL

### 3.3 Backtest Engine: `backtest/engine.py`

New module: `src/openclaw/backtest/engine.py`

```python
@dataclass
class BacktestConfig:
    signal_params: SignalParams
    cost_params: CostParams
    initial_capital: float = 1_000_000
    max_positions: int = 5
    max_position_pct: float = 0.30      # single position cap 30%
    max_drawdown_halt: float = 0.15     # halt at 15% drawdown

@dataclass
class TradeRecord:
    symbol: str
    side: str           # buy/sell
    price: float
    qty: int
    date: str
    reason: str         # from SignalResult.reason
    cost: float

@dataclass
class BacktestResult:
    trades: list[TradeRecord]
    equity_curve: list[dict]     # [{date, equity, drawdown}]
    metrics: dict                # total_return, win_rate, max_drawdown, sharpe, profit_factor
    params_used: SignalParams
```

**Core loop** (`run_backtest`):
1. Load EOD data for specified symbols and date range from `eod_prices` (readonly)
2. For each trading day, chronologically:
   a. For each held position → `evaluate_exit()` → execute sell if triggered
   b. For each watchlist symbol without position → `evaluate_entry()` → execute buy if triggered and capital allows
   c. Update equity, track high-water mark, compute drawdown
   d. If drawdown exceeds `max_drawdown_halt` → stop all trading for remaining period
3. Force-close all remaining positions at end of period
4. Compute aggregate metrics

**Simplified risk controls** (backtest only):
- Concentration limit: `max_position_pct` (default 30%)
- Drawdown circuit breaker: `max_drawdown_halt` (default 15%)
- No full 7-layer risk_engine — avoids overfitting risk parameters to historical data

**Position sizing:**
- Buy qty = floor(available_capital × max_position_pct / price)
- Round to lot size (1000 shares for stocks under NT$10, 1 share otherwise per TWSE rules)

### 3.4 Parameter Scanner: `backtest/scanner.py`

New module: `src/openclaw/backtest/scanner.py`

```python
@dataclass
class ScanRange:
    param_name: str     # e.g. "trailing_pct"
    start: float
    end: float
    step: float

def scan_params(
    symbols: list[str],
    eod_data: dict,
    base_config: BacktestConfig,
    scan_ranges: list[ScanRange],
) -> list[BacktestResult]:
    """
    Grid search over parameter combinations.
    Returns results sorted by Sharpe ratio descending.
    """
```

**Performance target:** 60K EOD records, 5 symbols, 50 parameter combinations → < 30 seconds total.

**Output:** JSON report with ranked parameter combinations and their metrics.

### 3.5 CLI Tool: `tools/run_backtest.py`

```bash
# Single backtest with current production parameters
python tools/run_backtest.py --strategy current \
  --symbols 2317,2382 \
  --period 2025-10-01:2026-03-12

# Parameter scan
python tools/run_backtest.py --strategy current \
  --scan trailing_pct=2:8:0.5 \
  --scan stop_loss_pct=2:5:0.5

# Output location
# → data/backtest/results/YYYYMMDDTHHMMSSZ.json
# → stdout: summary table (top 5 parameter combinations + metrics)
```

### 3.6 Data Source

Backtest engine reads directly from `eod_prices` table (readonly mode, `db.get_conn()`). Supports arbitrary date ranges within available data (2025-10-01 to present).

Phase 2 additions will also read `eod_institution_flows` and `eod_margin_data` for chips-integrated strategies.

### 3.7 Test Strategy

- Unit tests for `signal_logic.py` pure functions (known input → known output)
- Unit tests for `cost_model.py` (verify fee/tax calculations against manual examples)
- Integration test: run backtest on a known 30-day slice, assert metrics are deterministic
- Regression test: verify `signal_generator.py` produces identical results after refactoring to use `signal_logic.py`

---

## 4. Phase 2 — Strategy Upgrades (A+B+C)

Each change is validated via Phase 1 backtest before merging to production.

### 4.1 (A) Entry Signal Enhancement

**New signals to add to `signal_logic.py`:**

| Signal | Logic | Purpose |
|--------|-------|---------|
| Volume breakout | today_vol >= 1.5 × MA5_vol | Confirm momentum behind price moves |
| Rate of Change (ROC) | (close - close_N) / close_N | Short-term momentum (5-day, 10-day) |
| MACD histogram crossover | histogram crosses zero from below | Trend confirmation alongside MA cross |

**Integration:** `evaluate_entry()` returns buy only when MA cross + at least 1 confirming signal fires. This reduces false entry signals.

**Validation:** Backtest current-only vs current+volume vs current+volume+ROC, compare win rate and profit factor.

### 4.2 (B) Dynamic Exit Thresholds

**Replace static thresholds with ATR-based dynamic thresholds:**

```python
@dataclass
class DynamicExitParams:
    atr_period: int = 14
    trailing_atr_mult: float = 2.0      # trailing = ATR × 2.0
    take_profit_atr_mult: float = 3.0   # take profit = ATR × 3.0
    stop_loss_atr_mult: float = 1.5     # stop loss = ATR × 1.5
```

**Regime awareness:** In bear regime, tighten multipliers by 0.7× (from signal_aggregator's existing regime weights).

**Validation:** Scan `atr_mult` from 1.0 to 4.0 in 0.5 steps, compare max drawdown and profit factor vs static thresholds.

### 4.3 (C) Institutional Flow Integration

**New signal source in `signal_logic.py`:**

```python
def evaluate_chips_signal(
    institution_flows: list[dict],  # recent N days of T86 data
    margin_data: list[dict],        # recent N days of MI_MARGN data
) -> float:  # 0.0 (bearish) ~ 1.0 (bullish)
```

**Scoring rules:**
- Foreign + trust net buy >= 2 consecutive days → +0.3
- Foreign + trust net buy >= 5 consecutive days → +0.5
- Margin balance decreasing >= 2 days → +0.2 (deleveraging = bullish)
- Margin balance increasing >= 3 days → -0.2 (overleveraged = bearish)

**Integration into `signal_aggregator.py`:**

Add chips as 4th signal source. Updated regime weights:

```python
REGIME_WEIGHTS = {
    "bull":  {"technical": 0.40, "llm": 0.15, "risk_adj": 0.25, "chips": 0.20},
    "bear":  {"technical": 0.25, "llm": 0.15, "risk_adj": 0.40, "chips": 0.20},
    "range": {"technical": 0.35, "llm": 0.15, "risk_adj": 0.30, "chips": 0.20},
}
```

**Validation:** Backtest with/without chips signal, compare across bull/bear/range periods in historical data.

---

## 5. Phase 3 — Observability (E+F)

### 5.1 (E) Performance Attribution Engine

New module: `src/openclaw/attribution.py`

For each closed trade, tag with:
- `signal_source`: which signal triggered entry/exit (ma_cross, trailing_stop, chips, etc.)
- `regime_at_entry` / `regime_at_exit`: market regime when trade opened/closed
- `holding_days`: how long the position was held

Aggregate into attribution report:
- PnL breakdown by signal source
- PnL breakdown by regime
- PnL breakdown by holding period bucket (1-5d, 5-15d, 15-30d, 30d+)

Storage: new columns on `daily_pnl_summary` or a dedicated `trade_attribution` table.

### 5.2 (F) Intraday Snapshot Persistence

New table: `intraday_snapshots`

```sql
CREATE TABLE intraday_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,   -- ISO timestamp
    close REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    reference REAL,
    created_at INTEGER NOT NULL    -- epoch ms
);
CREATE INDEX idx_intraday_symbol_time ON intraday_snapshots(symbol, snapshot_time);
```

**Modification:** `ticker_watcher.py` writes each 3-minute poll snapshot to this table before signal evaluation. Retention policy: keep 30 days, auto-purge older records daily.

**Future use:** Intraday pattern analysis (opening auction behavior, volume acceleration detection, price-volume divergence).

---

## 6. File Structure

```
src/openclaw/
├── signal_logic.py          # NEW: pure signal functions (shared)
├── cost_model.py            # NEW: fee/tax/slippage model
├── signal_generator.py      # MODIFIED: thin wrapper over signal_logic
├── signal_aggregator.py     # MODIFIED (Phase 2): add chips signal source
├── attribution.py           # NEW (Phase 3): performance attribution
├── backtest/
│   ├── __init__.py
│   ├── engine.py            # NEW: single-run backtest
│   └── scanner.py           # NEW: parameter grid search
tools/
├── run_backtest.py          # NEW: CLI entry point
data/
├── backtest/
│   └── results/             # NEW: backtest output directory
```

## 7. Non-Goals

- **Live trading integration** — Backtest results inform parameter changes; they are NOT auto-deployed to production.
- **ML-based optimization** — Grid search only; no Bayesian optimization or genetic algorithms. YAGNI for current scale.
- **Multi-timeframe analysis** — Phase 1 is daily only. Intraday backtesting deferred to post-Phase 3.
- **Web UI for backtest** — CLI + JSON output only. Frontend visualization deferred.
- **Options or futures** — Stock-only. No derivatives strategy support.

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Backtest-production divergence | False confidence in parameters | Shared pure-function layer; regression test that signal_generator output matches signal_logic |
| Overfitting to historical data | Parameters work in backtest but fail live | Out-of-sample validation: train on 2025-10 to 2026-01, test on 2026-02 to 2026-03 |
| Refactoring breaks signal_generator | Production signals stop working | Full test coverage before/after; canary: run both old and new in parallel for 1 day |
| Parameter scan too slow | > 30s for large grids | Profile and optimize hot paths; cap max combinations at 500 |
| Look-ahead bias in backtest | Unrealistic results | Engine processes data strictly chronologically; no future data in any signal function |
