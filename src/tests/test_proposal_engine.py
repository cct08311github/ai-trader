"""Tests for proposal_engine.py — covers the full state machine and helpers."""

import sqlite3
from datetime import datetime, timedelta, timezone

from openclaw.proposal_engine import (
    LEVEL3_FORBIDDEN_CATEGORIES,
    AuthorityLevel,
    ProposalStatus,
    StrategyProposal,
    _check_auto_approve_eligibility,
    apply_authority_decision,
    approve_proposal,
    create_proposal,
    expire_old_proposals,
    format_proposal_for_telegram,
    get_authority_level,
    get_pending_proposals,
    get_proposal_history,
    insert_strategy_proposal,
    reject_proposal,
)


# ---------------------------------------------------------------------------
# Helpers — two schema flavours
# ---------------------------------------------------------------------------

def _legacy_conn() -> sqlite3.Connection:
    """Legacy schema used by the original tests (expires_at TEXT)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE strategy_proposals(
          proposal_id TEXT PRIMARY KEY,
          generated_by TEXT NOT NULL,
          target_rule TEXT NOT NULL,
          rule_category TEXT NOT NULL,
          current_value TEXT NOT NULL,
          proposed_value TEXT NOT NULL,
          supporting_evidence TEXT NOT NULL,
          source_episodes_json TEXT NOT NULL,
          backtest_sharpe_before REAL,
          backtest_sharpe_after REAL,
          confidence REAL NOT NULL,
          semantic_memory_action TEXT NOT NULL,
          rollback_version TEXT NOT NULL,
          requires_human_approval INTEGER NOT NULL DEFAULT 1,
          auto_approve_eligible INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL
        );
        CREATE TABLE authority_policy(
          id INTEGER PRIMARY KEY CHECK (id = 1),
          level INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          note TEXT
        );
        INSERT INTO authority_policy(id, level, updated_at, note)
          VALUES (1, 2, datetime('now'), 'test');
        """
    )
    return conn


def _v4_conn() -> sqlite3.Connection:
    """v4 schema used by create_proposal / approve_proposal etc. (expires_at INTEGER)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE strategy_proposals(
          proposal_id TEXT PRIMARY KEY,
          generated_by TEXT,
          target_rule TEXT,
          rule_category TEXT,
          current_value TEXT,
          proposed_value TEXT,
          supporting_evidence TEXT,
          confidence REAL,
          requires_human_approval INTEGER DEFAULT 1,
          status TEXT DEFAULT 'pending',
          expires_at INTEGER,
          proposal_json TEXT DEFAULT '{}',
          created_at INTEGER,
          decided_at INTEGER,
          decided_by TEXT,
          decision_reason TEXT,
          source_episodes_json TEXT,
          backtest_sharpe_before REAL,
          backtest_sharpe_after REAL,
          semantic_memory_action TEXT,
          rollback_version TEXT,
          auto_approve_eligible INTEGER DEFAULT 0
        );
        """
    )
    return conn


def _make_legacy_proposal(conn, proposal_id="p1", rule_category="entry_threshold",
                           auto_approve_eligible=1, expires_at=None, status="pending"):
    """Insert a row directly into the legacy-schema table."""
    if expires_at is None:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO strategy_proposals
          (proposal_id, generated_by, target_rule, rule_category,
           current_value, proposed_value, supporting_evidence,
           source_episodes_json, confidence,
           semantic_memory_action, rollback_version,
           auto_approve_eligible, expires_at, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
        (proposal_id, "pm", "entry", rule_category,
         "2%", "2.5%", "x", "[]", 0.9,
         "UPDATE", "v1", auto_approve_eligible, expires_at, status),
    )
    conn.commit()


# ===========================================================================
# Tests preserved from original file
# ===========================================================================

def test_auto_approve_level2():
    conn = _legacy_conn()
    p = StrategyProposal(
        proposal_id="p1",
        generated_by="pm",
        target_rule="entry",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="x",
        confidence=0.9,
        backtest_sharpe_before=0.8,
        backtest_sharpe_after=1.0,
    )
    p.source_episodes = ["e"] * 20
    p.semantic_memory_action = "UPDATE"
    p.rollback_version = "v1"
    p.auto_approve_eligible = True
    insert_strategy_proposal(conn, p)
    res = apply_authority_decision(conn, "p1")
    assert res["allowed"] is True


