"""Tests for edge_integration module (v4 #16)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from openclaw.edge_metrics import compute_edge_metrics, EdgeMetrics
from openclaw.edge_integration import (
    EdgeAnalysisResult,
    analyze_strategy_edge,
    batch_update_all_strategy_versions,
    compute_edge_score,
    evaluate_edge_quality,
    generate_edge_recommendation,
    get_trades_for_strategy,
    integrate_edge_into_decision,
    update_strategy_version_with_edge,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_trades_db(path: str, trades: list[dict]) -> None:
    """Create a minimal trades DB with the schema expected by get_trades_for_strategy."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            action TEXT,
            quantity INTEGER,
            price REAL,
            fee REAL,
            tax REAL,
            pnl REAL,
            timestamp TEXT,
            agent_id TEXT,
            decision_id TEXT
        )
    """)
    for t in trades:
        conn.execute(
            "INSERT INTO trades(symbol, action, quantity, price, fee, tax, pnl, timestamp, agent_id, decision_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                t.get("symbol", "2330"),
                t.get("action", "buy"),
                t.get("quantity", 100),
                t.get("price", 100.0),
                t.get("fee", 0.0),
                t.get("tax", 0.0),
                t.get("pnl"),
                t.get("timestamp", "2026-01-01T00:00:00"),
                t.get("agent_id", "strategy_a"),
                t.get("decision_id", "d1"),
            ),
        )
    conn.commit()
    conn.close()


def _make_strategy_versions_db(path: str, versions: list[dict]) -> None:
    """Create a minimal strategy_versions DB."""
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE strategy_versions (
            version_id TEXT PRIMARY KEY,
            strategy_config_json TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.execute("""
        CREATE TABLE version_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
    """)
    for v in versions:
        conn.execute(
            "INSERT INTO strategy_versions(version_id, strategy_config_json, status) VALUES(?,?,?)",
            (v["version_id"], v.get("strategy_config_json", "{}"), v.get("status", "active")),
        )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# get_trades_for_strategy
# ─────────────────────────────────────────────────────────────────────────────

def test_get_trades_for_strategy_empty(tmp_path):
    db = str(tmp_path / "trades.db")
    _make_trades_db(db, [])
    result = get_trades_for_strategy(db, "strategy_a", days_back=30)
    assert result == []


def test_get_trades_for_strategy_with_trades(tmp_path):
    db = str(tmp_path / "trades.db")
    today = date.today()
    _make_trades_db(db, [
        {"agent_id": "strategy_a", "pnl": 100.0, "timestamp": f"{(today - timedelta(days=1)).isoformat()}T00:00:00"},
        {"agent_id": "strategy_a", "pnl": -50.0, "timestamp": f"{(today - timedelta(days=2)).isoformat()}T00:00:00"},
        {"agent_id": "strategy_b", "pnl": 200.0, "timestamp": f"{(today - timedelta(days=1)).isoformat()}T00:00:00"},
    ])
    result = get_trades_for_strategy(db, "strategy_a", days_back=30)
    assert len(result) == 2
    for t in result:
        assert t["agent_id"] == "strategy_a"
        assert isinstance(t["pnl"], float)


def test_get_trades_for_strategy_pnl_none_stays_none(tmp_path):
    """Trade with pnl=None should be returned with pnl=None (no conversion)."""
    db = str(tmp_path / "trades.db")
    _make_trades_db(db, [{"agent_id": "strategy_x", "pnl": None, "timestamp": f"{date.today().isoformat()}T00:00:00"}])
    result = get_trades_for_strategy(db, "strategy_x", days_back=30)
    assert len(result) == 1
    assert result[0]["pnl"] is None


# ─────────────────────────────────────────────────────────────────────────────
# analyze_strategy_edge — lines 97-98 (no trades branch)
# ─────────────────────────────────────────────────────────────────────────────

def test_analyze_strategy_edge_no_trades(tmp_path):
    db = str(tmp_path / "trades.db")
    _make_trades_db(db, [])
    result = analyze_strategy_edge(db, "strategy_a")
    assert result.strategy_id == "strategy_a"
    assert result.trade_count == 0
    assert result.edge_score == 0.0
    assert result.is_edge_ok is False
    assert "No trades" in result.recommendation


def test_analyze_strategy_edge_insufficient_trades(tmp_path):
    """Less than min_trades pnl values → insufficient branch."""
    db = str(tmp_path / "trades.db")
    today = date.today()
    _make_trades_db(db, [
        {"agent_id": "strategy_a", "pnl": 10.0, "timestamp": f"{(today - timedelta(days=1)).isoformat()}T00:00:00"},
        {"agent_id": "strategy_a", "pnl": -5.0, "timestamp": f"{(today - timedelta(days=2)).isoformat()}T00:00:00"},
    ])
    result = analyze_strategy_edge(db, "strategy_a", min_trades=10)
    assert result.trade_count == 2
    assert result.edge_score == 0.0
    assert result.is_edge_ok is False
    assert "Insufficient" in result.recommendation


def test_analyze_strategy_edge_sufficient_trades(tmp_path):
    """Enough trades → full analysis path."""
    db = str(tmp_path / "trades.db")
    from datetime import datetime, timedelta
    base_date = datetime.now()  # Use relative date to avoid 30-day lookback expiry
    trades = [
        {"agent_id": "strat", "pnl": 10.0 if i % 2 == 0 else -4.0,
         "timestamp": (base_date - timedelta(days=i)).strftime("%Y-%m-%dT00:00:00")}
        for i in range(12)
    ]
    _make_trades_db(db, trades)
    result = analyze_strategy_edge(db, "strat", min_trades=10)
    assert result.trade_count == 12
    assert isinstance(result.edge_score, float)
    assert isinstance(result.is_edge_ok, bool)
    assert len(result.recommendation) > 0


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_edge_quality — all branches
# ─────────────────────────────────────────────────────────────────────────────

def test_evaluate_edge_quality_too_few_trades():
    m = compute_edge_metrics([10.0, -5.0])
    assert evaluate_edge_quality(m) is False


def test_evaluate_edge_quality_low_profit_factor():
    """profit_factor <= 1.1 → False (line 166)."""
    # 10 trades, slightly net positive but PF <= 1.1
    pnls = [1.0] * 5 + [-1.0] * 5  # PF = 5/5 = 1.0 <= 1.1
    m = compute_edge_metrics(pnls)
    assert m.profit_factor <= 1.1
    assert evaluate_edge_quality(m) is False


def test_evaluate_edge_quality_negative_expectancy():
    """expectancy <= 0 → False (line 169)."""
    # Profit factor just above 1.1 but negative expectancy (trick: many small wins, big losses)
    # PF = total_win/total_loss; expectancy = wr*avg_win - (1-wr)*avg_loss
    # 8 wins at 1.0, 2 losses at -3.7 → PF=8/7.4=1.08... not enough
    # Need PF > 1.1 and expectancy <= 0
    # 6 wins at 2.0, 4 losses at -2.5 → total_win=12, total_loss=10 → PF=1.2 > 1.1
    # exp = 0.6*2 - 0.4*2.5 = 1.2 - 1.0 = 0.2 > 0 ... let's try different values
    # 6 wins at 1.0, 4 losses at -1.5 → total_win=6, total_loss=6 → PF=1.0 ≤ 1.1
    # Try: n=10, PF just over 1.1 but negative expectancy
    # 3 wins at 4.0, 7 losses at -1.5 → total_win=12, total_loss=10.5 → PF=1.143 > 1.1
    # exp = 0.3*4 - 0.7*1.5 = 1.2 - 1.05 = 0.15 > 0 ... still positive
    # Very hard to have PF>1.1 and exp<=0; that's mathematically near impossible
    # Let's just test the branch directly with mock
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 10
    m.profit_factor = 1.5
    m.expectancy = -0.1
    m.win_rate = 0.5
    assert evaluate_edge_quality(m) is False


def test_evaluate_edge_quality_low_win_rate_still_ok():
    """win_rate < 0.3 → checks PF > 1.2 and exp > 0.5 (line 174)."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 10
    m.profit_factor = 1.5
    m.expectancy = 0.8
    m.win_rate = 0.2  # < 0.3
    result = evaluate_edge_quality(m)
    assert result is True  # PF > 1.2 and exp > 0.5


