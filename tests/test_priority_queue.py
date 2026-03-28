"""Tests for Phase 3 — LLM priority queue + dynamic daily limit.

Closes #480
"""
import json
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
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at INTEGER,
            proposal_json TEXT NOT NULL DEFAULT '{}',
            created_at INTEGER NOT NULL,
            decided_at INTEGER,
            decided_by TEXT,
            decision_reason TEXT,
            backtest_sharpe_before REAL,
            backtest_sharpe_after REAL,
            auto_approve_eligible INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            ts TEXT,
            severity TEXT,
            source TEXT,
            code TEXT,
            detail_json TEXT,
            resolved INTEGER DEFAULT 0
        )
    """)
    yield c
    c.close()


def _insert_proposal(conn, proposal_id, target_rule, confidence):
    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            status, proposal_json, created_at, confidence)
           VALUES (?, 'agent', ?, 'test', 'pending', ?, ?, ?)""",
        (
            proposal_id,
            target_rule,
            json.dumps({"direction": "buy", "confidence": confidence}),
            int(time.time() * 1000),
            confidence,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# _sort_key
# ---------------------------------------------------------------------------

class TestSortKey:
    def test_position_rebalance_before_strategy_direction(self):
        from openclaw.proposal_reviewer import _sort_key
        pr_row = ("id1", "agent", "POSITION_REBALANCE", "ev", json.dumps({"confidence": 0.7}))
        sd_row = ("id2", "agent", "STRATEGY_DIRECTION", "ev", json.dumps({"confidence": 0.9}))
        assert _sort_key(pr_row) < _sort_key(sd_row)

    def test_higher_confidence_sorts_first_within_same_rule(self):
        from openclaw.proposal_reviewer import _sort_key
        hi = ("id1", "a", "STRATEGY_DIRECTION", "e", json.dumps({"confidence": 0.9}))
        lo = ("id2", "a", "STRATEGY_DIRECTION", "e", json.dumps({"confidence": 0.6}))
        assert _sort_key(hi) < _sort_key(lo)

    def test_unknown_rule_sorts_last(self):
        from openclaw.proposal_reviewer import _sort_key
        sd_row = ("id1", "a", "STRATEGY_DIRECTION", "e", json.dumps({}))
        uk_row = ("id2", "a", "UNKNOWN_RULE", "e", json.dumps({}))
        assert _sort_key(sd_row) < _sort_key(uk_row)

    def test_missing_confidence_treated_as_zero(self):
        from openclaw.proposal_reviewer import _sort_key
        row = ("id1", "a", "STRATEGY_DIRECTION", "e", "{}")
        # Should not raise; confidence defaults to 0
        key = _sort_key(row)
        assert key == (1, 0.0)

    def test_malformed_json_treated_as_zero_confidence(self):
        from openclaw.proposal_reviewer import _sort_key
        row = ("id1", "a", "STRATEGY_DIRECTION", "e", "not-json")
        key = _sort_key(row)
        assert key == (1, 0.0)


# ---------------------------------------------------------------------------
# _effective_daily_limit
# ---------------------------------------------------------------------------

class TestEffectiveDailyLimit:
    def test_normal_pending_returns_base_limit(self):
        from openclaw.proposal_reviewer import _effective_daily_limit, _LLM_DAILY_LIMIT
        assert _effective_daily_limit(20) == _LLM_DAILY_LIMIT

    def test_high_pending_returns_multiplied_limit(self):
        from openclaw.proposal_reviewer import (
            _effective_daily_limit, _LLM_DAILY_LIMIT, _DYNAMIC_LIMIT_MULTIPLIER,
        )
        result = _effective_daily_limit(21)
        assert result == int(_LLM_DAILY_LIMIT * _DYNAMIC_LIMIT_MULTIPLIER)

    def test_zero_pending_returns_base_limit(self):
        from openclaw.proposal_reviewer import _effective_daily_limit, _LLM_DAILY_LIMIT
        assert _effective_daily_limit(0) == _LLM_DAILY_LIMIT


# ---------------------------------------------------------------------------
# auto_review_pending_proposals: priority ordering
# ---------------------------------------------------------------------------

class TestPriorityOrdering:
    def _mock_minimax(self, decision="approve", confidence=0.75, reason="ok"):
        return {"decision": decision, "confidence": confidence, "reason": reason}

    def test_position_rebalance_reviewed_before_strategy_direction(self, conn):
        """POSITION_REBALANCE must be reviewed before STRATEGY_DIRECTION even if
        STRATEGY_DIRECTION was inserted first."""
        _insert_proposal(conn, "sd_first", "STRATEGY_DIRECTION", 0.80)
        # Insert POSITION_REBALANCE after (lower created_at order would be last)
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                status, proposal_json, created_at, confidence)
               VALUES ('pr_second', 'agent', 'POSITION_REBALANCE', 'test',
                       'pending', ?, ?, 0.75)""",
            (
                json.dumps({
                    "symbol": "2330", "reduce_pct": 0.10, "current_weight": 0.25,
                    "confidence": 0.75,
                }),
                int(time.time() * 1000) + 1000,
            ),
        )
        conn.commit()

        call_order = []

        def mock_gemini(conn, symbol, weight, reduce_pct, evidence, position_summary):
            call_order.append("POSITION_REBALANCE")
            return self._mock_minimax()

        def mock_sd(direction, proposed_value, evidence, position_summary):
            call_order.append("STRATEGY_DIRECTION")
            return self._mock_minimax()

        with patch("openclaw.proposal_reviewer._gemini_review", side_effect=mock_gemini), \
             patch("openclaw.proposal_reviewer._strategy_direction_review", side_effect=mock_sd), \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(conn)

        assert reviewed == 2
        assert call_order == ["POSITION_REBALANCE", "STRATEGY_DIRECTION"]

    def test_high_confidence_reviewed_within_same_rule(self, conn):
        """Within STRATEGY_DIRECTION, both proposals should be reviewed.
        Sort order correctness is covered by TestSortKey unit tests."""
        _insert_proposal(conn, "lo_conf", "STRATEGY_DIRECTION", 0.60)
        _insert_proposal(conn, "hi_conf", "STRATEGY_DIRECTION", 0.90)

        with patch("openclaw.proposal_reviewer._strategy_direction_review",
                   return_value=self._mock_minimax()), \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(conn)

        assert reviewed == 2
        for pid in ("lo_conf", "hi_conf"):
            row = conn.execute(
                "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
            ).fetchone()
            assert row[0] == "approved"
