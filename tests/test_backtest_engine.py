# tests/test_backtest_engine.py
"""backtest_engine 單元測試（TDD）

測試案例：
1. test_run_backtest_basic — 30 日上漲趨勢資料，驗證回傳結構合法
2. test_run_backtest_locked_symbols_skip_exit — locked symbol 不產生賣出交易
3. test_run_backtest_empty_data — 空 DB → 0 trades，equity 不變
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from openclaw.backtest_engine import BacktestConfig, BacktestResult, run_backtest
from openclaw.cost_model import CostParams
from openclaw.signal_logic import SignalParams


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_db(rows: list[tuple]) -> str:
    """建立暫存 SQLite，插入 eod_prices 資料，回傳 db_path。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE eod_prices (
            trade_date TEXT,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp.name


def _uptrend_rows(symbol: str, start_close: float = 100.0, days: int = 30) -> list[tuple]:
    """產生 days 筆穩定上漲的日線資料（每日 +1%）。"""
    from datetime import date, timedelta

    rows = []
    base = date(2024, 1, 2)
    price = start_close
    for i in range(days):
        d = base + timedelta(days=i)
        o = price * 0.999
        h = price * 1.005
        lo = price * 0.995
        rows.append((d.isoformat(), symbol, o, h, lo, price, 10000))
        price = round(price * 1.01, 4)
    return rows


def _default_config(
    symbols: list[str],
    db_rows: list[tuple],
    locked_symbols: set[str] | None = None,
    stop_loss_pct: float = 0.03,
) -> tuple[BacktestConfig, str]:
    """回傳 (config, db_path)。"""
    db_path = _make_db(db_rows)
    # SignalParams：用寬鬆 ma_short/ma_long 以便短資料觸發進場
    sp = SignalParams(
        ma_short=3,
        ma_long=5,
        take_profit_pct=0.50,   # 50%，不易意外觸發止盈
        stop_loss_pct=stop_loss_pct,
        trailing_pct=0.99,      # 99%，不易意外觸發 trailing
        rsi_entry_max=100.0,    # 不過濾 RSI
    )
    config = BacktestConfig(
        symbols=symbols,
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=1_000_000.0,
        signal_params=sp,
        max_positions=3,
        max_single_pct=0.30,
        cost_params=CostParams(),
        locked_symbols=locked_symbols or set(),
    )
    return config, db_path


# ─── Test 1: basic uptrend ─────────────────────────────────────────────────────

def test_run_backtest_basic():
    """30 日上漲趨勢，應回傳合法 BacktestResult。"""
    symbol = "2330"
    rows = _uptrend_rows(symbol, start_close=500.0, days=30)
    config, db_path = _default_config([symbol], rows)

    result = run_backtest(config, db_path)

    assert isinstance(result, BacktestResult)
    # equity_curve 應有資料（至少初始值 + 若干日）
    assert len(result.equity_curve) >= 1
    # 所有 equity 值應為正數
    assert all(v > 0 for v in result.equity_curve)
    # metrics 是 PerfMetrics（有 total_trades 欄位）
    assert hasattr(result.metrics, "total_trades")
    assert result.metrics.total_trades >= 0
    # trades 是 list
    assert isinstance(result.trades, list)
    # 若有交易，每筆 trade 必須包含必要欄位
    required_keys = {
        "symbol", "side", "entry_date", "exit_date",
        "entry_price", "exit_price", "qty", "pnl",
        "holding_days", "reason",
    }
    for trade in result.trades:
        assert required_keys.issubset(trade.keys()), f"缺少欄位: {trade.keys()}"
        assert trade["qty"] > 0
        assert trade["entry_price"] > 0
        assert trade["exit_price"] > 0


# ─── Test 2: locked_symbols 不產生出場交易 ────────────────────────────────────

def test_run_backtest_locked_symbols_skip_exit():
    """locked_symbol 即使止損條件成立，也不應產生 sell 交易。"""
    symbol = "0050"
    rows = _uptrend_rows(symbol, start_close=100.0, days=30)
    # stop_loss_pct=0.001 → 幾乎任何波動都會觸發止損（若不被 lock）
    config, db_path = _default_config(
        [symbol],
        rows,
        locked_symbols={symbol},
        stop_loss_pct=0.001,
    )

    result = run_backtest(config, db_path)

    # 所有非 end_of_backtest 的 sell trade 不應來自 locked symbol
    sell_trades_from_locked = [
        t for t in result.trades
        if t["symbol"] == symbol and t["reason"] != "end_of_backtest"
    ]
    assert len(sell_trades_from_locked) == 0, (
        f"locked symbol {symbol!r} 不應有 intra-period sell trades，"
        f"但發現: {sell_trades_from_locked}"
    )


# ─── Test 3: empty DB ──────────────────────────────────────────────────────────

def test_run_backtest_empty_data():
    """空 DB（無 eod_prices 資料）→ 0 trades，equity 等於 initial_capital。"""
    # 建立空 DB（無 eod_prices 表）
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name

    sp = SignalParams()
    config = BacktestConfig(
        symbols=["2330", "0050"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=500_000.0,
        signal_params=sp,
    )

    result = run_backtest(config, db_path)

    assert result.trades == []
    assert len(result.equity_curve) >= 1
    # equity 應等於初始資本（誤差容忍 0.01）
    assert abs(result.equity_curve[0] - 500_000.0) < 0.01
    assert result.metrics.total_trades == 0
