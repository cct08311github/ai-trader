from __future__ import annotations

import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import run_backtest_ci as rbc


def _baseline() -> dict:
    return {
        "dataset": {
            "days": 60,
            "start_date": "2025-01-02",
            "symbols": ["2330", "2317", "2454"],
        },
        "signal_params": {
            "ma_short": 3,
            "ma_long": 7,
            "rsi_entry_max": 100.0,
            "take_profit_pct": 0.04,
            "stop_loss_pct": 0.04,
            "trailing_pct": 0.08,
            "trailing_pct_tight": 0.05,
            "trailing_profit_threshold": 0.04,
        },
        "thresholds": {
            "min_win_rate_pct": 40.0,
            "max_drawdown_pct": 15.0,
            "min_total_trades": 5,
        },
        "allowed_regression": {
            "total_return_pct": -5.0,
            "sharpe_ratio": -2.0,
            "total_trades": -3,
        },
        "metrics": {
            "total_return_pct": 10.2736,
            "annualized_return_pct": 50.7928,
            "sharpe_ratio": 9.4361,
            "max_drawdown_pct": 0.057,
            "win_rate_pct": 100.0,
            "profit_factor": 0.0,
            "avg_holding_days": 2.0,
            "total_trades": 9,
        },
    }


def test_create_synthetic_backtest_db(tmp_path):
    db_path = tmp_path / "fixture.db"
    rbc.create_synthetic_backtest_db(db_path, days=10, start_date="2025-01-02")

    import sqlite3

    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM eod_prices").fetchone()[0]
    conn.close()
    assert count == 30


def test_run_ci_backtest_produces_trades():
    metrics = rbc.run_ci_backtest(_baseline())
    assert metrics["total_trades"] >= 5
    assert metrics["win_rate_pct"] >= 40.0


def test_compare_to_baseline_passes_for_current_config():
    baseline = _baseline()
    current = rbc.run_ci_backtest(baseline)
    failures, diff = rbc.compare_to_baseline(current, baseline)
    assert failures == []
    assert "total_return_pct" in diff


def test_compare_to_baseline_flags_regression():
    baseline = _baseline()
    current = dict(baseline["metrics"])
    current["total_return_pct"] = 1.0
    current["sharpe_ratio"] = 1.0
    current["win_rate_pct"] = 20.0
    current["max_drawdown_pct"] = 20.0
    current["total_trades"] = 1

    failures, _ = rbc.compare_to_baseline(current, baseline)
    assert any("win_rate_pct" in failure for failure in failures)
    assert any("max_drawdown_pct" in failure for failure in failures)
    assert any("total_trades" in failure for failure in failures)


def test_main_writes_report_file(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    report_path = tmp_path / "report.json"
    baseline_path.write_text(json.dumps(_baseline()))

    rc = rbc.main(["--baseline", str(baseline_path), "--report-file", str(report_path)])

    assert rc == 0
    report = json.loads(report_path.read_text())
    assert report["status"] == "passed"
    assert report["current_metrics"]["total_trades"] >= 5
