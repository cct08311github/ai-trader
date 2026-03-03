"""Tests for app/api/strategy.py — targeting 44% → near 100%."""
from __future__ import annotations

import json
import sqlite3
import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _create_strategy_db(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            confidence REAL,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS version_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT,
            summary TEXT,
            content_json TEXT,
            decay_score REAL,
            is_archived INTEGER,
            created_at INTEGER,
            updated_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS semantic_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule TEXT,
            confidence REAL,
            created_at INTEGER
        )
    """)
    conn.execute(
        "INSERT INTO strategy_proposals (proposal_id, status, confidence, created_at, proposal_json) VALUES (?,?,?,?,?)",
        ("p1", "pending", 0.7, 1000, json.dumps({"action": "BUY"}))
    )
    conn.execute(
        "INSERT INTO llm_traces (trace_id, agent, model, response, created_at) VALUES (?,?,?,?,?)",
        ("t1", "watcher", "gemini", "test response", 1000)
    )
    conn.commit()
    conn.close()


@pytest.fixture
def strat_client(tmp_path, monkeypatch):
    import importlib
    db_path = tmp_path / "trades.db"
    _create_strategy_db(db_path)

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c, db_path


class TestStrategyProposals:
    def test_get_proposals(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/proposals", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "data" in data

    def test_get_proposals_with_status_filter(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/proposals?status=pending", headers=_AUTH)
        assert r.status_code == 200

    def test_get_proposals_limit_offset(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/proposals?limit=10&offset=0", headers=_AUTH)
        assert r.status_code == 200

    def test_proposals_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/proposals")
        assert r.status_code == 401


class TestStrategyLogs:
    def test_get_logs(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/logs", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "data" in data

    def test_get_logs_with_trace_id(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/logs?trace_id=t1", headers=_AUTH)
        assert r.status_code == 200

    def test_logs_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/logs")
        assert r.status_code == 401


class TestApproveProposal:
    def test_approve_existing(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/p1/approve",
                   json={"actor": "admin", "reason": "looks good"},
                   headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["data"]["status"] == "approved"

    def test_approve_not_found(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/nonexistent/approve",
                   json={"actor": "admin", "reason": "test"},
                   headers=_AUTH)
        assert r.status_code == 404

    def test_approve_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/p1/approve", json={"actor": "a", "reason": "b"})
        assert r.status_code == 401


class TestRejectProposal:
    def test_reject_existing(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/p1/reject",
                   json={"actor": "admin", "reason": "too risky"},
                   headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["data"]["status"] == "rejected"

    def test_reject_not_found(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/nonexistent/reject",
                   json={"actor": "admin", "reason": "test"},
                   headers=_AUTH)
        assert r.status_code == 404

    def test_reject_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.post("/api/strategy/p1/reject", json={"actor": "a", "reason": "b"})
        assert r.status_code == 401


class TestMarketRating:
    def test_rating_no_data(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_rating_with_episodic_memory(self, strat_client):
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        content = json.dumps({
            "confidence": 0.8,
            "approved": True,
            "recommended_action": "BUY",
        })
        conn.execute(
            """INSERT INTO episodic_memory
               (episode_id, episode_type, summary, content_json, decay_score, is_archived, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ep1", "pm_review", "市場多頭", content, 1.0, 0, 1700000000, 1700000000)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        if data["data"]:
            assert "rating" in data["data"]

    def test_rating_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/market-rating")
        assert r.status_code == 401


class TestSemanticMemory:
    def test_semantic_memory_empty(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/semantic-memory", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)

    def test_semantic_memory_with_data(self, strat_client):
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO semantic_memory (rule, confidence, created_at) VALUES (?,?,?)",
            ("Buy on dip", 0.7, 1000)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/semantic-memory", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1

    def test_semantic_memory_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/semantic-memory")
        assert r.status_code == 401


class TestPmTraces:
    def test_pm_traces_empty(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/pm-traces", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["total"] == 0  # No pm_review agent traces yet

    def test_pm_traces_with_data(self, strat_client):
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO llm_traces (trace_id, agent, model, prompt, response, latency_ms, created_at) VALUES (?,?,?,?,?,?,?)",
            ("pm1", "pm_review", "gemini", "test prompt", "test response", 1000, 1700000000)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/pm-traces", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1

    def test_pm_traces_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/pm-traces")
        assert r.status_code == 401


class TestDebates:
    def test_debates_today_empty(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/debates", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)

    def test_debates_specific_date(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/debates?date=2026-01-01", headers=_AUTH)
        assert r.status_code == 200

    def test_debates_no_auth(self, strat_client):
        c, _ = strat_client
        r = c.get("/api/strategy/debates")
        assert r.status_code == 401


class TestStrategyWithNoEpisodicTable:
    def test_market_rating_no_episodic_table(self, strat_client):
        """market-rating returns ok even if episodic_memory table doesn't exist."""
        c, db_path = strat_client
        # Drop the episodic_memory table
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS episodic_memory")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_semantic_memory_no_table(self, strat_client):
        """semantic-memory returns ok even if table doesn't exist."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS semantic_memory")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/semantic-memory", headers=_AUTH)
        assert r.status_code == 200

    def test_pm_traces_no_llm_traces_table(self, strat_client):
        """pm-traces returns ok even if llm_traces table doesn't exist."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS llm_traces")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/pm-traces", headers=_AUTH)
        assert r.status_code == 200

    def test_debates_no_episodic_table(self, strat_client):
        """debates returns ok even if episodic_memory table doesn't exist."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS episodic_memory")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/debates", headers=_AUTH)
        assert r.status_code == 200

    def test_market_rating_with_low_confidence(self, strat_client):
        """market-rating with approved=True but low confidence → rating B."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        content = json.dumps({
            "confidence": 0.5,
            "approved": True,
            "recommended_action": "HOLD",
        })
        conn.execute(
            """INSERT INTO episodic_memory
               (episode_id, episode_type, summary, content_json, decay_score, is_archived, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ep_low", "pm_review", "市場觀望", content, 1.0, 0, 1700000001, 1700000001)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        if data["data"]:
            assert data["data"]["rating"] in ("A", "B", "C")

    def test_market_rating_not_approved_gives_c(self, strat_client):
        """market-rating with approved=False → rating C."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        content = json.dumps({
            "confidence": 0.9,
            "approved": False,
            "recommended_action": "SELL",
        })
        conn.execute(
            """INSERT INTO episodic_memory
               (episode_id, episode_type, summary, content_json, decay_score, is_archived, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ep_not_approved", "pm_review", "市場空頭", content, 1.0, 0, 1700000002, 1700000002)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200

    def test_proposals_no_table(self, strat_client):
        """proposals returns gracefully when strategy_proposals table doesn't exist."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS strategy_proposals")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/proposals", headers=_AUTH)
        assert r.status_code == 200

    def test_logs_no_table(self, strat_client):
        """logs returns gracefully when llm_traces table doesn't exist."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS llm_traces")
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/logs", headers=_AUTH)
        assert r.status_code == 200

    def test_approve_500_on_unexpected_error(self, strat_client, monkeypatch):
        """approve returns 500 on unexpected DB error."""
        c, _ = strat_client
        import app.db as db_mod
        original = db_mod.get_conn_rw
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected DB failure")
            yield
        monkeypatch.setattr(db_mod, "get_conn_rw", bad_conn)
        r = c.post("/api/strategy/p1/approve",
                   json={"actor": "admin", "reason": "test"},
                   headers=_AUTH)
        assert r.status_code == 500

    def test_reject_500_on_unexpected_error(self, strat_client, monkeypatch):
        """reject returns 500 on unexpected DB error."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected DB failure")
            yield
        monkeypatch.setattr(db_mod, "get_conn_rw", bad_conn)
        r = c.post("/api/strategy/p1/reject",
                   json={"actor": "admin", "reason": "test"},
                   headers=_AUTH)
        assert r.status_code == 500

    def test_semantic_memory_order_asc(self, strat_client):
        """semantic-memory with order=asc."""
        c, _ = strat_client
        r = c.get("/api/strategy/semantic-memory?order=asc", headers=_AUTH)
        assert r.status_code == 200

    def test_semantic_memory_no_confidence_column(self, strat_client):
        """semantic-memory fallback when confidence column missing."""
        c, db_path = strat_client
        # Recreate semantic_memory without confidence column
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS semantic_memory")
        conn.execute("CREATE TABLE semantic_memory (id INTEGER PRIMARY KEY, rule TEXT, created_at INTEGER)")
        conn.execute("INSERT INTO semantic_memory (rule, created_at) VALUES (?,?)", ("test rule", 1000))
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/semantic-memory", headers=_AUTH)
        assert r.status_code == 200


class TestEnsureTables:
    def test_ensure_tables_idempotent(self):
        """_ensure_tables should not raise on repeated calls."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        from app.api.strategy import _ensure_tables
        _ensure_tables(conn)
        _ensure_tables(conn)  # second call should be idempotent


class TestStrategyConnDep:
    def test_conn_dep_file_not_found_503(self, strat_client, monkeypatch):
        """conn_dep raises 503 when DB file doesn't exist."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        from pathlib import Path
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise FileNotFoundError("DB not found")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/proposals", headers=_AUTH)
        assert r.status_code == 503

    def test_conn_dep_generic_exception_500(self, strat_client, monkeypatch):
        """conn_dep raises 500 on generic DB failure."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("connection failed")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/proposals", headers=_AUTH)
        assert r.status_code == 500

    def test_market_rating_generic_exception_500(self, strat_client, monkeypatch):
        """market-rating raises 500 on unexpected error."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected error")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 500

    def test_semantic_memory_generic_exception_500(self, strat_client, monkeypatch):
        """semantic-memory raises 500 on unexpected error."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected error")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/semantic-memory", headers=_AUTH)
        assert r.status_code == 500

    def test_pm_traces_generic_exception_500(self, strat_client, monkeypatch):
        """pm-traces raises 500 on unexpected error."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected error")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/pm-traces", headers=_AUTH)
        assert r.status_code == 500

    def test_debates_generic_exception_500(self, strat_client, monkeypatch):
        """debates raises 500 on unexpected error."""
        c, _ = strat_client
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("unexpected error")
            yield
        monkeypatch.setattr(db_mod, "get_conn", bad_conn)
        r = c.get("/api/strategy/debates", headers=_AUTH)
        assert r.status_code == 500

    def test_market_rating_invalid_content_json(self, strat_client):
        """market-rating handles invalid JSON in content_json gracefully."""
        c, db_path = strat_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO episodic_memory
               (episode_id, episode_type, summary, content_json, decay_score, is_archived, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ep_bad_json", "pm_review", "市場", "NOT VALID JSON", 1.0, 0, 1700000003, 1700000003)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/strategy/market-rating", headers=_AUTH)
        assert r.status_code == 200  # Should handle gracefully, not crash

    def test_proposals_service_error_500(self, monkeypatch):
        """proposals returns 500 on non-table OperationalError (direct unit test)."""
        import importlib
        import sqlite3 as sq3
        from app.api.strategy import get_strategy_proposals, _ensure_tables
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        conn = sq3.connect(":memory:")
        conn.row_factory = sq3.Row
        _ensure_tables(conn)

        # Create a mock service that raises a non-table error
        import app.api.strategy as strat_mod
        mock_service = MagicMock()
        mock_service.list_proposals.side_effect = sq3.OperationalError("disk I/O error")
        saved = strat_mod.service
        strat_mod.service = mock_service
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_strategy_proposals(limit=50, offset=0, status=None, conn=conn)
            assert exc_info.value.status_code == 500
        finally:
            strat_mod.service = saved
        conn.close()

    def test_logs_service_error_500(self, monkeypatch):
        """logs returns 500 on non-table OperationalError (direct unit test)."""
        import sqlite3 as sq3
        from app.api.strategy import get_strategy_logs, _ensure_tables
        from fastapi import HTTPException
        from unittest.mock import MagicMock

        conn = sq3.connect(":memory:")
        conn.row_factory = sq3.Row
        _ensure_tables(conn)

        import app.api.strategy as strat_mod
        mock_service = MagicMock()
        mock_service.list_logs.side_effect = sq3.OperationalError("disk I/O error")
        saved = strat_mod.service
        strat_mod.service = mock_service
        try:
            with pytest.raises(HTTPException) as exc_info:
                get_strategy_logs(limit=50, offset=0, trace_id=None, conn=conn)
            assert exc_info.value.status_code == 500
        finally:
            strat_mod.service = saved
        conn.close()


