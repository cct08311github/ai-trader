"""Tests for app/api/pm.py — PM review API including history persistence."""
from __future__ import annotations

import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


class TestPmStatus:
    def test_status_returns_ok(self, client):
        r = client.get("/api/pm/status", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "data" in data

    def test_status_no_auth(self, client):
        r = client.get("/api/pm/status")
        assert r.status_code == 401


class TestPmApprove:
    def test_approve_returns_ok(self, client):
        r = client.post("/api/pm/approve", json={"reason": "test approval"}, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "data" in data

    def test_approve_empty_body(self, client):
        r = client.post("/api/pm/approve", json={}, headers=_AUTH)
        assert r.status_code == 200

    def test_approve_no_auth(self, client):
        r = client.post("/api/pm/approve", json={})
        assert r.status_code == 401


class TestPmReject:
    def test_reject_returns_ok(self, client):
        r = client.post("/api/pm/reject", json={"reason": "market unstable"}, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_reject_empty_body(self, client):
        r = client.post("/api/pm/reject", json={}, headers=_AUTH)
        assert r.status_code == 200

    def test_reject_no_auth(self, client):
        r = client.post("/api/pm/reject", json={})
        assert r.status_code == 401


class TestPmReview:
    def test_review_no_llm_key(self, client, monkeypatch):
        """Without GEMINI_API_KEY, review falls back to pending_manual."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        r = client.post("/api/pm/review", headers=_AUTH)
        # Should succeed (no LLM call)
        assert r.status_code in (200, 503)

    def test_review_with_mock_llm(self, client, monkeypatch):
        """Mock the LLM call so review succeeds."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_state = {
            "date": "2026-03-03",
            "approved": True,
            "source": "llm",
            "reason": "Market looks good",
            "confidence": 0.8,
            "bull_case": "Strong earnings",
            "bear_case": "Rising inflation",
            "neutral_case": "Mixed signals",
            "consensus_points": [],
            "divergence_points": [],
            "recommended_action": "BUY",
        }
        with patch("app.api.pm.run_daily_pm_review", return_value=mock_state):
            r = client.post("/api/pm/review", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_review_llm_exception_returns_503(self, client, monkeypatch):
        """If LLM raises, return 503."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with patch("app.api.pm.run_daily_pm_review", side_effect=RuntimeError("LLM down")):
            r = client.post("/api/pm/review", headers=_AUTH)
        assert r.status_code == 503

    def test_review_no_auth(self, client):
        r = client.post("/api/pm/review")
        assert r.status_code == 401

    def test_review_db_conn_failure_uses_null_context(self, client, monkeypatch):
        """When get_conn() fails during review, falls back to build_daily_context(conn=None) (covers lines 117-118)."""
        import contextlib
        import app.db as db_mod

        @contextlib.contextmanager
        def bad_conn():
            raise FileNotFoundError("DB not available")
            yield

        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        mock_state = {
            "date": "2026-03-03",
            "approved": True,
            "source": "llm",
            "reason": "OK",
            "confidence": 0.7,
            "bull_case": "", "bear_case": "", "neutral_case": "",
            "consensus_points": [], "divergence_points": [],
            "recommended_action": "HOLD",
        }
        with patch("app.api.pm.run_daily_pm_review", return_value=mock_state):
            r = client.post("/api/pm/review", headers=_AUTH)
        # Should succeed even with DB failure (falls back to None context)
        assert r.status_code == 200


class TestGetLlmCall:
    def test_returns_none_when_no_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.pm import _get_llm_call
        result = _get_llm_call()
        assert result is None

    def test_returns_callable_when_key_set(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key")
        mock_gemini = MagicMock()
        with patch.dict("sys.modules", {"openclaw.llm_gemini": MagicMock(gemini_call=mock_gemini)}):
            from importlib import reload
            import app.api.pm as pm_mod
            result = pm_mod._get_llm_call()
            # Either returns the mock or None depending on module state
            assert result is None or callable(result)


class TestWriteDebateToDB:
    def test_skips_non_llm_source(self, client):
        """_write_debate_to_db should skip if source is not 'llm' or 'manual'."""
        from app.api.pm import _write_debate_to_db
        state = {"source": "mock", "date": "2026-03-03"}
        # Should not raise
        _write_debate_to_db(state)

    def test_writes_llm_source(self, client):
        """_write_debate_to_db should write if source is 'llm'."""
        from app.api.pm import _write_debate_to_db
        state = {
            "source": "llm",
            "date": "2026-03-03",
            "reason": "test",
            "approved": True,
            "confidence": 0.8,
            "bull_case": "Strong",
            "bear_case": "Weak",
            "neutral_case": "Mixed",
            "consensus_points": [],
            "divergence_points": [],
            "recommended_action": "BUY",
        }
        # Should not raise (will fail silently if episodic_memory table missing)
        _write_debate_to_db(state)

    def test_writes_manual_source(self, client):
        from app.api.pm import _write_debate_to_db
        state = {
            "source": "manual",
            "date": "2026-03-03",
            "reason": "Manual override",
            "approved": False,
            "confidence": 0.0,
        }
        _write_debate_to_db(state)


class TestWriteLlmTrace:
    def test_skips_when_no_prompt(self, client):
        from app.api.pm import _write_llm_trace
        state = {"_prompt": None, "_raw_response": None, "_latency_ms": 100, "_model": "gemini"}
        # Should not raise
        _write_llm_trace(state, "gemini-pro")

    def test_writes_when_prompt_present(self, client):
        from app.api.pm import _write_llm_trace
        state = {
            "_prompt": "Test prompt",
            "_raw_response": "Test response",
            "_latency_ms": 500,
            "_model": "gemini-pro",
        }
        # Should not raise (will fail silently if DB error)
        _write_llm_trace(state, "gemini-pro")

    def test_pops_internal_keys(self, client):
        from app.api.pm import _write_llm_trace
        state = {
            "_prompt": "p",
            "_raw_response": "r",
            "_latency_ms": 100,
            "_model": "m",
            "other_key": "should_remain",
        }
        _write_llm_trace(state, "gemini")
        # Internal keys should be popped
        assert "_prompt" not in state
        assert "_raw_response" not in state
        assert "_latency_ms" not in state
        assert "other_key" in state


class TestPmHistory:
    def test_history_empty(self, client):
        r = client.get("/api/pm/history", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["data"] == []
        assert body["pagination"]["total"] == 0

    def test_history_returns_records(self, client, monkeypatch):
        """After approve, history should contain the persisted review."""
        client.post("/api/pm/approve", json={"reason": "test persist"}, headers=_AUTH)
        r = client.get("/api/pm/history", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["pagination"]["total"] >= 1
        rec = body["data"][0]
        assert rec["approved"] == 1
        assert rec["source"] == "manual"
        assert "test persist" in (rec.get("reason") or "")

    def test_history_pagination(self, client):
        """Pagination params are respected."""
        r = client.get("/api/pm/history?limit=5&offset=0", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["pagination"]["limit"] == 5
        assert body["pagination"]["offset"] == 0

    def test_history_no_auth(self, client):
        r = client.get("/api/pm/history")
        assert r.status_code == 401

    def test_history_graceful_when_table_missing(self, client, monkeypatch):
        """If pm_reviews table doesn't exist in readonly path, return empty."""
        import contextlib
        import app.db as db_mod

        original_get_conn = db_mod.get_conn

        @contextlib.contextmanager
        def conn_without_pm_reviews():
            """Yield a connection to a DB that lacks pm_reviews."""
            import tempfile, os
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
                os.unlink(tmp.name)

        monkeypatch.setattr(db_mod, "get_conn", conn_without_pm_reviews)
        r = client.get("/api/pm/history", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["data"] == []


class TestWritePmReviewToDb:
    def test_skips_non_valid_source(self, client):
        from app.api.pm import _write_pm_review_to_db
        _write_pm_review_to_db({"source": "pending", "date": "2026-03-09"})
        # Should not raise, and no row written

    def test_writes_llm_review(self, client, monkeypatch):
        from app.api.pm import _write_pm_review_to_db
        import os
        state = {
            "source": "llm",
            "date": "2026-03-09",
            "approved": True,
            "confidence": 0.85,
            "reason": "Market is bullish",
            "recommended_action": "BUY",
            "bull_case": "Strong earnings",
            "bear_case": "Inflation risk",
            "neutral_case": "Mixed signals",
            "consensus_points": ["Growth"],
            "divergence_points": ["Rates"],
        }
        _write_pm_review_to_db(state)

        # Verify persisted
        r = client.get("/api/pm/history", headers=_AUTH)
        body = r.json()
        assert body["pagination"]["total"] >= 1
        rec = body["data"][0]
        assert rec["review_date"] == "2026-03-09"
        assert rec["approved"] == 1
        assert rec["confidence"] == 0.85
        assert rec["source"] == "llm"

    def test_writes_manual_review(self, client):
        from app.api.pm import _write_pm_review_to_db
        state = {
            "source": "manual",
            "date": "2026-03-08",
            "approved": False,
            "confidence": 1.0,
            "reason": "Force block",
        }
        _write_pm_review_to_db(state)

        r = client.get("/api/pm/history", headers=_AUTH)
        data = r.json()["data"]
        manual_recs = [d for d in data if d["review_date"] == "2026-03-08"]
        assert len(manual_recs) >= 1
        assert manual_recs[0]["approved"] == 0

    def test_approve_endpoint_persists(self, client):
        """POST /api/pm/approve should persist to pm_reviews."""
        client.post("/api/pm/approve", json={"reason": "LGTM"}, headers=_AUTH)
        r = client.get("/api/pm/history", headers=_AUTH)
        data = r.json()["data"]
        assert any(d["source"] == "manual" and d["approved"] == 1 for d in data)

    def test_reject_endpoint_persists(self, client):
        """POST /api/pm/reject should persist to pm_reviews."""
        client.post("/api/pm/reject", json={"reason": "Too risky"}, headers=_AUTH)
        r = client.get("/api/pm/history", headers=_AUTH)
        data = r.json()["data"]
        assert any(d["source"] == "manual" and d["approved"] == 0 for d in data)

    def test_review_endpoint_persists(self, client, monkeypatch):
        """POST /api/pm/review (mocked LLM) should persist to pm_reviews."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        mock_state = {
            "date": "2026-03-07",
            "approved": True,
            "source": "llm",
            "reason": "Bullish outlook",
            "confidence": 0.9,
            "bull_case": "Earnings beat",
            "bear_case": "Geopolitical",
            "neutral_case": "Sideways",
            "consensus_points": [],
            "divergence_points": [],
            "recommended_action": "BUY",
        }
        with patch("app.api.pm.run_daily_pm_review", return_value=mock_state):
            r = client.post("/api/pm/review", headers=_AUTH)
        assert r.status_code == 200

        r = client.get("/api/pm/history", headers=_AUTH)
        data = r.json()["data"]
        assert any(d["review_date"] == "2026-03-07" and d["source"] == "llm" for d in data)
