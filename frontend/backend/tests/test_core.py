"""Tests for app/core/*.py — covering missing lines."""
from __future__ import annotations

import logging
import pytest


class TestSensitiveFilter:
    def test_filter_passes_normal_message(self):
        """Normal messages are not redacted."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="normal message", args=(), exc_info=None
        )
        result = f.filter(record)
        assert result is True
        assert record.msg == "normal message"

    def test_filter_redacts_token_message(self):
        """Messages containing 'token' are redacted."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="bearer token=abc123", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "[REDACTED]"
        assert record.args == ()

    def test_filter_redacts_password_message(self):
        """Messages containing 'password' are redacted."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="user password is secret", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "[REDACTED]"

    def test_filter_redacts_authorization(self):
        """Messages containing 'authorization' are redacted."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="authorization: Bearer abc", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "[REDACTED]"

    def test_filter_handles_message_error_gracefully(self):
        """Filter never breaks logging, even if getMessage raises."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()

        class BadRecord:
            def getMessage(self):
                raise RuntimeError("getMessage failed")
            msg = "original"
            args = ()

        record = BadRecord()
        result = f.filter(record)
        assert result is True  # Never break logging

    def test_filter_case_insensitive(self):
        """Filter matches case-insensitively."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="TOKEN value", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "[REDACTED]"

    def test_filter_custom_patterns(self):
        """Custom patterns are respected."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter(patterns=["secret", "key"])
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="my secret value", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "[REDACTED]"

    def test_filter_no_match_not_redacted(self):
        """Non-sensitive messages are not redacted."""
        from app.core.logging import SensitiveFilter
        f = SensitiveFilter(patterns=["secret"])
        record = logging.LogRecord(
            name="test", level=logging.INFO,
            pathname="", lineno=0, msg="market open at 9:00", args=(), exc_info=None
        )
        f.filter(record)
        assert record.msg == "market open at 9:00"


class TestSetupLogging:
    def test_setup_logging_runs_without_error(self):
        """setup_logging() should run without raising."""
        from app.core.logging import setup_logging
        setup_logging()  # Should not raise

    def test_setup_logging_with_custom_level(self, monkeypatch):
        """setup_logging() reads LOG_LEVEL env var without raising."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        from app.core.logging import setup_logging
        # setup_logging should not raise even with custom level
        setup_logging()  # No assertion needed — just verify it runs


class TestErrorHandlers:
    def test_http_exception_handler(self):
        """http_exception_handler returns correct JSON response."""
        from app.core.errors import http_exception_handler
        from starlette.exceptions import HTTPException as StarletteHTTPException
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/test",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        exc = StarletteHTTPException(status_code=404, detail="Not found")
        response = http_exception_handler(request, exc)
        assert response.status_code == 404

    def test_unhandled_exception_handler(self):
        """unhandled_exception_handler returns 500 with error details."""
        from app.core.errors import unhandled_exception_handler
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/crash",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope)
        exc = ValueError("something broke")
        response = unhandled_exception_handler(request, exc)
        assert response.status_code == 500


class TestConfig:
    def test_get_settings_returns_settings(self):
        """get_settings() returns Settings instance."""
        from app.core.config import get_settings
        settings = get_settings()
        assert settings.service_name == "AI-Trader Command Center API"

    def test_parse_cors_origins_with_env(self, monkeypatch):
        """parse_cors_origins returns split list when CORS_ORIGINS is set."""
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
        import importlib
        import app.core.config as config_mod
        importlib.reload(config_mod)
        settings = config_mod.Settings()
        origins = settings.parse_cors_origins()
        assert "http://localhost:3000" in origins
        assert "http://localhost:5173" in origins

    def test_parse_cors_origins_default_when_empty(self, monkeypatch):
        """parse_cors_origins returns defaults when CORS_ORIGINS is empty string (covers line 41)."""
        from app.core.config import Settings
        # Instantiate with empty cors_origins directly to bypass .env file
        settings = Settings(CORS_ORIGINS="")
        origins = settings.parse_cors_origins()
        # Should return default list (line 41 executed)
        assert isinstance(origins, list)
        assert len(origins) > 3  # Multiple defaults
        # At least one localhost entry should be present
        assert any("localhost" in o for o in origins)