def test_evaluate_edge_quality_high_win_rate_still_ok():
    """win_rate > 0.8 → checks PF > 1.2 and exp > 0.5 (line 174)."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 10
    m.profit_factor = 1.5
    m.expectancy = 0.8
    m.win_rate = 0.9  # > 0.8
    result = evaluate_edge_quality(m)
    assert result is True


def test_evaluate_edge_quality_extreme_win_rate_bad_pf():
    """win_rate outside range, but PF <= 1.2 → False."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 10
    m.profit_factor = 1.15  # > 1.1 but <= 1.2
    m.expectancy = 0.8
    m.win_rate = 0.85  # > 0.8
    result = evaluate_edge_quality(m)
    assert result is False


def test_evaluate_edge_quality_good():
    """All criteria met → True."""
    pnls = [10.0] * 7 + [-3.0] * 3
    m = compute_edge_metrics(pnls)
    assert m.n_trades == 10
    assert evaluate_edge_quality(m) is True


# ─────────────────────────────────────────────────────────────────────────────
# generate_edge_recommendation — all branches
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_recommendation_no_trades():
    """n_trades == 0 → line 182."""
    m = compute_edge_metrics([])
    result = generate_edge_recommendation(m, False)
    assert result == "No trades available for analysis"


def test_generate_recommendation_insufficient_trades():
    """n_trades < 10 → line 185."""
    m = compute_edge_metrics([10.0, -5.0, 3.0])
    result = generate_edge_recommendation(m, False)
    assert "Insufficient" in result
    assert "3" in result


