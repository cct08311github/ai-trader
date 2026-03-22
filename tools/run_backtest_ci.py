#!/usr/bin/env python3
"""Deterministic CI backtest validation for signal changes."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import tempfile
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from openclaw.backtest_engine import BacktestConfig, run_backtest
from openclaw.cost_model import CostParams
from openclaw.signal_logic import SignalParams

_PROJECT = Path(__file__).resolve().parents[1]
_DEFAULT_BASELINE = _PROJECT / "config" / "backtest_baseline.json"


def load_baseline(path: str | Path = _DEFAULT_BASELINE) -> dict:
    return json.loads(Path(path).read_text())


def _business_days(start: date, days: int) -> list[date]:
    out: list[date] = []
    cursor = start
    while len(out) < days:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _synthetic_rows(
    symbol: str,
    base: float,
    amplitude: float,
    trend: float,
    phase: float,
    start: date,
    days: int,
) -> list[tuple]:
    rows = []
    for idx, trading_day in enumerate(_business_days(start, days)):
        close = round(base + amplitude * math.sin((idx / 3.0) + phase) + trend * idx, 2)
        rows.append(
            (
                trading_day.isoformat(),
                symbol,
                round(close * 0.99, 2),
                round(close * 1.01, 2),
                round(close * 0.98, 2),
                close,
                10000 + idx * 50,
            )
        )
    return rows


def create_synthetic_backtest_db(path: str | Path, days: int, start_date: str) -> str:
    db_path = str(path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE eod_prices (
            trade_date TEXT,
            symbol TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER
        )
        """
    )
    start = date.fromisoformat(start_date)
    rows = []
    rows += _synthetic_rows("2330", 100.0, 8.0, 0.05, 0.0, start, days)
    rows += _synthetic_rows("2317", 82.0, 6.0, 0.04, 0.7, start, days)
    rows += _synthetic_rows("2454", 120.0, 10.0, 0.06, 1.4, start, days)
    conn.executemany("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db_path


def metrics_to_dict(result) -> dict:
    data = asdict(result.metrics)
    data["win_rate_pct"] = round(float(data.pop("win_rate", 0.0)) * 100, 4)
    for key, value in list(data.items()):
        if isinstance(value, float):
            data[key] = round(value, 4)
    return data


def run_ci_backtest(baseline: dict) -> dict:
    dataset = baseline["dataset"]
    params = SignalParams(**baseline["signal_params"])

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    create_synthetic_backtest_db(
        db_path,
        days=int(dataset["days"]),
        start_date=dataset["start_date"],
    )

    config = BacktestConfig(
        symbols=list(dataset["symbols"]),
        start_date=dataset["start_date"],
        end_date=_business_days(date.fromisoformat(dataset["start_date"]), int(dataset["days"]))[-1].isoformat(),
        initial_capital=1_000_000.0,
        signal_params=params,
        max_positions=3,
        max_single_pct=0.30,
        cost_params=CostParams(),
        slippage_bps=10,
    )
    result = run_backtest(config, db_path)
    return metrics_to_dict(result)


def compare_to_baseline(current: dict, baseline: dict) -> tuple[list[str], dict]:
    failures: list[str] = []
    diff: dict[str, float] = {}

    baseline_metrics = baseline["metrics"]
    thresholds = baseline["thresholds"]
    allowed_regression = baseline.get("allowed_regression", {})

    for key, baseline_value in baseline_metrics.items():
        current_value = current.get(key)
        if isinstance(baseline_value, (int, float)) and isinstance(current_value, (int, float)):
            diff[key] = round(current_value - baseline_value, 4)

    if current["win_rate_pct"] < thresholds["min_win_rate_pct"]:
        failures.append(
            f"win_rate_pct {current['win_rate_pct']:.2f} < {thresholds['min_win_rate_pct']:.2f}"
        )
    if current["max_drawdown_pct"] > thresholds["max_drawdown_pct"]:
        failures.append(
            f"max_drawdown_pct {current['max_drawdown_pct']:.2f} > {thresholds['max_drawdown_pct']:.2f}"
        )
    if current["total_trades"] < thresholds["min_total_trades"]:
        failures.append(
            f"total_trades {current['total_trades']} < {thresholds['min_total_trades']}"
        )

    for key, allowed_drop in allowed_regression.items():
        if diff.get(key, 0.0) < allowed_drop:
            failures.append(
                f"{key} regression {diff[key]:.4f} < allowed {allowed_drop:.4f}"
            )

    return failures, diff


def build_report(current: dict, baseline: dict, failures: list[str], diff: dict) -> dict:
    return {
        "status": "failed" if failures else "passed",
        "baseline_path": str(_DEFAULT_BASELINE),
        "dataset": baseline["dataset"],
        "current_metrics": current,
        "baseline_metrics": baseline["metrics"],
        "diff_vs_baseline": diff,
        "thresholds": baseline["thresholds"],
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic CI backtest validation.")
    parser.add_argument("--baseline", default=str(_DEFAULT_BASELINE))
    parser.add_argument("--report-file", default="")
    args = parser.parse_args(argv)

    baseline = load_baseline(args.baseline)
    current = run_ci_backtest(baseline)
    failures, diff = compare_to_baseline(current, baseline)
    report = build_report(current, baseline, failures, diff)
    report_json = json.dumps(report, ensure_ascii=False, indent=2)
    print(report_json)

    if args.report_file:
        Path(args.report_file).write_text(report_json + "\n")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
