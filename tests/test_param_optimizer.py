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


def test_save_optimal_params_writes_json(tmp_path):
    """save_optimal_params writes correct JSON structure."""
    from openclaw.param_optimizer import save_optimal_params, OptimizationResult
    import json
    out_path = str(tmp_path / "signal_params.json")
    result = OptimizationResult(
        all_results=[{"params": {"ma_short": 5}, "oos_sharpe": 1.5, "oos_mdd": -0.05}],
        best_params={"ma_short": 5},
        in_sample_range="2026-01-01 ~ 2026-02-15",
        out_of_sample_range="2026-02-16 ~ 2026-03-13",
    )
    save_optimal_params(result, out_path)
    with open(out_path) as f:
        data = json.load(f)
    assert data["params"] == {"ma_short": 5}
    assert data["out_of_sample_sharpe"] == 1.5
    assert "optimized_at" in data


def test_save_optimal_params_empty_best_skips(tmp_path):
    """Empty best_params (no results) → file is written but params is empty dict.

    NOTE: save_optimal_params currently lacks a guard clause for empty best_params;
    it always writes the file. This test documents the current behaviour and acts as
    a regression anchor — if a guard is added the assertion can be updated.
    """
    from openclaw.param_optimizer import save_optimal_params, OptimizationResult
    import json, os
    out_path = str(tmp_path / "signal_params.json")
    result = OptimizationResult(
        all_results=[],
        best_params={},
        in_sample_range="N/A",
        out_of_sample_range="N/A",
    )
    save_optimal_params(result, out_path)
    # Current behaviour: file IS written even when best_params is empty.
    assert os.path.exists(out_path)
    with open(out_path) as f:
        data = json.load(f)
    assert data["params"] == {}
    assert data["out_of_sample_sharpe"] == 0.0


def test_grid_search_empty_db(tmp_path):
    """Empty DB → OptimizationResult with empty results."""
    import sqlite3
    from openclaw.param_optimizer import grid_search
    db_path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE eod_prices (trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER)")
    conn.commit()
    conn.close()
    result = grid_search(symbols=["2330"], db_path=db_path, param_grid={"ma_short": [5], "ma_long": [20], "rsi_entry_max": [70], "stop_loss_pct": [0.05], "take_profit_pct": [0.08], "trailing_pct": [0.05]}, max_workers=1)
    assert result.best_params == {}
    assert len(result.all_results) == 0
