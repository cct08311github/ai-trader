"""Tests for Phase 2 — enriched reviewer prompt + proposal_outcomes T+5/T+20.

Closes #480
"""
import sqlite3
import time
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE lm_signal_cache (
            cache_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            score REAL,
            direction TEXT,
            reasoning TEXT,
            expires_at INTEGER,
            created_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER) * 1000)
        )
    """)
    c.execute("""
        CREATE TABLE eod_prices (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            close REAL,
            volume REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    c.execute("""
        CREATE TABLE eod_institution_flows (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            foreign_net REAL DEFAULT 0,
            sitc_net REAL DEFAULT 0,
            dealer_net REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    c.execute("""
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            symbol TEXT,
            decision_type TEXT,
            result_pnl REAL,
            created_at INTEGER DEFAULT (CAST(strftime('%s','now') AS INTEGER) * 1000)
        )
    """)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# _build_review_context
# ---------------------------------------------------------------------------

class TestBuildReviewContext:
    def test_returns_defaults_when_no_data(self, conn):
        from openclaw.proposal_reviewer import _build_review_context
        ctx = _build_review_context(conn, "9999")
        assert ctx["signal_score"] == "N/A"
        assert ctx["institution_net_3d"] == 0
        assert "無" in ctx["recent_decisions_summary"]

    def test_picks_up_signal_cache(self, conn):
        from openclaw.proposal_reviewer import _build_review_context
        future_ms = int(time.time() * 1000) + 3_600_000
        conn.execute(
            """INSERT INTO lm_signal_cache
               (cache_id, symbol, score, direction, expires_at)
               VALUES ('c1', '2330', 7.5, 'bearish', ?)""",
            (future_ms,),
        )
        conn.commit()
        ctx = _build_review_context(conn, "2330")
        assert ctx["signal_score"] == "7.5/10"
        assert ctx["signal_direction"] == "bearish"

    def test_picks_up_eod_prices(self, conn):
        from openclaw.proposal_reviewer import _build_review_context
        from datetime import date, timedelta
        today = date.today()
        for i in range(5):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO eod_prices (symbol, trade_date, close) VALUES (?, ?, ?)",
                ("2330", d, 500.0 - i * 10),
            )
        conn.commit()
        ctx = _build_review_context(conn, "2330")
        assert ctx["latest_close"] == "500.0"
        assert "%" in ctx["price_5d_change"]

    def test_picks_up_institution_flows(self, conn):
        from openclaw.proposal_reviewer import _build_review_context
        conn.execute(
            """INSERT INTO eod_institution_flows
               (symbol, trade_date, foreign_net, sitc_net, dealer_net)
               VALUES ('2330', date('now'), 500, 100, -50)""",
        )
        conn.commit()
        ctx = _build_review_context(conn, "2330")
        assert ctx["institution_net_3d"] == 550

    def test_picks_up_recent_decisions(self, conn):
        from openclaw.proposal_reviewer import _build_review_context
        conn.execute(
            "INSERT INTO decisions (decision_id, symbol, decision_type, result_pnl) "
            "VALUES ('d1', '2330', 'sell', 0.03)"
        )
        conn.commit()
        ctx = _build_review_context(conn, "2330")
        assert "sell" in ctx["recent_decisions_summary"]
        assert "3.0%" in ctx["recent_decisions_summary"]


# ---------------------------------------------------------------------------
# proposal_outcomes table creation
# ---------------------------------------------------------------------------

class TestProposalOutcomesTable:
    def test_ensure_creates_table(self, conn):
        from openclaw.proposal_engine import ensure_proposal_outcomes_table
        ensure_proposal_outcomes_table(conn)
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(proposal_outcomes)"
        ).fetchall()}
        assert "price_t5" in cols
        assert "price_t20" in cols
        assert "pnl_t5" in cols
        assert "pnl_t20" in cols
        assert "outcome_t5" in cols
        assert "outcome_t20" in cols

    def test_idempotent(self, conn):
        from openclaw.proposal_engine import ensure_proposal_outcomes_table
        ensure_proposal_outcomes_table(conn)
        ensure_proposal_outcomes_table(conn)  # should not raise


# ---------------------------------------------------------------------------
# confidence_calibration_report
# ---------------------------------------------------------------------------

class TestConfidenceCalibrationReport:
    def _seed(self, conn, rows):
        from openclaw.proposal_engine import ensure_proposal_outcomes_table
        ensure_proposal_outcomes_table(conn)
        for proposal_id, symbol, direction, conf, pnl_t5, pnl_t20 in rows:
            outcome_t5 = "profitable" if pnl_t5 > 0 else "loss"
            outcome_t20 = "profitable" if pnl_t20 > 0 else "loss" if pnl_t20 < 0 else "neutral"
            conn.execute(
                """INSERT INTO proposal_outcomes
                   (proposal_id, symbol, direction, confidence,
                    price_t5, pnl_t5, outcome_t5,
                    price_t20, pnl_t20, outcome_t20,
                    evaluated_at)
                   VALUES (?, ?, ?, ?, 100, ?, ?, 100, ?, ?, 0)""",
                (proposal_id, symbol, direction, conf, pnl_t5, outcome_t5, pnl_t20, outcome_t20),
            )
        conn.commit()

    def test_returns_empty_when_no_data(self, conn):
        from openclaw.proposal_engine import confidence_calibration_report, ensure_proposal_outcomes_table
        ensure_proposal_outcomes_table(conn)
        assert confidence_calibration_report(conn) == []

    def test_groups_by_bucket_and_direction(self, conn):
        from openclaw.proposal_engine import confidence_calibration_report
        self._seed(conn, [
            ("p1", "2330", "sell", 0.72, 0.02, 0.03),
            ("p2", "2330", "sell", 0.75, -0.01, 0.01),
            ("p3", "1303", "buy", 0.68, 0.01, -0.01),
        ])
        rows = confidence_calibration_report(conn)
        buckets = {(r[0], r[1]) for r in rows}
        assert ("0.70-0.84", "sell") in buckets
        assert ("0.65-0.69", "buy") in buckets