def test_insert_strategy_proposal_minimal():
    """正向測試：插入最簡提案。"""
    conn = _legacy_conn()
    p = StrategyProposal(
        proposal_id="p2",
        generated_by="pm",
        target_rule="entry",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="x",
        confidence=0.9,
        backtest_sharpe_before=0.8,
        backtest_sharpe_after=1.0,
    )
    p.source_episodes = ["e"] * 5
    p.semantic_memory_action = "UPDATE"
    p.rollback_version = "v1"
    p.auto_approve_eligible = False
    insert_strategy_proposal(conn, p)
    count = conn.execute("SELECT COUNT(*) FROM strategy_proposals WHERE proposal_id='p2'").fetchone()[0]
    assert count == 1


def test_apply_authority_decision_nonexistent():
    """反向測試：不存在的提案應拋出異常。"""
    conn = _legacy_conn()
    try:
        apply_authority_decision(conn, "nonexistent")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "not found" in str(e).lower()


# ===========================================================================
# New tests — coverage for missing lines
# ===========================================================================

# ---------------------------------------------------------------------------
# create_proposal  (lines 94-133)
# ---------------------------------------------------------------------------

class TestCreateProposal:
    def test_basic_creation_returns_proposal(self):
        conn = _v4_conn()
        p = create_proposal(
            conn,
            generated_by="pm",
            target_rule="entry_signal",
            rule_category="entry_threshold",
            current_value="2%",
            proposed_value="2.5%",
            supporting_evidence="backtested",
            confidence=0.9,
            backtest_sharpe_before=0.8,
            backtest_sharpe_after=1.2,
        )
        assert p.proposal_id.startswith("prop_")
        assert p.target_rule == "entry_signal"
        assert p.status == "pending"
        # Verify DB row was inserted
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (p.proposal_id,)
        ).fetchone()
        assert row is not None
        assert row[0] == "pending"

    def test_proposal_json_is_populated(self):
        import json
        conn = _v4_conn()
        p = create_proposal(
            conn,
            generated_by="bot",
            target_rule="exit_rule",
            rule_category="exit_threshold",
            current_value="5%",
            proposed_value="4%",
            confidence=0.95,
            backtest_sharpe_before=1.0,
            backtest_sharpe_after=1.3,
        )
        data = json.loads(p.proposal_json)
        assert data["target_rule"] == "exit_rule"
        assert data["confidence"] == 0.95

    def test_expires_at_is_set(self):
        conn = _v4_conn()
        before = int(datetime.now(timezone.utc).timestamp() * 1000)
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        after = int((datetime.now(timezone.utc) + timedelta(days=8)).timestamp() * 1000)
        assert before < p.expires_at < after

    def test_custom_expires_days(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold", expires_days=1)
        expected_max = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)
        assert p.expires_at < expected_max

    def test_requires_human_approval_for_forbidden_category(self):
        conn = _v4_conn()
        p = create_proposal(
            conn, "pm", "r", "stop_loss_logic",
            confidence=0.99, auto_approve=True
        )
        assert p.requires_human_approval is True

    def test_auto_approve_eligible_category(self):
        conn = _v4_conn()
        p = create_proposal(
            conn, "pm", "r", "entry_threshold",
            confidence=0.95,
            backtest_sharpe_before=1.0,
            backtest_sharpe_after=1.5,
            auto_approve=True,
        )
        # Eligible category + confidence >= 0.85 + improvement → not requires_human
        assert p.requires_human_approval is False

    def test_none_confidence_no_sharpe(self):
        """No confidence and no sharpe data — should still insert without error."""
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        assert p.proposal_id.startswith("prop_")


# ---------------------------------------------------------------------------
# _check_auto_approve_eligibility  (lines 145, 149, 154)
# ---------------------------------------------------------------------------

