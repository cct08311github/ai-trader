"""Tests for LLM cost guard in proposal_reviewer.py (Issue #291).

Covers:
- _count_reviews_today: counts only today's approved/rejected proposals
- _record_cost_guard_incident: writes to incidents table
- auto_review_pending_proposals: stops at daily limit, sends Telegram notification
"""
from __future__ import annotations

import json
import sqlite3
import time
import datetime
import zoneinfo

import pytest

from openclaw import proposal_reviewer


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def _make_db(proposals: list[dict] | None = None) -> sqlite3.Connection:
    """Build an in-memory SQLite with the minimal schema required."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE strategy_proposals (
            proposal_id     TEXT PRIMARY KEY,
            generated_by    TEXT,
            target_rule     TEXT,
            supporting_evidence TEXT,
            proposal_json   TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      INTEGER,
            decided_at      INTEGER,
            expires_at      INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            ts          TEXT,
            severity    TEXT,
            source      TEXT,
            code        TEXT,
            detail_json TEXT,
            resolved    INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            avg_price REAL,
            current_price REAL,
            unrealized_pnl REAL
        )"""
    )
    conn.commit()

    if proposals:
        for p in proposals:
            conn.execute(
                """INSERT INTO strategy_proposals
                   (proposal_id, generated_by, target_rule, supporting_evidence,
                    proposal_json, status, created_at, decided_at, expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    p["proposal_id"],
                    p.get("generated_by", "test"),
                    p.get("target_rule", "TEST_RULE"),
                    p.get("supporting_evidence", ""),
                    p.get("proposal_json", json.dumps({"symbol": "2330", "reduce_pct": 0.1, "current_weight": 0.6})),
                    p.get("status", "pending"),
                    p.get("created_at", int(time.time() * 1000)),
                    p.get("decided_at"),
                    p.get("expires_at"),
                ),
            )
        conn.commit()

    return conn


def _today_ms() -> int:
    """今日 Asia/Taipei 00:00 的 epoch ms（用於模擬今日決定的 decided_at）。"""
    tz = zoneinfo.ZoneInfo("Asia/Taipei")
    today_start = datetime.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(today_start.timestamp() * 1000) + 60_000  # +1 min 確保 >= today_start


def _yesterday_ms() -> int:
    tz = zoneinfo.ZoneInfo("Asia/Taipei")
    yesterday = datetime.datetime.now(tz) - datetime.timedelta(days=1)
    yesterday_start = yesterday.replace(hour=12, minute=0, second=0, microsecond=0)
    return int(yesterday_start.timestamp() * 1000)


# ──────────────────────────────────────────────
# _count_reviews_today
# ──────────────────────────────────────────────

class TestCountReviewsToday:
    def test_no_proposals_returns_zero(self):
        conn = _make_db()
        assert proposal_reviewer._count_reviews_today(conn) == 0

    def test_counts_only_approved_and_rejected(self):
        proposals = [
            {"proposal_id": "p1", "status": "approved", "decided_at": _today_ms()},
            {"proposal_id": "p2", "status": "rejected", "decided_at": _today_ms()},
            {"proposal_id": "p3", "status": "pending",  "decided_at": None},
        ]
        conn = _make_db(proposals)
        assert proposal_reviewer._count_reviews_today(conn) == 2

    def test_excludes_yesterday_decisions(self):
        proposals = [
            {"proposal_id": "p1", "status": "approved", "decided_at": _today_ms()},
            {"proposal_id": "p2", "status": "approved", "decided_at": _yesterday_ms()},
        ]
        conn = _make_db(proposals)
        assert proposal_reviewer._count_reviews_today(conn) == 1

    def test_null_decided_at_not_counted(self):
        proposals = [
            {"proposal_id": "p1", "status": "approved", "decided_at": None},
        ]
        conn = _make_db(proposals)
        assert proposal_reviewer._count_reviews_today(conn) == 0


# ──────────────────────────────────────────────
# _record_cost_guard_incident
# ──────────────────────────────────────────────

class TestRecordCostGuardIncident:
    def test_writes_incident_row(self):
        conn = _make_db()
        proposal_reviewer._record_cost_guard_incident(
            conn, reviewed_today=55, pending_remaining=3
        )
        row = conn.execute("SELECT code, detail_json FROM incidents").fetchone()
        assert row is not None
        assert row[0] == "LLM_COST_GUARD"
        detail = json.loads(row[1])
        assert detail["reviewed_today"] == 55
        assert detail["pending_remaining"] == 3
        assert "daily_limit" in detail

    def test_does_not_raise_on_missing_table(self):
        """Graceful failure — incidents table may not exist in edge cases."""
        conn = sqlite3.connect(":memory:")
        # No incidents table created — should log and not raise
        proposal_reviewer._record_cost_guard_incident(
            conn, reviewed_today=10, pending_remaining=5
        )


# ──────────────────────────────────────────────
# auto_review_pending_proposals — cost guard
# ──────────────────────────────────────────────

class TestAutoReviewCostGuard:
    """auto_review_pending_proposals should stop when daily limit is reached."""

    def _pending_proposal(self, pid: str) -> dict:
        return {
            "proposal_id": pid,
            "status": "pending",
            "decided_at": None,
            "expires_at": None,
        }

    def test_stops_at_daily_limit(self, monkeypatch):
        """When reviewed_today >= limit, no new LLM calls should be made."""
        # Patch limit to 2
        monkeypatch.setattr(proposal_reviewer, "_LLM_DAILY_LIMIT", 2)

        # Pre-fill 2 already-reviewed proposals today
        already = [
            {"proposal_id": f"done{i}", "status": "approved", "decided_at": _today_ms() + i}
            for i in range(2)
        ]
        pending = [self._pending_proposal("new1"), self._pending_proposal("new2")]
        conn = _make_db(already + pending)

        minimax_called = []

        def fake_minimax(model, prompt):
            minimax_called.append(prompt)
            return {"decision": "approve", "confidence": 0.9, "reason": "OK"}

        tg_messages = []

        def fake_send(msg):
            tg_messages.append(msg)

        monkeypatch.setattr(
            "openclaw.proposal_reviewer._gemini_review",
            lambda **kw: fake_minimax("", ""),
        )
        monkeypatch.setattr("openclaw.tg_notify.send_message", fake_send)
        # patch tg_approver import used inside auto_review
        monkeypatch.setattr(
            "openclaw.tg_approver._fmt_symbol",
            lambda conn, sym: sym,
            raising=False,
        )

        result = proposal_reviewer.auto_review_pending_proposals(conn)

        # No proposals reviewed (limit already hit)
        assert result == 0
        assert len(minimax_called) == 0
        # Cost guard Telegram notification sent
        assert any("費用守衛" in m for m in tg_messages)

    def test_reviews_when_under_limit(self, monkeypatch):
        """When reviewed_today < limit, proposals are processed normally."""
        monkeypatch.setattr(proposal_reviewer, "_LLM_DAILY_LIMIT", 10)

        pending = [self._pending_proposal("p1")]
        conn = _make_db(pending)

        monkeypatch.setattr(
            "openclaw.proposal_reviewer._gemini_review",
            lambda **kw: {"decision": "approve", "confidence": 0.8, "reason": "Good"},
        )
        monkeypatch.setattr("openclaw.tg_notify.send_message", lambda msg: None)
        monkeypatch.setattr(
            "openclaw.tg_approver._fmt_symbol",
            lambda conn, sym: sym,
            raising=False,
        )

        result = proposal_reviewer.auto_review_pending_proposals(conn)

        assert result == 1
        # Proposal should be marked approved in DB
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
        ).fetchone()
        assert row[0] == "approved"

    def test_incident_written_when_limit_hit(self, monkeypatch):
        """Incident table entry must be created when cost guard triggers."""
        monkeypatch.setattr(proposal_reviewer, "_LLM_DAILY_LIMIT", 1)

        already = [
            {"proposal_id": "done1", "status": "approved", "decided_at": _today_ms()},
        ]
        pending = [self._pending_proposal("new1")]
        conn = _make_db(already + pending)

        monkeypatch.setattr(
            "openclaw.proposal_reviewer._gemini_review",
            lambda **kw: {"decision": "approve", "confidence": 0.9, "reason": "OK"},
        )
        monkeypatch.setattr("openclaw.tg_notify.send_message", lambda msg: None)
        monkeypatch.setattr(
            "openclaw.tg_approver._fmt_symbol",
            lambda conn, sym: sym,
            raising=False,
        )

        proposal_reviewer.auto_review_pending_proposals(conn)

        incident = conn.execute(
            "SELECT code FROM incidents WHERE code='LLM_COST_GUARD'"
        ).fetchone()
        assert incident is not None

    def test_no_action_when_no_pending(self, monkeypatch):
        """Empty pending queue returns 0 without touching LLM or incidents."""
        monkeypatch.setattr(proposal_reviewer, "_LLM_DAILY_LIMIT", 5)
        conn = _make_db()

        minimax_called = []
        monkeypatch.setattr(
            "openclaw.proposal_reviewer._gemini_review",
            lambda **kw: minimax_called.append(True) or {},
        )

        result = proposal_reviewer.auto_review_pending_proposals(conn)
        assert result == 0
        assert minimax_called == []
