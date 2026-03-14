# tests/test_param_optimizer.py
"""TDD tests for param_optimizer.py — Grid Search Parameter Optimizer."""
from __future__ import annotations

import sqlite3
import random
import tempfile
import os

import pytest

from openclaw.param_optimizer import (
    OptimizationResult,
    split_dates,
    grid_search,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _create_grid_db(path: str, n_days: int = 60) -> None:
    """建立測試用 SQLite DB，含 n_days 天的 eod_prices 資料。"""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE eod_prices "
        "(trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER)"
    )
    random.seed(42)
    base = 100.0
    for i in range(n_days):
        day_num = i + 1
        month = (day_num - 1) // 28 + 1
        day_in_month = (day_num - 1) % 28 + 1
        day = f"2026-{month:02d}-{day_in_month:02d}"
        close = base + random.gauss(0, 2) + i * 0.1
        conn.execute(
            "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (day, "2330", close - 1, close + 1, close - 2, round(close, 2), 10000),
        )
    conn.commit()
    conn.close()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSplitDates:
    def test_split_dates_70_30(self):
        """10 個日期 → 7 train, 3 test。"""
        dates = [f"2026-01-{i:02d}" for i in range(1, 11)]  # 10 dates
        train, test = split_dates(dates)
        assert len(train) == 7
        assert len(test) == 3
        # 確認連續性（不重疊、不遺漏）
        assert train + test == dates

    def test_split_dates_empty(self):
        """空列表 → 兩個空列表。"""
        train, test = split_dates([])
        assert train == []
        assert test == []


class TestGridSearch:
    def test_grid_search_returns_sorted_results(self):
        """使用 1-combo 的 tiny grid，驗證回傳 OptimizationResult 且結構正確。"""
        small_grid = {
            "ma_short": [5],
            "ma_long": [20],
            "rsi_entry_max": [70],
            "stop_loss_pct": [0.05],
            "take_profit_pct": [0.08],
            "trailing_pct": [0.05],
        }

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            _create_grid_db(db_path, n_days=60)

            result = grid_search(
                symbols=["2330"],
                db_path=db_path,
                param_grid=small_grid,
                max_workers=1,
            )

            # 回傳型別正確
            assert isinstance(result, OptimizationResult)

            # all_results 是 list
            assert isinstance(result.all_results, list)

            # best_params 是 dict
            assert isinstance(result.best_params, dict)

            # 日期範圍字串不為空
            assert result.in_sample_range != ""
            assert result.out_of_sample_range != ""

            # 若有 valid results，應按 oos_sharpe 降序排列
            if len(result.all_results) >= 2:
                sharpes = [r["oos_sharpe"] for r in result.all_results]
                assert sharpes == sorted(sharpes, reverse=True)

            # 若有 valid results，best_params 應等於第一筆的 params
            if result.all_results:
                assert result.best_params == result.all_results[0]["params"]

        finally:
            os.unlink(db_path)
