"""
perf_metrics.py — Backtest performance metrics calculation.

Provides PerfMetrics dataclass and calculate_metrics() for evaluating
strategy equity curves and trade histories.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
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


def _zeros() -> PerfMetrics:
    return PerfMetrics(
        total_return_pct=0.0,
        annualized_return_pct=0.0,
        sharpe_ratio=0.0,
        max_drawdown_pct=0.0,
        max_drawdown_days=0,
        win_rate=0.0,
        profit_factor=0.0,
        avg_holding_days=0.0,
        total_trades=0,
        avg_profit_per_trade=0.0,
    )


def calculate_metrics(
    equity_curve: Sequence[float],
    trades: Sequence[dict],
    risk_free_rate: float = 0.015,
    trading_days_per_year: int = 252,
) -> PerfMetrics:
    """Calculate backtest performance metrics from equity curve and trade list.

    Args:
        equity_curve: Sequence of portfolio values (e.g. [100, 102, 101, ...]).
                      Must have at least 2 data points for meaningful results.
        trades: Sequence of dicts with keys:
                  - "pnl" (float): profit/loss for the trade
                  - "holding_days" (int): number of days held
        risk_free_rate: Annual risk-free rate (default 0.015 = 1.5% 台灣定存).
        trading_days_per_year: Trading days per year for annualisation (default 252).

    Returns:
        PerfMetrics with all computed statistics, or all-zeros if insufficient data.
    """
    equity = list(equity_curve)

    # Guard: need at least 2 points in equity curve for any meaningful calculation
    if len(equity) < 2:
        return _zeros()

    # --- Total return ---
    total_return_pct = (equity[-1] - equity[0]) / equity[0] * 100.0

    # --- Annualised return ---
    n_days = len(equity) - 1  # number of periods
    if n_days > 0 and equity[0] != 0:
        total_return_ratio = equity[-1] / equity[0]
        annualized_return_pct = (
            (total_return_ratio ** (trading_days_per_year / n_days)) - 1.0
        ) * 100.0
    else:
        annualized_return_pct = 0.0

    # --- Daily returns ---
    daily_returns = [
        (equity[i] - equity[i - 1]) / equity[i - 1]
        for i in range(1, len(equity))
    ]

    # --- Sharpe ratio ---
    daily_rf = risk_free_rate / trading_days_per_year
    if len(daily_returns) >= 2:
        avg_daily = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_daily) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        std_daily = math.sqrt(variance) if variance > 0 else 0.0
        if std_daily > 0:
            sharpe_ratio = (avg_daily - daily_rf) / std_daily * math.sqrt(trading_days_per_year)
        else:
            sharpe_ratio = 0.0
    else:
        sharpe_ratio = 0.0

    # --- Max drawdown ---
    max_drawdown_pct = 0.0
    max_drawdown_days = 0
    peak = equity[0]
    peak_idx = 0
    for i, val in enumerate(equity):
        if val >= peak:
            peak = val
            peak_idx = i
        else:
            dd = (peak - val) / peak * 100.0
            dd_days = i - peak_idx
            if dd > max_drawdown_pct:
                max_drawdown_pct = dd
                max_drawdown_days = dd_days

    # --- Trade statistics ---
    total_trades = len(trades)
    if total_trades == 0:
        return PerfMetrics(
            total_return_pct=total_return_pct,
            annualized_return_pct=annualized_return_pct,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            max_drawdown_days=max_drawdown_days,
            win_rate=0.0,
            profit_factor=0.0,
            avg_holding_days=0.0,
            total_trades=0,
            avg_profit_per_trade=0.0,
        )

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    win_rate = len(wins) / total_trades

    total_win_pnl = sum(t["pnl"] for t in wins)
    total_loss_pnl = abs(sum(t["pnl"] for t in losses))
    profit_factor = (total_win_pnl / total_loss_pnl) if total_loss_pnl > 0 else 0.0

    avg_holding_days = sum(t["holding_days"] for t in trades) / total_trades
    avg_profit_per_trade = sum(t["pnl"] for t in trades) / total_trades

    return PerfMetrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=max_drawdown_pct,
        max_drawdown_days=max_drawdown_days,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_holding_days=avg_holding_days,
        total_trades=total_trades,
        avg_profit_per_trade=avg_profit_per_trade,
    )