class TestCheckAutoApproveEligibility:
    def test_forbidden_category_returns_false(self):
        for cat in LEVEL3_FORBIDDEN_CATEGORIES:
            assert _check_auto_approve_eligibility(cat, 0.99, 2.0, 1.0) is False

    def test_low_confidence_returns_false(self):
        assert _check_auto_approve_eligibility("entry_threshold", 0.7, 2.0, 1.0) is False

    def test_no_improvement_returns_false(self):
        # sharpe_after <= sharpe_before
        assert _check_auto_approve_eligibility("entry_threshold", 0.9, 1.0, 1.0) is False
        assert _check_auto_approve_eligibility("entry_threshold", 0.9, 0.9, 1.0) is False

    def test_eligible_returns_true(self):
        assert _check_auto_approve_eligibility("entry_threshold", 0.9, 1.5, 1.0) is True

    def test_none_confidence_not_penalised(self):
        # confidence is None — the check is skipped, should return True
        assert _check_auto_approve_eligibility("entry_threshold", None, 1.5, 1.0) is True

    def test_only_sharpe_after_provided(self):
        # backtest_sharpe_before is None → improvement check skipped
        assert _check_auto_approve_eligibility("entry_threshold", 0.9, 1.5, None) is True


# ---------------------------------------------------------------------------
# approve_proposal  (lines 214-238)
# ---------------------------------------------------------------------------

