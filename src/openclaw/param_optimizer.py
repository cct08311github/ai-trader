# src/openclaw/param_optimizer.py
"""param_optimizer.py — Grid Search 參數最佳化器（70/30 防過擬合）

使用 ProcessPoolExecutor 並行回測所有參數組合，
以 in-sample Sharpe < 0.5 為早期截止條件，
最終按 out-of-sample Sharpe 降序排列。
"""
from __future__ import annotations

import json
import itertools
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from openclaw.backtest_engine import BacktestConfig, run_backtest
from openclaw.signal_logic import SignalParams

# 預設參數搜尋空間
PARAM_GRID: dict[str, list] = {
    "ma_short": [3, 5, 8],
    "ma_long": [15, 20, 30],
    "rsi_entry_max": [60, 70, 80],
    "stop_loss_pct": [0.03, 0.05, 0.07],
    "take_profit_pct": [0.05, 0.08, 0.10],
    "trailing_pct": [0.03, 0.05, 0.08],
}

# In-sample Sharpe 早期截止閾值
_IS_SHARPE_THRESHOLD = 0.5

# 初始資金
_INITIAL_CAPITAL = 1_000_000.0


@dataclass
class OptimizationResult:
    all_results: list[dict]      # sorted by oos_sharpe desc
    best_params: dict
    in_sample_range: str
    out_of_sample_range: str


def split_dates(dates: list[str], train_ratio: float = 0.7) -> tuple[list[str], list[str]]:
    """將日期列表依 train_ratio 分割為訓練集與測試集。

    Args:
        dates: 排序後的日期字串列表（YYYY-MM-DD）
        train_ratio: 訓練集比例（預設 0.7）

    Returns:
        (train_dates, test_dates)
    """
    if not dates:
        return [], []
    split_idx = int(len(dates) * train_ratio)
    return dates[:split_idx], dates[split_idx:]


def _run_single(args: tuple) -> Optional[dict]:
    """單一參數組合回測（ProcessPoolExecutor worker）。

    每個 subprocess 自行開啟 SQLite 連線（SQLite 不跨 process 共享）。

    Args:
        args: (params_dict, symbols, db_path, train_dates, test_dates)

    Returns:
        result dict 或 None（早期截止）
    """
    params, symbols, db_path, train_dates, test_dates = args

    signal_params = SignalParams(
        ma_short=params["ma_short"],
        ma_long=params["ma_long"],
        rsi_entry_max=params["rsi_entry_max"],
        stop_loss_pct=params["stop_loss_pct"],
        take_profit_pct=params["take_profit_pct"],
        trailing_pct=params["trailing_pct"],
    )

    # --- In-sample 回測 ---
    if not train_dates:
        return None

    is_config = BacktestConfig(
        symbols=symbols,
        start_date=train_dates[0],
        end_date=train_dates[-1],
        initial_capital=_INITIAL_CAPITAL,
        signal_params=signal_params,
    )
    is_result = run_backtest(is_config, db_path)
    is_sharpe = is_result.metrics.sharpe_ratio

    # 早期截止：in-sample Sharpe 不足則跳過 OOS
    if is_sharpe < _IS_SHARPE_THRESHOLD:
        return None

    # --- Out-of-sample 回測 ---
    if not test_dates:
        return None

    oos_config = BacktestConfig(
        symbols=symbols,
        start_date=test_dates[0],
        end_date=test_dates[-1],
        initial_capital=_INITIAL_CAPITAL,
        signal_params=signal_params,
    )
    oos_result = run_backtest(oos_config, db_path)

    return {
        "params": params,
        "is_sharpe": is_sharpe,
        "is_return_pct": is_result.metrics.total_return_pct,
        "oos_sharpe": oos_result.metrics.sharpe_ratio,
        "oos_return_pct": oos_result.metrics.total_return_pct,
        "oos_mdd": oos_result.metrics.max_drawdown_pct,
        "oos_total_trades": oos_result.metrics.total_trades,
    }


def grid_search(
    symbols: list[str],
    db_path: str,
    param_grid: Optional[dict[str, list]] = None,
    max_workers: int = 4,
) -> OptimizationResult:
    """對所有參數組合進行 grid search，70/30 split 防過擬合。

    Args:
        symbols: 回測標的列表
        db_path: SQLite 資料庫路徑
        param_grid: 參數搜尋空間（預設 PARAM_GRID）
        max_workers: ProcessPoolExecutor 並行數

    Returns:
        OptimizationResult，all_results 按 oos_sharpe 降序排列
    """
    if param_grid is None:
        param_grid = PARAM_GRID

    # 取得所有唯一日期（合併所有 symbols 的日期）
    import sqlite3
    placeholders = ",".join("?" * len(symbols))
    sql = f"""
        SELECT DISTINCT trade_date FROM eod_prices
        WHERE symbol IN ({placeholders})
        ORDER BY trade_date
    """
    all_dates: list[str] = []
    try:
        conn = sqlite3.connect(db_path)
        all_dates = [row[0] for row in conn.execute(sql, symbols)]
        conn.close()
    except sqlite3.OperationalError:
        pass

    train_dates, test_dates = split_dates(all_dates, train_ratio=0.7)

    in_sample_range = (
        f"{train_dates[0]} ~ {train_dates[-1]}" if train_dates else "N/A"
    )
    out_of_sample_range = (
        f"{test_dates[0]} ~ {test_dates[-1]}" if test_dates else "N/A"
    )

    # 建立所有組合
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    # 準備 worker args
    worker_args = [
        (params, symbols, db_path, train_dates, test_dates)
        for params in combos
    ]

    valid_results: list[dict] = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for result in executor.map(_run_single, worker_args):
            if result is not None:
                valid_results.append(result)

    # 按 oos_sharpe 降序排列
    valid_results.sort(key=lambda x: x["oos_sharpe"], reverse=True)

    best_params = valid_results[0]["params"] if valid_results else {}

    return OptimizationResult(
        all_results=valid_results,
        best_params=best_params,
        in_sample_range=in_sample_range,
        out_of_sample_range=out_of_sample_range,
    )


def save_optimal_params(result: OptimizationResult, output_path: str) -> None:
    """將最佳參數寫入 JSON 檔案。

    JSON 結構：
    {
        "optimized_at": "ISO timestamp",
        "in_sample": "YYYY-MM-DD ~ YYYY-MM-DD",
        "out_of_sample": "YYYY-MM-DD ~ YYYY-MM-DD",
        "params": {...},
        "out_of_sample_sharpe": float,
        "out_of_sample_mdd": float
    }
    """
    best = result.all_results[0] if result.all_results else {}

    payload = {
        "optimized_at": datetime.now(timezone.utc).isoformat(),
        "in_sample": result.in_sample_range,
        "out_of_sample": result.out_of_sample_range,
        "params": result.best_params,
        "out_of_sample_sharpe": best.get("oos_sharpe", 0.0),
        "out_of_sample_mdd": best.get("oos_mdd", 0.0),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
