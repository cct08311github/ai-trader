"""Tests for batch approve/reject API endpoints.

Closes #493
"""
import json
import sqlite3
import time
import os
import importlib
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")


@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE strategy_proposals (
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
            backtest_sharpe_before REAL,
            backtest_sharpe_after REAL,
            auto_approve_eligible INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE version_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
    """)
    c.commit()
    yield c, db_path
    c.close()


def _insert_proposal(c, proposal_id, status="pending"):
    c.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            status, proposal_json, created_at)
           VALUES (?, 'agent', 'POSITION_REBALANCE', 'test', ?, '{}', ?)""",
        (proposal_id, status, int(time.time() * 1000)),
    )
    c.commit()


@pytest.fixture
def client(conn, monkeypatch):
    c, db_path = conn
    # Patch db module to use our test DB
    import app.db as db_mod
    monkeypatch.setenv("DB_PATH", db_path)
    importlib.reload(db_mod)

    from app.main import app
    from fastapi.testclient import TestClient
    return TestClient(app), c


# ---------------------------------------------------------------------------
# POST /api/strategy/proposals/batch/{action}
# ---------------------------------------------------------------------------

class TestBatchDecide:
    def test_batch_approve_happy_path(self, client):
        tc, c = client
        for pid in ("p1", "p2", "p3"):
            _insert_proposal(c, pid)

        resp = tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": ["p1", "p2", "p3"]},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "approve"
        assert data["total"] == 3
        assert len(data["succeeded"]) == 3
        assert len(data["failed"]) == 0

        # Verify DB state
        for pid in ("p1", "p2", "p3"):
            row = c.execute(
                "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
            ).fetchone()
            assert row["status"] == "approved"

    def test_batch_reject_happy_path(self, client):
        tc, c = client
        _insert_proposal(c, "p1")
        _insert_proposal(c, "p2")

        resp = tc.post(
            "/api/strategy/proposals/batch/reject",
            json={"proposal_ids": ["p1", "p2"]},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["succeeded"]) == 2
        for pid in ("p1", "p2"):
            row = c.execute(
                "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
            ).fetchone()
            assert row["status"] == "rejected"

    def test_invalid_action_returns_400(self, client):
        tc, _ = client
        resp = tc.post(
            "/api/strategy/proposals/batch/cancel",
            json={"proposal_ids": ["p1"]},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 400

    def test_empty_list_returns_422(self, client):
        tc, _ = client
        resp = tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": []},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 422

    def test_exceeds_max_returns_422(self, client):
        tc, _ = client
        ids = [f"p{i}" for i in range(51)]
        resp = tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": ids},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 422
        assert "max" in resp.json()["detail"].lower()

    def test_skip_already_decided(self, client):
        tc, c = client
        _insert_proposal(c, "p-pending")
        _insert_proposal(c, "p-approved", status="approved")

        resp = tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": ["p-pending", "p-approved"]},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        data = resp.json()
        assert len(data["succeeded"]) == 1
        assert data["succeeded"][0]["proposal_id"] == "p-pending"
        assert len(data["failed"]) == 1
        assert data["failed"][0]["proposal_id"] == "p-approved"
        assert "already" in data["failed"][0]["reason"]

    def test_not_found_in_failed(self, client):
        tc, _ = client
        resp = tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": ["nonexistent"]},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        data = resp.json()
        assert len(data["failed"]) == 1
        assert data["failed"][0]["reason"] == "not_found"

    def test_audit_log_per_proposal(self, client):
        tc, c = client
        for pid in ("p1", "p2"):
            _insert_proposal(c, pid)

        tc.post(
            "/api/strategy/proposals/batch/approve",
            json={"proposal_ids": ["p1", "p2"], "reason": "batch test"},
            headers={"Authorization": "Bearer test-bearer-token"},
        )

        logs = c.execute("SELECT * FROM version_audit_log ORDER BY id").fetchall()
        assert len(logs) >= 2
        pids_logged = {json.loads(r["details"])["proposal_id"] for r in logs}
        assert "p1" in pids_logged
        assert "p2" in pids_logged

    def test_batch_with_reason(self, client):
        tc, c = client
        _insert_proposal(c, "p1")
        resp = tc.post(
            "/api/strategy/proposals/batch/reject",
            json={"proposal_ids": ["p1"], "reason": "市場異常"},
            headers={"Authorization": "Bearer test-bearer-token"},
        )
        assert resp.status_code == 200
        log = c.execute(
            "SELECT details FROM version_audit_log WHERE version_id='p1'"
        ).fetchone()
        assert "市場異常" in log["details"]


# ---------------------------------------------------------------------------
# GET /api/strategy/proposals/batch-approve-all?token=...
# ---------------------------------------------------------------------------

class TestBatchApproveAllUrl:
    def test_approves_all_pending(self, client):
        tc, c = client
        for pid in ("p1", "p2", "p3"):
            _insert_proposal(c, pid)

        resp = tc.get(
            "/api/strategy/proposals/batch-approve-all?token=test-bearer-token"
        )
        assert resp.status_code == 200
        assert "3 筆" in resp.text

        for pid in ("p1", "p2", "p3"):
            row = c.execute(
                "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
            ).fetchone()
            assert row["status"] == "approved"

    def test_no_pending_returns_warning(self, client):
        tc, _ = client
        resp = tc.get(
            "/api/strategy/proposals/batch-approve-all?token=test-bearer-token"
        )
        assert resp.status_code == 200
        assert "無待審" in resp.text

    def test_invalid_token_returns_error(self, client):
        tc, _ = client
        resp = tc.get(
            "/api/strategy/proposals/batch-approve-all?token=wrong"
        )
        # Auth middleware may return 401 before handler checks token
        assert resp.status_code in (401, 403)