class TestApproveProposal:
    def test_approve_pending_proposal(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        result = approve_proposal(conn, p.proposal_id, "admin", "looks good")
        assert result["success"] is True
        assert result["status"] == "approved"

    def test_approve_nonexistent_proposal(self):
        conn = _v4_conn()
        result = approve_proposal(conn, "does_not_exist", "admin")
        assert result["success"] is False
        assert result["reason"] == "PROPOSAL_NOT_FOUND"

    def test_approve_already_approved_proposal(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        approve_proposal(conn, p.proposal_id, "admin")
        # Second approval should fail with INVALID_STATUS
        result = approve_proposal(conn, p.proposal_id, "admin")
        assert result["success"] is False
        assert "INVALID_STATUS" in result["reason"]

    def test_approve_expired_proposal(self):
        """Proposal with expires_at in the past triggers auto-expire path."""
        conn = _v4_conn()
        past_ts = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)
        conn.execute(
            """
            INSERT INTO strategy_proposals
              (proposal_id, generated_by, target_rule, rule_category,
               status, expires_at, created_at, proposal_json)
            VALUES ('exp1','pm','r','entry_threshold','pending',?,?,'{}')
            """,
            (past_ts, int(datetime.now(timezone.utc).timestamp() * 1000)),
        )
        conn.commit()
        result = approve_proposal(conn, "exp1", "admin")
        assert result["success"] is False
        assert result["reason"] == "PROPOSAL_EXPIRED"

    def test_approve_default_reason(self):
        """decision_reason defaults to 'Approved' when None is passed."""
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        result = approve_proposal(conn, p.proposal_id, "admin", None)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# reject_proposal  (lines 248-266)
# ---------------------------------------------------------------------------

class TestRejectProposal:
    def test_reject_pending_proposal(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        result = reject_proposal(conn, p.proposal_id, "admin", "too risky")
        assert result["success"] is True
        assert result["status"] == "rejected"

    def test_reject_nonexistent_proposal(self):
        conn = _v4_conn()
        result = reject_proposal(conn, "ghost", "admin", "no reason")
        assert result["success"] is False
        assert result["reason"] == "PROPOSAL_NOT_FOUND"

    def test_reject_already_rejected_proposal(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        reject_proposal(conn, p.proposal_id, "admin", "r1")
        result = reject_proposal(conn, p.proposal_id, "admin", "r2")
        assert result["success"] is False
        assert "INVALID_STATUS" in result["reason"]


# ---------------------------------------------------------------------------
# _expire_proposal / expire_old_proposals  (lines 271-280, 285-295)
# ---------------------------------------------------------------------------

class TestExpireProposals:
    def test_expire_old_proposals_returns_count(self):
        conn = _v4_conn()
        # Two proposals with expires_at in the past
        past_ts = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp() * 1000)
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        for pid in ("ep1", "ep2"):
            conn.execute(
                """
                INSERT INTO strategy_proposals
                  (proposal_id, generated_by, target_rule, rule_category,
                   status, expires_at, created_at, proposal_json)
                VALUES (?,?,?,?,?,?,?,'{}')
                """,
                (pid, "pm", "r", "entry_threshold", "pending", past_ts, now_ts),
            )
        conn.commit()
        count = expire_old_proposals(conn)
        assert count == 2

    def test_expire_old_proposals_skips_future(self):
        conn = _v4_conn()
        future_ts = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000)
        now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        conn.execute(
            """
            INSERT INTO strategy_proposals
              (proposal_id, generated_by, target_rule, rule_category,
               status, expires_at, created_at, proposal_json)
            VALUES ('fp1','pm','r','entry_threshold','pending',?,?,'{}')
            """,
            (future_ts, now_ts),
        )
        conn.commit()
        count = expire_old_proposals(conn)
        assert count == 0


# ---------------------------------------------------------------------------
# _get_proposal / get_pending_proposals  (lines 300-310, 315-324)
# ---------------------------------------------------------------------------

class TestGetProposals:
    def test_get_pending_proposals_empty(self):
        conn = _v4_conn()
        result = get_pending_proposals(conn)
        assert result == []

    def test_get_pending_proposals_returns_rows(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        rows = get_pending_proposals(conn)
        assert len(rows) == 1
        assert rows[0]["proposal_id"] == p.proposal_id
        assert rows[0]["status"] == "pending"

    def test_get_pending_proposals_excludes_approved(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        approve_proposal(conn, p.proposal_id, "admin")
        rows = get_pending_proposals(conn)
        assert rows == []


# ---------------------------------------------------------------------------
# get_proposal_history  (lines 332-343)
# ---------------------------------------------------------------------------

class TestGetProposalHistory:
    def test_history_empty(self):
        conn = _v4_conn()
        result = get_proposal_history(conn)
        assert result == []

    def test_history_includes_approved(self):
        conn = _v4_conn()
        p = create_proposal(conn, "pm", "r", "entry_threshold")
        approve_proposal(conn, p.proposal_id, "admin")
        history = get_proposal_history(conn)
        assert len(history) == 1
        assert history[0]["status"] == "approved"

    def test_history_excludes_pending(self):
        conn = _v4_conn()
        create_proposal(conn, "pm", "r", "entry_threshold")
        history = get_proposal_history(conn)
        assert history == []

    def test_history_limit(self):
        conn = _v4_conn()
        for i in range(5):
            p = create_proposal(conn, "pm", f"r{i}", "entry_threshold")
            approve_proposal(conn, p.proposal_id, "admin")
        history = get_proposal_history(conn, limit=3)
        assert len(history) == 3


# ---------------------------------------------------------------------------
# format_proposal_for_telegram  (lines 402-429)
# ---------------------------------------------------------------------------

class TestFormatProposalForTelegram:
    def test_pending_proposal_format(self):
        proposal = {
            "proposal_id": "prop_abc123",
            "target_rule": "entry_signal",
            "rule_category": "entry_threshold",
            "current_value": "2%",
            "proposed_value": "2.5%",
            "confidence": 0.9,
            "status": "pending",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        text = format_proposal_for_telegram(proposal)
        assert "prop_abc123" in text
        assert "entry_signal" in text
        assert "PENDING" in text
        assert "⏳" in text

    def test_approved_proposal_format(self):
        proposal = {
            "proposal_id": "prop_xyz",
            "target_rule": "exit_rule",
            "rule_category": "exit_threshold",
            "current_value": "5%",
            "proposed_value": "4%",
            "confidence": 0.95,
            "status": "approved",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        text = format_proposal_for_telegram(proposal)
        assert "✅" in text
        assert "APPROVED" in text

    def test_rejected_proposal_format(self):
        proposal = {
            "proposal_id": "prop_rej",
            "target_rule": "r",
            "rule_category": "c",
            "status": "rejected",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        text = format_proposal_for_telegram(proposal)
        assert "❌" in text

    def test_expired_proposal_format(self):
        proposal = {
            "proposal_id": "prop_exp",
            "target_rule": "r",
            "rule_category": "c",
            "status": "expired",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        text = format_proposal_for_telegram(proposal)
        assert "⏰" in text

    def test_unknown_status_format(self):
        proposal = {
            "proposal_id": "prop_unk",
            "target_rule": "r",
            "rule_category": "c",
            "status": "unknown_status",
            "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
        }
        text = format_proposal_for_telegram(proposal)
        assert "❓" in text

    def test_missing_fields_use_na(self):
        text = format_proposal_for_telegram({})
        assert "N/A" in text


# ---------------------------------------------------------------------------
# __main__ block  (lines 433-434)
# ---------------------------------------------------------------------------

def test_main_block_runs():
    """Execute the module-level __main__ block via runpy."""
    import runpy
    # Should not raise; output goes to stdout
    runpy.run_module("openclaw.proposal_engine", run_name="__main__", alter_sys=False)


# ---------------------------------------------------------------------------
# apply_authority_decision extra branches (lines 454, 456, 458-459, 463)
# ---------------------------------------------------------------------------

class TestApplyAuthorityDecisionExtra:
    def test_non_pending_status_blocked(self):
        """Proposal already approved → AUTH_NOT_PENDING."""
        conn = _legacy_conn()
        _make_legacy_proposal(conn, proposal_id="a1", auto_approve_eligible=1, status="approved")
        res = apply_authority_decision(conn, "a1")
        assert res["allowed"] is False
        assert res["reason_code"] == "AUTH_NOT_PENDING"

    def test_level3_forbidden_category_blocked(self):
        """stop_loss_logic is forbidden even for eligible proposals."""
        conn = _legacy_conn()
        _make_legacy_proposal(conn, proposal_id="b1",
                               rule_category="stop_loss_logic",
                               auto_approve_eligible=1)
        res = apply_authority_decision(conn, "b1")
        assert res["allowed"] is False
        assert res["reason_code"] == "AUTH_LEVEL3_FORBIDDEN"

    def test_expired_proposal_blocked(self):
        """expires_at in the past → AUTH_PROPOSAL_EXPIRED."""
        conn = _legacy_conn()
        past_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        _make_legacy_proposal(conn, proposal_id="c1",
                               auto_approve_eligible=1,
                               expires_at=past_date)
        res = apply_authority_decision(conn, "c1")
        assert res["allowed"] is False
        assert res["reason_code"] == "AUTH_PROPOSAL_EXPIRED"
        # Verify status was updated to expired in DB
        status = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='c1'"
        ).fetchone()[0]
        assert status == "expired"

    def test_not_auto_approve_eligible_blocked(self):
        """auto_approve_eligible=0 with level 2 → AUTH_MANUAL_REQUIRED."""
        conn = _legacy_conn()
        _make_legacy_proposal(conn, proposal_id="d1", auto_approve_eligible=0)
        res = apply_authority_decision(conn, "d1")
        assert res["allowed"] is False
        assert res["reason_code"] == "AUTH_MANUAL_REQUIRED"


# ---------------------------------------------------------------------------
# get_authority_level  (backward-compat, always returns 2)
# ---------------------------------------------------------------------------

def test_get_authority_level():
    conn = _v4_conn()
    assert get_authority_level(conn) == 2


# ---------------------------------------------------------------------------
# ProposalStatus / AuthorityLevel enums
# ---------------------------------------------------------------------------

def test_proposal_status_values():
    assert ProposalStatus.PENDING.value == "pending"
    assert ProposalStatus.APPROVED.value == "approved"
    assert ProposalStatus.REJECTED.value == "rejected"
    assert ProposalStatus.EXPIRED.value == "expired"
    assert ProposalStatus.AUTO_APPROVED.value == "auto_approved"


def test_authority_level_values():
    assert AuthorityLevel.LEVEL_0.value == 0
    assert AuthorityLevel.LEVEL_3.value == 3
