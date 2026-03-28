"""Tests for Phase 1 — eligibility threshold lowering + reviewer expansion.

Closes #480
"""
import sqlite3
import pytest
from unittest.mock import patch, MagicMock


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


# ---------------------------------------------------------------------------
# proposal_engine: eligibility threshold 0.85 → 0.60
# ---------------------------------------------------------------------------

class TestAutoApproveEligibility:
    def _fn(self, rule_category, confidence, sharpe_after=None, sharpe_before=None):
        from openclaw.proposal_engine import _check_auto_approve_eligibility
        return _check_auto_approve_eligibility(
            rule_category, confidence, sharpe_after, sharpe_before
        )

    def test_conf_0_60_eligible(self):
        """0.60 should now be eligible (previously required 0.85)."""
        assert self._fn("entry_parameters", 0.60) is True

    def test_conf_0_59_not_eligible(self):
        assert self._fn("entry_parameters", 0.59) is False

    def test_conf_0_85_still_eligible(self):
        assert self._fn("entry_parameters", 0.85) is True

    def test_conf_none_eligible(self):
        """None confidence skips check → eligible."""
        assert self._fn("entry_parameters", None) is True

    def test_level3_blocked_regardless_of_confidence(self):
        for cat in ("stop_loss_logic", "position_sizing", "symbol_universe",
                    "live_mode_switch", "monthly_drawdown_limit", "risk_parameters"):
            assert self._fn(cat, 0.90) is False

    def test_sharpe_improvement_required(self):
        assert self._fn("entry_parameters", 0.80, sharpe_after=1.0, sharpe_before=1.5) is False

    def test_sharpe_improvement_eligible(self):
        assert self._fn("entry_parameters", 0.80, sharpe_after=1.6, sharpe_before=1.5) is True

    def test_env_override_threshold(self):
        """AUTO_APPROVE_CONFIDENCE env var controls the threshold."""
        with patch.dict("os.environ", {"AUTO_APPROVE_CONFIDENCE": "0.75"}):
            # Need to re-import to pick up the new env value
            import importlib
            import openclaw.proposal_engine as pe
            old_val = pe._ELIGIBILITY_CONFIDENCE
            pe._ELIGIBILITY_CONFIDENCE = 0.75
            try:
                assert self._fn("entry_parameters", 0.74) is False
                assert self._fn("entry_parameters", 0.75) is True
            finally:
                pe._ELIGIBILITY_CONFIDENCE = old_val


# ---------------------------------------------------------------------------
# proposal_reviewer: STRATEGY_DIRECTION now reviewable
# ---------------------------------------------------------------------------

class TestReviewableRules:
    def test_position_rebalance_reviewable(self):
        from openclaw.proposal_reviewer import _REVIEWABLE_RULES
        assert "POSITION_REBALANCE" in _REVIEWABLE_RULES

    def test_strategy_direction_reviewable(self):
        from openclaw.proposal_reviewer import _REVIEWABLE_RULES
        assert "STRATEGY_DIRECTION" in _REVIEWABLE_RULES

    def test_other_rules_not_reviewable(self):
        from openclaw.proposal_reviewer import _REVIEWABLE_RULES
        assert "RISK_CONTROL" not in _REVIEWABLE_RULES
        assert "ENTRY_CONDITION" not in _REVIEWABLE_RULES


class TestStrategyDirectionReview:
    def _mock_minimax(self, decision="approve", confidence=0.75, reason="ok"):
        return {"decision": decision, "confidence": confidence, "reason": reason}

    def test_strategy_direction_gets_reviewed(self, conn):
        """STRATEGY_DIRECTION proposals should be reviewed, not skipped."""
        import json, time
        proposal_json = json.dumps({
            "direction": "defensive",
            "proposed_value": "減少多頭敞口",
            "committee_context": {"arbiter": {"direction": "defensive"}},
        })
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json, created_at)
               VALUES (?, 'strategy_committee', 'STRATEGY_DIRECTION', 'strategy',
                       '減少多頭敞口', '市場下行風險', 0.70, 1, 'pending', ?, ?)""",
            ("prop_sd_001", proposal_json, int(time.time() * 1000)),
        )
        conn.commit()

        with patch("openclaw.proposal_reviewer._strategy_direction_review",
                   return_value=self._mock_minimax("approve", 0.75, "市場環境支持")) as mock_review, \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(conn)

        assert reviewed == 1
        mock_review.assert_called_once()
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='prop_sd_001'"
        ).fetchone()
        assert row[0] == "approved"

    def test_non_reviewable_rule_skipped(self, conn):
        """Non-reviewable rules should be skipped without LLM call."""
        import json, time
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json, created_at)
               VALUES ('prop_rc_001', 'agent', 'RISK_CONTROL', 'risk',
                       'value', 'evidence', 0.80, 1, 'pending', '{}', ?)""",
            (int(time.time() * 1000),),
        )
        conn.commit()

        with patch("openclaw.proposal_reviewer._gemini_review") as mock_gr, \
             patch("openclaw.proposal_reviewer._strategy_direction_review") as mock_sd, \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(conn)

        assert reviewed == 0
        mock_gr.assert_not_called()
        mock_sd.assert_not_called()

    def test_strategy_direction_rejected(self, conn):
        """STRATEGY_DIRECTION can be rejected by LLM."""
        import json, time
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json, created_at)
               VALUES ('prop_sd_002', 'strategy_committee', 'STRATEGY_DIRECTION', 'strategy',
                       '加碼', '技術信號看多', 0.65, 1, 'pending', '{}', ?)""",
            (int(time.time() * 1000),),
        )
        conn.commit()

        with patch("openclaw.proposal_reviewer._strategy_direction_review",
                   return_value=self._mock_minimax("reject", 0.55, "風險過高")) as _, \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(conn)

        assert reviewed == 1
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='prop_sd_002'"
        ).fetchone()
        assert row[0] == "rejected"