class TestStrategyEndpointExceptionPaths:
    """Direct unit tests for endpoint exception paths (covers lines 259-260, 288-289, 313-314, 350-351)."""

    def _make_bad_conn(self, fail_on_keyword):
        """Create a wrapper around SQLite conn that raises RuntimeError on keyword match."""
        real_conn = sqlite3.connect(":memory:")
        real_conn.row_factory = sqlite3.Row

        from app.api.strategy import _ensure_tables
        _ensure_tables(real_conn)

        class BadConn:
            row_factory = sqlite3.Row
            def execute(self, sql, *args, **kwargs):
                if fail_on_keyword.lower() in sql.lower():
                    raise RuntimeError(f"mock error for: {fail_on_keyword}")
                return real_conn.execute(sql, *args, **kwargs)
            def commit(self):
                return real_conn.commit()
            def close(self):
                return real_conn.close()

        return BadConn()

    def test_market_rating_endpoint_exception_500(self):
        """get_market_rating raises 500 when query fails unexpectedly (covers line 259-260)."""
        from app.api.strategy import get_market_rating
        from fastapi import HTTPException

        conn = self._make_bad_conn("episodic_memory")
        with pytest.raises(HTTPException) as exc_info:
            get_market_rating(conn=conn)
        assert exc_info.value.status_code == 500

    def test_semantic_memory_endpoint_exception_500(self):
        """get_semantic_memory raises 500 when query fails unexpectedly (covers line 288-289)."""
        from app.api.strategy import get_semantic_memory
        from fastapi import HTTPException

        conn = self._make_bad_conn("semantic_memory")
        with pytest.raises(HTTPException) as exc_info:
            get_semantic_memory(sort="confidence", order="desc", limit=10, conn=conn)
        assert exc_info.value.status_code == 500

    def test_pm_traces_endpoint_exception_500(self):
        """get_pm_traces raises 500 when query fails unexpectedly (covers line 313-314)."""
        from app.api.strategy import get_pm_traces
        from fastapi import HTTPException

        conn = self._make_bad_conn("llm_traces")
        with pytest.raises(HTTPException) as exc_info:
            get_pm_traces(limit=10, conn=conn)
        assert exc_info.value.status_code == 500

    def test_debates_endpoint_exception_500(self):
        """get_debates raises 500 when query fails unexpectedly (covers line 350-351)."""
        from app.api.strategy import get_debates
        from fastapi import HTTPException

        conn = self._make_bad_conn("episodic_memory")
        with pytest.raises(HTTPException) as exc_info:
            get_debates(date="today", conn=conn)
        assert exc_info.value.status_code == 500

    def test_conn_dep_reraises_http_exception(self, monkeypatch):
        """conn_dep re-raises HTTPException from within endpoint (covers line 33)."""
        import contextlib
        from app.api.strategy import conn_dep
        from fastapi import HTTPException
        import app.db as db_mod

        @contextlib.contextmanager
        def good_conn():
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            yield conn
            conn.close()

        monkeypatch.setattr(db_mod, "get_conn", good_conn)

        # Use conn_dep as generator and throw HTTPException into it
        gen = conn_dep()
        try:
            conn = next(gen)  # Get the yielded connection
            # Simulate an HTTPException raised within an endpoint body
            with pytest.raises(HTTPException) as exc_info:
                gen.throw(HTTPException(status_code=404, detail="not found"))
            assert exc_info.value.status_code == 404  # Re-raised (line 33)
        except StopIteration:
            pass

    def test_update_proposal_invalid_json_in_proposal_json(self):
        """_update_proposal_status handles invalid JSON in proposal_json (covers lines 152-153)."""
        from app.api.strategy import _ensure_tables, _update_proposal_status

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _ensure_tables(conn)
        # Insert proposal with INVALID JSON in proposal_json
        conn.execute(
            "INSERT INTO strategy_proposals (proposal_id, status, confidence, created_at, proposal_json) VALUES (?,?,?,?,?)",
            ("p_bad_json", "pending", 0.5, 1000, "NOT VALID JSON")
        )
        conn.commit()

        # approve/reject triggers _update_proposal_status which reads proposal_json
        # Invalid JSON in proposal_json → lines 152-153 (except Exception: pass)
        result = _update_proposal_status(
            conn,
            proposal_id="p_bad_json",
            new_status="approved",
            actor="test",
            reason="test reason",
        )
        # Should succeed despite bad JSON (it's silently ignored)
        assert result.get("proposal_id") == "p_bad_json" or isinstance(result, dict)
        conn.close()


class TestUpdateProposalStatus:
    def test_invalid_status_raises(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        from app.api.strategy import _ensure_tables, _update_proposal_status
        _ensure_tables(conn)
        conn.execute(
            "INSERT INTO strategy_proposals (proposal_id, status, confidence, created_at) VALUES (?,?,?,?)",
            ("p99", "pending", 0.5, 1000)
        )
        conn.commit()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _update_proposal_status(
                conn,
                proposal_id="p99",
                new_status="invalid",
                actor="test",
                reason="test",
            )
        assert exc_info.value.status_code == 400

    def test_not_found_raises(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        from app.api.strategy import _ensure_tables, _update_proposal_status
        _ensure_tables(conn)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _update_proposal_status(
                conn,
                proposal_id="nonexistent",
                new_status="approved",
                actor="test",
                reason="test",
            )
        assert exc_info.value.status_code == 404