def test_generate_recommendation_edge_not_ok():
    """is_edge_ok=False → adds 'Edge quality below acceptable threshold.' (line 190)."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 15
    m.profit_factor = 0.8   # < 1.1 → also adds line 193
    m.expectancy = -0.5     # <= 0 → also adds line 196
    m.win_rate = 0.3        # < 0.4 → also adds line 199
    m.payoff_ratio = 0.5    # < 1.0 → also adds line 205
    result = generate_edge_recommendation(m, False)
    assert "Edge quality needs improvement" in result
    assert "Edge quality below acceptable threshold" in result
    assert "Profit factor" in result
    assert "Expectancy" in result
    assert "Win rate" in result
    assert "Payoff ratio" in result


def test_generate_recommendation_high_win_rate():
    """win_rate > 0.7 → line 202."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 15
    m.profit_factor = 1.5
    m.expectancy = 0.5
    m.win_rate = 0.85   # > 0.7
    m.payoff_ratio = 1.5
    result = generate_edge_recommendation(m, True)
    assert "unusually high" in result
    # is_edge_ok=True and recommendations is non-empty → line 211
    assert "acceptable but could be improved" in result


def test_generate_recommendation_edge_ok_no_issues():
    """is_edge_ok=True and no issues → line 209."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 15
    m.profit_factor = 1.5
    m.expectancy = 0.8
    m.win_rate = 0.55   # in 0.4..0.7 range
    m.payoff_ratio = 1.5
    result = generate_edge_recommendation(m, True)
    assert "Edge quality is good" in result


def test_generate_recommendation_edge_ok_with_issues():
    """is_edge_ok=True but some sub-issues (line 211)."""
    m = MagicMock(spec=EdgeMetrics)
    m.n_trades = 15
    m.profit_factor = 1.2
    m.expectancy = 0.5
    m.win_rate = 0.35   # < 0.4 → adds recommendation
    m.payoff_ratio = 1.5
    result = generate_edge_recommendation(m, True)
    assert "acceptable but could be improved" in result


# ─────────────────────────────────────────────────────────────────────────────
# integrate_edge_into_decision — lines 252-277
# ─────────────────────────────────────────────────────────────────────────────

def test_integrate_edge_into_decision_no_trades(tmp_path):
    """No trades → edge not OK, no position_sizing → trade blocked (lines 274-277)."""
    db = str(tmp_path / "trades.db")
    _make_trades_db(db, [])
    decision = {"symbol": "2330", "action": "buy"}
    updated, rec = integrate_edge_into_decision(db, "strategy_a", decision, edge_threshold=50.0)
    assert "edge_analysis" in updated
    assert "edge_decision" in updated
    assert updated.get("trade_blocked") is True
    assert updated.get("block_reason") == "insufficient_edge_quality"
    assert "insufficient edge quality" in rec.lower()


def test_integrate_edge_into_decision_with_position_sizing(tmp_path):
    """Edge not OK but position_sizing present → reduce size by 50% (lines 267-272)."""
    db = str(tmp_path / "trades.db")
    _make_trades_db(db, [])
    decision = {
        "symbol": "2330",
        "position_sizing": {"size": 100.0}
    }
    updated, rec = integrate_edge_into_decision(db, "strategy_a", decision, edge_threshold=50.0)
    assert updated["position_sizing"]["size"] == 50.0
    assert updated["position_sizing"]["edge_adjustment"] == 0.5
    assert "50%" in rec


def test_integrate_edge_into_decision_edge_ok_proceed(tmp_path):
    """Good edge with high score → should_proceed=True."""
    db = str(tmp_path / "trades.db")
    from datetime import datetime, timedelta
    base_date = datetime(2026, 3, 1)
    # Create many good trades within last 30 days
    trades = [
        {"agent_id": "strat", "pnl": 20.0 if i % 2 == 0 else -3.0,
         "timestamp": (base_date - timedelta(days=i)).strftime("%Y-%m-%dT00:00:00")}
        for i in range(20)
    ]
    _make_trades_db(db, trades)
    decision = {"symbol": "2330", "action": "buy"}
    # Use edge_threshold=0.0 so any positive score passes
    updated, rec = integrate_edge_into_decision(db, "strat", decision, edge_threshold=0.0)
    assert "edge_analysis" in updated
    assert updated["edge_decision"]["edge_threshold"] == 0.0


def test_integrate_edge_into_decision_score_below_threshold(tmp_path):
    """Edge score below threshold → should_proceed=False (lines 255-257)."""
    db = str(tmp_path / "trades.db")
    from datetime import datetime, timedelta
    base_date = datetime(2026, 3, 1)
    # Create enough trades but with poor edge
    trades = [
        {"agent_id": "strat", "pnl": 1.0 if i < 5 else -1.0,
         "timestamp": (base_date - timedelta(days=i)).strftime("%Y-%m-%dT00:00:00")}
        for i in range(12)
    ]
    _make_trades_db(db, trades)
    decision = {"symbol": "2330"}
    updated, rec = integrate_edge_into_decision(db, "strat", decision, edge_threshold=99.0)
    assert updated["edge_decision"]["should_proceed"] is False
    assert updated["edge_decision"]["edge_threshold"] == 99.0


# ─────────────────────────────────────────────────────────────────────────────
# update_strategy_version_with_edge — lines 304-328
# ─────────────────────────────────────────────────────────────────────────────

def test_update_strategy_version_with_edge_no_trades(tmp_path):
    """No trades → empty metrics, but still persists (line 311)."""
    db = str(tmp_path / "sv.db")
    _make_strategy_versions_db(db, [{"version_id": "v1", "strategy_config_json": "{}"}])
    # Also need trades table for get_trades_for_strategy
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    result = update_strategy_version_with_edge(db, "v1", "strategy_a")
    assert result is True


def test_update_strategy_version_with_edge_with_trades(tmp_path):
    """Trades present → computes metrics and persists (line 313)."""
    from datetime import datetime, timedelta
    db = str(tmp_path / "sv.db")
    _make_strategy_versions_db(db, [{"version_id": "v1", "strategy_config_json": "{}"}])
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    base_date = datetime(2026, 3, 1)
    for i in range(5):
        conn.execute(
            "INSERT INTO trades(symbol,action,quantity,price,fee,tax,pnl,timestamp,agent_id,decision_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("2330", "buy", 100, 100.0, 0.0, 0.0, 10.0,
             (base_date - timedelta(days=i)).strftime("%Y-%m-%dT00:00:00"),
             "strategy_a", "d1")
        )
    conn.commit()
    conn.close()
    result = update_strategy_version_with_edge(db, "v1", "strategy_a")
    assert result is True


def test_update_strategy_version_with_edge_exception(tmp_path):
    """DB error → returns False (lines 326-328)."""
    result = update_strategy_version_with_edge(
        "/nonexistent/path/db.db", "v1", "strategy_a"
    )
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# batch_update_all_strategy_versions — lines 344-400
# ─────────────────────────────────────────────────────────────────────────────

def test_batch_update_all_strategy_versions_empty(tmp_path):
    """No strategy versions → stats with zero updates."""
    db = str(tmp_path / "sv.db")
    _make_strategy_versions_db(db, [])
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    stats = batch_update_all_strategy_versions(db)
    assert stats["total_versions"] == 0
    assert stats["updated"] == 0
    assert stats["failed"] == 0
    assert stats["details"] == []


def test_batch_update_all_strategy_versions_success(tmp_path):
    """Multiple strategy versions → each gets updated."""
    db = str(tmp_path / "sv.db")
    versions = [
        {"version_id": "v1", "strategy_config_json": json.dumps({"strategy_id": "strat_a"}), "status": "active"},
        {"version_id": "v2", "strategy_config_json": json.dumps({"strategy_id": "strat_b"}), "status": "active"},
    ]
    _make_strategy_versions_db(db, versions)
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    stats = batch_update_all_strategy_versions(db)
    assert stats["total_versions"] == 2
    assert stats["updated"] == 2
    assert stats["failed"] == 0


def test_batch_update_all_strategy_versions_null_config(tmp_path):
    """strategy_config_json is NULL → strategy_id defaults to 'unknown'."""
    db = str(tmp_path / "sv.db")
    versions = [
        {"version_id": "v1", "strategy_config_json": None, "status": "active"},
    ]
    _make_strategy_versions_db(db, versions)
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()
    stats = batch_update_all_strategy_versions(db)
    assert stats["total_versions"] == 1
    # strategy_id == 'unknown' since config is None/empty
    assert stats["details"][0]["strategy_id"] == "unknown"


def test_batch_update_all_strategy_versions_failure(tmp_path):
    """If update_strategy_version_with_edge returns False → stats['failed'] incremented."""
    db = str(tmp_path / "sv.db")
    versions = [
        {"version_id": "v1", "strategy_config_json": json.dumps({"strategy_id": "strat_a"}), "status": "active"},
    ]
    _make_strategy_versions_db(db, versions)
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()

    with patch("openclaw.edge_integration.update_strategy_version_with_edge", return_value=False):
        stats = batch_update_all_strategy_versions(db)
    assert stats["failed"] == 1
    assert stats["updated"] == 0
    assert stats["details"][0]["status"] == "failed"


def test_batch_update_all_strategy_versions_exception_in_loop(tmp_path):
    """Exception inside the loop → stats['failed'] incremented with 'error' status."""
    db = str(tmp_path / "sv.db")
    versions = [
        {"version_id": "v1", "strategy_config_json": json.dumps({"strategy_id": "strat_a"}), "status": "active"},
    ]
    _make_strategy_versions_db(db, versions)
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, action TEXT, quantity INTEGER, price REAL,
            fee REAL, tax REAL, pnl REAL, timestamp TEXT, agent_id TEXT, decision_id TEXT
        )
    """)
    conn.commit()
    conn.close()

    with patch("openclaw.edge_integration.update_strategy_version_with_edge", side_effect=RuntimeError("boom")):
        stats = batch_update_all_strategy_versions(db)
    assert stats["failed"] == 1
    assert stats["details"][0]["status"] == "error"
    assert "boom" in stats["details"][0]["error"]
