"""Tests for DecisionRepository."""
from __future__ import annotations

import sqlite3

import pytest

from openclaw.repositories.decision_repository import DecisionRepository


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            ts TEXT,
            created_at INTEGER,
            symbol TEXT,
            strategy_id TEXT,
            strategy_version TEXT,
            signal_side TEXT,
            signal_score REAL,
            signal_ttl_ms INTEGER,
            llm_ref TEXT,
            reason_json TEXT,
            signal_source TEXT,
            direction TEXT,
            quantity INTEGER,
            entry_price REAL,
            stop_loss REAL,
            take_profit REAL,
            sentinel_blocked INTEGER,
            pm_veto INTEGER,
            budget_status TEXT,
            sentinel_reason_code TEXT,
            drawdown_risk_mode TEXT,
            drawdown_reason_code TEXT
        );
        CREATE TABLE risk_checks (
            check_id TEXT PRIMARY KEY,
            decision_id TEXT,
            ts TEXT,
            passed INTEGER,
            reject_code TEXT,
            metrics_json TEXT
        );
    """)
    return c


@pytest.fixture()
def repo(conn):
    return DecisionRepository(conn)


class TestInsertDecision:
    def test_inserts_watcher_decision(self, conn, repo):
        repo.insert_decision(
            decision_id="d1", symbol="2330", signal_side="buy",
        )
        row = conn.execute("SELECT * FROM decisions WHERE decision_id='d1'").fetchone()
        assert row["symbol"] == "2330"
        assert row["signal_side"] == "buy"

    def test_ignores_duplicate(self, conn, repo):
        repo.insert_decision(decision_id="d1", symbol="2330", signal_side="buy")
        repo.insert_decision(decision_id="d1", symbol="2330", signal_side="sell")
        row = conn.execute("SELECT signal_side FROM decisions WHERE decision_id='d1'").fetchone()
        assert row["signal_side"] == "buy"  # first insert wins


class TestInsertRiskCheck:
    def test_inserts_risk_check(self, conn, repo):
        repo.insert_risk_check(
            decision_id="d1", passed=True, metrics={"nav": 1000000},
        )
        row = conn.execute("SELECT * FROM risk_checks").fetchone()
        assert row["decision_id"] == "d1"
        assert row["passed"] == 1

    def test_inserts_rejected_check(self, conn, repo):
        repo.insert_risk_check(
            decision_id="d1", passed=False, reject_code="RISK_NAV_LOW",
        )
        row = conn.execute("SELECT * FROM risk_checks").fetchone()
        assert row["passed"] == 0
        assert row["reject_code"] == "RISK_NAV_LOW"