class TestStrategyService:
    def test_list_proposals(self):
        """StrategyService.list_proposals returns proposals."""
        import sqlite3
        from app.services.strategy_service import StrategyService
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE strategy_proposals (
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
        conn.execute(
            "INSERT INTO strategy_proposals (proposal_id, status, confidence, created_at) VALUES (?,?,?,?)",
            ("p1", "pending", 0.8, 1000)
        )
        conn.commit()

        svc = StrategyService()
        result = svc.list_proposals(conn, limit=10, offset=0, status=None)
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        conn.close()

    def test_list_proposals_with_status_filter(self):
        """StrategyService.list_proposals filters by status."""
        import sqlite3
        from app.services.strategy_service import StrategyService
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE strategy_proposals (
                proposal_id TEXT PRIMARY KEY, status TEXT,
                confidence REAL, created_at INTEGER
            )
        """)
        conn.execute("INSERT INTO strategy_proposals VALUES (?,?,?,?)", ("p1", "pending", 0.5, 1000))
        conn.execute("INSERT INTO strategy_proposals VALUES (?,?,?,?)", ("p2", "approved", 0.9, 2000))
        conn.commit()

        svc = StrategyService()
        result = svc.list_proposals(conn, limit=10, offset=0, status="pending")
        assert len(result["data"]) == 1
        assert result["data"][0]["proposal_id"] == "p1"
        conn.close()

    def test_list_logs(self):
        """StrategyService.list_logs returns llm traces."""
        import sqlite3
        from app.services.strategy_service import StrategyService
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE llm_traces (
                trace_id TEXT, agent TEXT, model TEXT,
                prompt TEXT, response TEXT,
                latency_ms INTEGER, prompt_tokens INTEGER,
                completion_tokens INTEGER, confidence REAL, created_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO llm_traces VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("t1", "watcher", "gemini", "prompt", "resp", 100, 50, 25, 0.8, 1000)
        )
        conn.commit()

        svc = StrategyService()
        result = svc.list_logs(conn, limit=10, offset=0, trace_id=None)
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        conn.close()

    def test_list_logs_with_trace_id_filter(self):
        """StrategyService.list_logs filters by trace_id (covers line 39-40)."""
        import sqlite3
        from app.services.strategy_service import StrategyService
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE llm_traces (
                trace_id TEXT, agent TEXT, model TEXT,
                prompt TEXT, response TEXT,
                latency_ms INTEGER, prompt_tokens INTEGER,
                completion_tokens INTEGER, confidence REAL, created_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO llm_traces VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("t1", "watcher", "gemini", "prompt1", "resp1", 100, 50, 25, 0.8, 1000)
        )
        conn.execute(
            "INSERT INTO llm_traces VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("t2", "pm", "gemini", "prompt2", "resp2", 200, 100, 50, 0.9, 2000)
        )
        conn.commit()

        svc = StrategyService()
        result = svc.list_logs(conn, limit=10, offset=0, trace_id="t1")
        assert len(result["data"]) == 1
        assert result["data"][0]["trace_id"] == "t1"
        conn.close()

    def test_ensure_rw_allowed_raises_when_disabled(self):
        """ensure_rw_allowed raises 405 when enable_rw_endpoints=False (covers lines 39-40)."""
        from app.services.strategy_service import StrategyService
        from app.core.config import Settings
        from fastapi import HTTPException
        svc = StrategyService()
        settings = Settings(ENABLE_RW_ENDPOINTS=False)
        with pytest.raises(HTTPException) as exc_info:
            svc.ensure_rw_allowed(settings)
        assert exc_info.value.status_code == 405

    def test_ensure_rw_allowed_passes_when_enabled(self):
        """ensure_rw_allowed does not raise when enable_rw_endpoints=True."""
        from app.services.strategy_service import StrategyService
        from app.core.config import Settings
        svc = StrategyService()
        settings = Settings(ENABLE_RW_ENDPOINTS=True)
        # Should not raise
        svc.ensure_rw_allowed(settings)
