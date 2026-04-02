"""Tests for strategy_auto_optimizer and optimization_quality_gate."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from openclaw.agents.optimization_quality_gate import (
    QualityGateConfig,
    QualityGateResult,
    evaluate_quality_gate,
)
from openclaw.perf_metrics import PerfMetrics


# ── fixtures ─────────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    """建立記憶體 DB 並初始化必要表。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            ts_submit TEXT,
            status TEXT DEFAULT 'filled'
        );
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            qty REAL,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            ts_fill TEXT
        );
        CREATE TABLE IF NOT EXISTS optimization_log (
            ts INTEGER,
            trigger_type TEXT,
            param_key TEXT,
            old_value REAL,
            new_value REAL,
            is_auto INTEGER,
            sample_n INTEGER,
            confidence REAL,
            rationale TEXT
        );
        CREATE TABLE IF NOT EXISTS risk_limits (
            limit_id TEXT PRIMARY KEY,
            scope TEXT,
            rule_name TEXT,
            rule_value REAL,
            enabled INTEGER DEFAULT 1,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT NOT NULL,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL DEFAULT 0,
            requires_human_approval INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            proposal_json TEXT,
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            decided_at INTEGER,
            decided_by TEXT,
            decision_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT PRIMARY KEY,
            ts TEXT,
            component TEXT,
            agent TEXT,
            model TEXT,
            decision_id TEXT,
            prompt_text TEXT,
            response_text TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            tools_json TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0,
            metadata_json TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS agent_loop_runs (
            run_id TEXT PRIMARY KEY,
            agent_name TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            status TEXT NOT NULL DEFAULT 'running',
            diagnosis_json TEXT,
            proposals_json TEXT,
            quality_gate_json TEXT,
            error_message TEXT
        );
    """)
    # 插入基本 risk_limits
    conn.execute(
        "INSERT INTO risk_limits (limit_id, scope, rule_name, rule_value, enabled) "
        "VALUES ('rl1', 'global', 'trailing_pct', 0.05, 1)"
    )
    conn.commit()
    return conn


def _make_metrics(
    sharpe: float = 1.0,
    mdd: float = 10.0,
    pf: float = 1.5,
    trades: int = 20,
    win_rate: float = 0.5,
) -> PerfMetrics:
    return PerfMetrics(
        total_return_pct=10.0,
        annualized_return_pct=12.0,
        sharpe_ratio=sharpe,
        max_drawdown_pct=mdd,
        max_drawdown_days=5,
        win_rate=win_rate,
        profit_factor=pf,
        avg_holding_days=3.0,
        total_trades=trades,
        avg_profit_per_trade=100.0,
    )


# ── Quality Gate Tests ───────────────────────────────────────────────────────

class TestQualityGate:
    def test_pass_all_checks(self):
        baseline = _make_metrics(sharpe=1.0, mdd=10.0, pf=1.5, trades=20)
        candidate = _make_metrics(sharpe=1.1, mdd=10.5, pf=1.6, trades=15)
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is True
        assert result.reason == "通過"
        assert all(result.checks.values())

    def test_fail_sharpe_improvement(self):
        baseline = _make_metrics(sharpe=1.0)
        candidate = _make_metrics(sharpe=1.02)  # < 0.05 improvement
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is False
        assert "Sharpe" in result.reason
        assert result.checks["sharpe_improvement"] is False

    def test_fail_mdd_ratio(self):
        baseline = _make_metrics(sharpe=1.0, mdd=10.0)
        candidate = _make_metrics(sharpe=1.1, mdd=12.0)  # ratio = 1.2 > 1.1
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is False
        assert "MDD" in result.reason

    def test_fail_profit_factor(self):
        baseline = _make_metrics(sharpe=1.0)
        candidate = _make_metrics(sharpe=1.1, pf=0.8)
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is False
        assert "profit_factor" in result.reason

    def test_fail_min_trades(self):
        baseline = _make_metrics(sharpe=1.0)
        candidate = _make_metrics(sharpe=1.1, trades=5)
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is False
        assert "交易筆數" in result.reason

    def test_custom_config(self):
        config = QualityGateConfig(
            min_sharpe_improvement=0.01,
            max_mdd_ratio=2.0,
            min_profit_factor=0.5,
            min_trades=3,
        )
        baseline = _make_metrics(sharpe=1.0, mdd=10.0)
        candidate = _make_metrics(sharpe=1.02, mdd=18.0, pf=0.6, trades=5)
        result = evaluate_quality_gate(baseline, candidate, config)
        assert result.passed is True

    def test_zero_baseline_mdd(self):
        baseline = _make_metrics(sharpe=1.0, mdd=0.0)
        candidate = _make_metrics(sharpe=1.1, mdd=5.0)
        result = evaluate_quality_gate(baseline, candidate)
        assert result.passed is False  # mdd_ratio = 999


# ── Strategy Auto Optimizer Tests ────────────────────────────────────────────

class TestStrategyAutoOptimizer:
    def test_ensure_schema(self):
        conn = _make_conn()
        from openclaw.agents.strategy_auto_optimizer import _ensure_schema
        _ensure_schema(conn)
        # Table should exist
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_loop_runs'"
        ).fetchone()
        assert row is not None

    def test_diagnose_no_trades(self):
        conn = _make_conn()
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        opt = StrategyAutoOptimizer()
        diagnosis = opt.diagnose_weak_rules(conn, window_days=28)
        assert diagnosis["sample_n"] == 0
        assert diagnosis["weak_params"] == []

    @patch("openclaw.agents.strategy_auto_optimizer.call_agent_llm")
    def test_propose_optimization(self, mock_llm):
        conn = _make_conn()
        mock_llm.return_value = {
            "summary": "建議收緊 trailing_pct",
            "confidence": 0.75,
            "action_type": "suggest",
            "proposals": [
                {"param_key": "trailing_pct", "action": "increase", "delta": 0.005, "reason": "low win rate"}
            ],
        }
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        opt = StrategyAutoOptimizer()
        diagnosis = {"window_days": 28, "sample_n": 50, "weak_params": [{"param": "win_rate", "value": 0.3, "issue": "low_win_rate", "severity": "high"}], "recent_adjustments": [], "current_risk_limits": [], "confidence": 0.8, "win_rate": 0.3, "profit_factor": 0.9}
        result = opt.propose_optimization(diagnosis, conn)
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["param_key"] == "trailing_pct"

    @patch("openclaw.agents.strategy_auto_optimizer.call_agent_llm")
    def test_run_no_weak_params(self, mock_llm):
        """策略正常時應回傳 observe，不呼叫 LLM。"""
        conn = _make_conn()
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer, _ensure_schema
        _ensure_schema(conn)
        opt = StrategyAutoOptimizer()
        result = opt.run_strategy_auto_optimizer(conn=conn)
        assert result.action_type == "observe"
        assert result.success is True
        mock_llm.assert_not_called()

    @patch("openclaw.backtest_engine.run_backtest")
    @patch("openclaw.agents.strategy_auto_optimizer.call_agent_llm")
    def test_run_gate_rejected(self, mock_llm, mock_bt):
        """品質閘門未通過時不應建立 proposal。"""
        conn = _make_conn()
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer, _ensure_schema
        _ensure_schema(conn)

        # 插入交易資料讓 diagnose 找到弱項
        _insert_losing_trades(conn, count=15)

        mock_llm.return_value = {
            "summary": "建議調整",
            "confidence": 0.7,
            "action_type": "suggest",
            "proposals": [{"param_key": "trailing_pct", "action": "increase", "delta": 0.005, "reason": "test"}],
        }

        # 回測結果：Sharpe 沒有改善
        from openclaw.backtest_engine import BacktestResult
        mock_bt.return_value = BacktestResult(
            trades=[],
            equity_curve=[1_000_000, 1_000_000],
            metrics=_make_metrics(sharpe=1.0, trades=15),
        )

        opt = StrategyAutoOptimizer()
        result = opt.run_strategy_auto_optimizer(conn=conn)
        assert result.action_type == "observe"
        assert "品質閘門" in result.summary or "未通過" in result.summary

    def test_agent_loop_runs_recorded(self):
        """每次執行應寫入 agent_loop_runs。"""
        conn = _make_conn()
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer, _ensure_schema
        _ensure_schema(conn)
        opt = StrategyAutoOptimizer()
        opt.run_strategy_auto_optimizer(conn=conn)
        rows = conn.execute("SELECT * FROM agent_loop_runs").fetchall()
        assert len(rows) == 1
        assert dict(rows[0])["agent_name"] == "StrategyAutoOptimizer"
        assert dict(rows[0])["status"] in ("completed", "error")


class TestApplyAdjustments:
    def test_apply_trailing_pct_increase(self):
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        from openclaw.signal_logic import SignalParams
        opt = StrategyAutoOptimizer()
        base = SignalParams()
        adjustments = {
            "proposals": [
                {"param_key": "trailing_pct", "action": "increase", "delta": 0.01}
            ]
        }
        result = opt._apply_adjustments_to_params(base, adjustments)
        assert result.trailing_pct == base.trailing_pct + 0.01

    def test_apply_stop_loss_decrease(self):
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        from openclaw.signal_logic import SignalParams
        opt = StrategyAutoOptimizer()
        base = SignalParams()
        adjustments = {
            "proposals": [
                {"param_key": "stop_loss_pct", "action": "decrease", "delta": 0.005}
            ]
        }
        result = opt._apply_adjustments_to_params(base, adjustments)
        assert result.stop_loss_pct == base.stop_loss_pct - 0.005

    def test_apply_clamp_minimum(self):
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        from openclaw.signal_logic import SignalParams
        opt = StrategyAutoOptimizer()
        base = SignalParams()
        adjustments = {
            "proposals": [
                {"param_key": "trailing_pct", "action": "decrease", "delta": 999}
            ]
        }
        result = opt._apply_adjustments_to_params(base, adjustments)
        assert result.trailing_pct == 0.01  # clamped to min

    def test_no_proposals(self):
        from openclaw.agents.strategy_auto_optimizer import StrategyAutoOptimizer
        from openclaw.signal_logic import SignalParams
        opt = StrategyAutoOptimizer()
        base = SignalParams()
        result = opt._apply_adjustments_to_params(base, {"proposals": []})
        assert result is base  # same object, no changes


# ── Helpers ──────────────────────────────────────────────────────────────────

def _insert_losing_trades(conn: sqlite3.Connection, count: int = 15) -> None:
    """插入一批虧損交易讓 diagnose 偵測到弱項。"""
    import uuid
    from datetime import datetime, timedelta

    for i in range(count):
        ts = (datetime.now() - timedelta(days=i + 1)).isoformat()
        buy_id = f"buy_{uuid.uuid4().hex[:8]}"
        sell_id = f"sell_{uuid.uuid4().hex[:8]}"
        symbol = "2330"

        conn.execute(
            "INSERT INTO orders (order_id, symbol, side, ts_submit, status) VALUES (?,?,?,?,?)",
            (buy_id, symbol, "buy", ts, "filled"),
        )
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, qty, price, fee, tax, ts_fill) VALUES (?,?,?,?,?,?,?)",
            (f"f_{buy_id}", buy_id, 1000, 600.0, 0, 0, ts),
        )
        conn.execute(
            "INSERT INTO orders (order_id, symbol, side, ts_submit, status) VALUES (?,?,?,?,?)",
            (sell_id, symbol, "sell", ts, "filled"),
        )
        conn.execute(
            "INSERT INTO fills (fill_id, order_id, qty, price, fee, tax, ts_fill) VALUES (?,?,?,?,?,?,?)",
            (f"f_{sell_id}", sell_id, 1000, 580.0, 0, 0, ts),
        )
    conn.commit()
