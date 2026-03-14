# src/openclaw/backtest_engine.py
"""backtest_engine.py — 日線級別歷史回測引擎

從 eod_prices 表讀取 OHLCV，每個交易日逐序重播：
1. 持倉 → evaluate_exit() → 賣出（locked_symbols 跳過）
2. 無持倉 → evaluate_entry() → 買入
3. 用 cost_model 計算交易成本
4. 更新虛擬持倉、現金、NAV
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from openclaw.cost_model import CostParams, calc_buy_cost, calc_sell_proceeds
from openclaw.perf_metrics import PerfMetrics, calculate_metrics
from openclaw.signal_logic import SignalParams, SignalResult, evaluate_entry, evaluate_exit

# 台股一張 = 1000 股
_LOT_SIZE = 1000
# 買入保留現金緩衝比例
_CASH_BUFFER = 0.05


@dataclass
class BacktestConfig:
    symbols: list[str]
    start_date: str       # "YYYY-MM-DD"
    end_date: str         # "YYYY-MM-DD"
    initial_capital: float
    signal_params: SignalParams
    max_positions: int = 5
    max_single_pct: float = 0.20
    cost_params: CostParams = field(default_factory=CostParams)
    locked_symbols: set[str] = field(default_factory=set)


@dataclass
class BacktestResult:
    trades: list[dict]
    equity_curve: list[float]
    metrics: PerfMetrics


def _load_ohlcv(
    db_path: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, dict[str, dict]]:
    """從 eod_prices 讀取 OHLCV，回傳 {symbol: {date: row}}。"""
    if not symbols:
        return {}

    placeholders = ",".join("?" * len(symbols))
    sql = f"""
        SELECT trade_date, symbol, open, high, low, close, volume
        FROM eod_prices
        WHERE symbol IN ({placeholders})
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY trade_date
    """
    params = symbols + [start_date, end_date]

    result: dict[str, dict[str, dict]] = defaultdict(dict)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for row in conn.execute(sql, params):
            d = dict(row)
            result[d["symbol"]][d["trade_date"]] = d
        conn.close()
    except sqlite3.OperationalError:
        pass  # 表不存在或空 DB → 回傳空 dict

    return dict(result)


def run_backtest(config: BacktestConfig, db_path: str) -> BacktestResult:
    """執行回測，回傳 BacktestResult。"""
    # ── 1. 讀取資料 ─────────────────────────────────────────────
    all_data = _load_ohlcv(db_path, config.symbols, config.start_date, config.end_date)

    if not all_data:
        return BacktestResult(
            trades=[],
            equity_curve=[config.initial_capital],
            metrics=calculate_metrics([config.initial_capital], []),
        )

    # 取所有交易日（union of all symbols）並排序
    all_dates_set: set[str] = set()
    for sym_data in all_data.values():
        all_dates_set.update(sym_data.keys())
    all_dates = sorted(all_dates_set)

    if not all_dates:
        return BacktestResult(
            trades=[],
            equity_curve=[config.initial_capital],
            metrics=calculate_metrics([config.initial_capital], []),
        )

    # O(1) date → index 查找
    date_to_idx: dict[str, int] = {d: i for i, d in enumerate(all_dates)}

    # ── 2. 虛擬帳戶狀態 ──────────────────────────────────────────
    cash = config.initial_capital
    # positions: {symbol: {"qty", "avg_price", "hwm", "entry_date", "entry_price"}}
    positions: dict[str, dict] = {}
    equity_curve: list[float] = [config.initial_capital]
    completed_trades: list[dict] = []

    def _nav() -> float:
        """當前 NAV = 現金 + 持倉市值。"""
        total = cash
        for sym, pos in positions.items():
            # 用最後一個可用收盤價估值
            sym_data = all_data.get(sym, {})
            # 找最近一筆有效收盤價（用當前 date loop 外部 latest_close 更好，
            # 但這裡作為 fallback 計算 NAV 用 avg_price 也可接受）
            total += pos["avg_price"] * pos["qty"]
        return total

    # ── 3. 逐日重播 ──────────────────────────────────────────────
    for date_idx, date in enumerate(all_dates):

        # --- 3a. 持倉出場掃描 ---
        symbols_to_sell: list[tuple[str, float, str]] = []  # (symbol, price, reason)

        for sym, pos in list(positions.items()):
            # locked_symbols 不出場
            if sym in config.locked_symbols:
                continue

            sym_data = all_data.get(sym, {})
            if date not in sym_data:
                continue

            close_price = sym_data[date]["close"]
            if close_price is None or close_price <= 0:
                continue

            # 取 sym 在 date 及之前的 close 序列
            sym_dates = sorted(sym_data.keys())
            closes_up_to = [
                sym_data[d]["close"]
                for d in sym_dates
                if d <= date and sym_data[d]["close"] is not None
            ]

            if not closes_up_to:
                continue

            # 更新 high_water_mark
            if close_price > pos["hwm"]:
                pos["hwm"] = close_price

            result: SignalResult = evaluate_exit(
                closes=closes_up_to,
                avg_price=pos["avg_price"],
                high_water_mark=pos["hwm"],
                params=config.signal_params,
            )

            if result.signal == "sell":
                symbols_to_sell.append((sym, close_price, result.reason))

        # 執行賣出
        for sym, price, reason in symbols_to_sell:
            pos = positions.pop(sym)
            qty = pos["qty"]
            proceeds = calc_sell_proceeds(price, qty, config.cost_params)
            cost_basis = calc_buy_cost(pos["entry_price"], qty, config.cost_params)
            pnl = round(proceeds - cost_basis, 2)

            entry_date_str = pos["entry_date"]
            entry_idx = date_to_idx.get(entry_date_str, date_idx)
            holding_days = date_idx - entry_idx

            cash_ref = [cash]  # 用 list 讓 closure 可修改（Python 3.x 限制）
            cash_ref[0] += proceeds
            cash = cash_ref[0]

            completed_trades.append({
                "symbol": sym,
                "side": "sell",
                "entry_date": entry_date_str,
                "exit_date": date,
                "entry_price": pos["entry_price"],
                "exit_price": price,
                "qty": qty,
                "pnl": pnl,
                "holding_days": holding_days,
                "reason": reason,
            })

        # --- 3b. 買入掃描 ---
        # 已持倉數量
        held_count = len(positions)
        available_slots = config.max_positions - held_count

        if available_slots > 0:
            nav = cash  # 當日 NAV（持倉以 avg_price 估值）
            for sym, pos in positions.items():
                sym_data = all_data.get(sym, {})
                if date in sym_data:
                    nav += sym_data[date]["close"] * pos["qty"]
                else:
                    nav += pos["avg_price"] * pos["qty"]

            usable_cash = cash * (1 - _CASH_BUFFER)

            for sym in config.symbols:
                if sym in positions:
                    continue  # 已持倉
                if available_slots <= 0:
                    break

                sym_data = all_data.get(sym, {})
                if date not in sym_data:
                    continue

                close_price = sym_data[date]["close"]
                if close_price is None or close_price <= 0:
                    continue

                sym_dates = sorted(sym_data.keys())
                closes_up_to = [
                    sym_data[d]["close"]
                    for d in sym_dates
                    if d <= date and sym_data[d]["close"] is not None
                ]

                result = evaluate_entry(
                    closes=closes_up_to,
                    params=config.signal_params,
                )

                if result.signal != "buy":
                    continue

                # 計算可買張數（最多 max_single_pct * nav）
                max_invest = min(usable_cash, nav * config.max_single_pct)
                lots = int(max_invest // (close_price * _LOT_SIZE))

                if lots >= 1:
                    qty = lots * _LOT_SIZE
                elif usable_cash >= close_price:
                    # odd-lot fallback（零股）
                    qty = int(usable_cash // close_price)
                else:
                    continue

                if qty <= 0:
                    continue

                total_cost = calc_buy_cost(close_price, qty, config.cost_params)
                if total_cost > usable_cash:
                    # 嘗試縮減 qty
                    if lots >= 2:
                        qty = (lots - 1) * _LOT_SIZE
                        total_cost = calc_buy_cost(close_price, qty, config.cost_params)
                    if total_cost > usable_cash:
                        continue

                cash -= total_cost
                usable_cash -= total_cost

                positions[sym] = {
                    "qty": qty,
                    "avg_price": close_price,
                    "hwm": close_price,
                    "entry_date": date,
                    "entry_price": close_price,
                }
                available_slots -= 1

        # --- 3c. 計算當日 NAV 加入 equity_curve ---
        nav_today = cash
        for sym, pos in positions.items():
            sym_data = all_data.get(sym, {})
            if date in sym_data and sym_data[date]["close"]:
                nav_today += sym_data[date]["close"] * pos["qty"]
            else:
                nav_today += pos["avg_price"] * pos["qty"]

        equity_curve.append(nav_today)

    # ── 4. 回測結束：強制平倉所有剩餘持倉 ─────────────────────────
    last_date = all_dates[-1]
    last_date_idx = len(all_dates) - 1

    for sym, pos in list(positions.items()):
        sym_data = all_data.get(sym, {})
        if last_date in sym_data and sym_data[last_date]["close"]:
            price = sym_data[last_date]["close"]
        else:
            price = pos["avg_price"]

        qty = pos["qty"]
        proceeds = calc_sell_proceeds(price, qty, config.cost_params)
        cost_basis = calc_buy_cost(pos["entry_price"], qty, config.cost_params)
        pnl = round(proceeds - cost_basis, 2)

        entry_idx = date_to_idx.get(pos["entry_date"], last_date_idx)
        holding_days = last_date_idx - entry_idx

        cash += proceeds

        completed_trades.append({
            "symbol": sym,
            "side": "sell",
            "entry_date": pos["entry_date"],
            "exit_date": last_date,
            "entry_price": pos["entry_price"],
            "exit_price": price,
            "qty": qty,
            "pnl": pnl,
            "holding_days": holding_days,
            "reason": "end_of_backtest",
        })

    positions.clear()

    # 更新最後一筆 equity（強制平倉後）
    if equity_curve:
        equity_curve[-1] = cash

    metrics = calculate_metrics(equity_curve, completed_trades)

    return BacktestResult(
        trades=completed_trades,
        equity_curve=equity_curve,
        metrics=metrics,
    )
