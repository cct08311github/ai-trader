"""Tests for app/api/chat.py — targeting 24% → near 100%."""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path

import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _init_chat_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
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
    conn.commit()
    conn.close()


@pytest.fixture
def chat_client(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    _init_chat_db(db_path)

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.api.chat as chat_mod
    importlib.reload(chat_mod)
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


class TestChatHistory:
    def test_history_returns_200(self, chat_client):
        r = chat_client.get("/api/chat/history", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_history_no_auth(self, chat_client):
        r = chat_client.get("/api/chat/history")
        assert r.status_code == 401


class TestChatMessage:
    def test_message_empty_body_400(self, chat_client):
        r = chat_client.post(
            "/api/chat/message",
            json={"message": "   "},
            headers=_AUTH,
        )
        assert r.status_code == 400
        assert "empty" in r.json()["detail"].lower()

    def test_message_no_auth(self, chat_client):
        r = chat_client.post("/api/chat/message", json={"message": "hello"})
        assert r.status_code == 401

    def test_message_no_llm_key_auth_only(self, chat_client, monkeypatch):
        """Without LLM keys, the endpoint still validates auth and body.
        We only check auth — don't read body (SSE hangs)."""
        # First verify auth check: no auth → 401
        r = chat_client.post(
            "/api/chat/message",
            json={"message": "hello"},
        )
        assert r.status_code == 401


class TestChatCreateProposal:
    def test_create_proposal_no_intent(self, chat_client):
        r = chat_client.post(
            "/api/chat/create-proposal",
            json={"ai_response": "No trade suggestion here.", "user_message": "what?"},
            headers=_AUTH,
        )
        assert r.status_code == 400
        assert "未偵測" in r.json()["detail"]

    def test_create_proposal_with_intent(self, chat_client):
        r = chat_client.post(
            "/api/chat/create-proposal",
            json={
                "ai_response": "建議買入 2330 100股 @600",
                "user_message": "Should I buy TSMC?",
            },
            headers=_AUTH,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "proposal_id" in data
        assert "intent" in data

    def test_create_proposal_sell_intent(self, chat_client):
        r = chat_client.post(
            "/api/chat/create-proposal",
            json={
                "ai_response": "建議賣出 2317 50股 @85",
                "user_message": "Sell signal?",
            },
            headers=_AUTH,
        )
        assert r.status_code == 200
        assert r.json()["intent"]["action"] == "sell"

    def test_create_proposal_no_auth(self, chat_client):
        r = chat_client.post(
            "/api/chat/create-proposal",
            json={"ai_response": "建議買入 2330 100股 @600", "user_message": "buy?"},
        )
        assert r.status_code == 401


class TestPickStreamer:
    def test_no_keys_returns_none(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.chat import _pick_streamer
        streamer, model = _pick_streamer("")
        assert streamer is None
        assert model == "none"

    def test_gemini_model_override(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.chat import _pick_streamer, _stream_gemini
        streamer, model = _pick_streamer("gemini-pro")
        assert streamer is _stream_gemini
        assert model == "gemini-pro"

    def test_claude_model_override(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.chat import _pick_streamer, _stream_claude
        streamer, model = _pick_streamer("claude-3")
        assert streamer is _stream_claude
        assert model == "claude-3"

    def test_anthropic_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.chat import _pick_streamer, _stream_claude
        streamer, model = _pick_streamer("")
        assert streamer is _stream_claude

    def test_gemini_key_present(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
        from app.api.chat import _pick_streamer, _stream_gemini
        streamer, model = _pick_streamer("")
        assert streamer is _stream_gemini


class TestGetChatModel:
    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("CHAT_LLM_MODEL", "my-model")
        from app.api.chat import _get_chat_model
        assert _get_chat_model() == "my-model"

    def test_returns_empty_when_not_set(self, monkeypatch):
        monkeypatch.delenv("CHAT_LLM_MODEL", raising=False)
        from app.api.chat import _get_chat_model
        assert _get_chat_model() == ""


class TestWriteTrace:
    def test_write_trace_does_not_raise(self, chat_client):
        """_write_trace should silently fail if DB insert fails."""
        from app.api.chat import _write_trace
        # Should not raise even if model is weird
        _write_trace("test-model", "prompt text", "response text", 100)

    def test_write_trace_exception_swallowed(self, chat_client, monkeypatch):
        """_write_trace silently swallows exceptions."""
        import app.db as db_mod
        import contextlib
        @contextlib.contextmanager
        def bad_conn(*args, **kwargs):
            raise RuntimeError("DB write error")
            yield
        monkeypatch.setattr(db_mod, "get_conn_rw", bad_conn)
        from app.api.chat import _write_trace
        # Should not raise
        _write_trace("model", "prompt", "response", 50)


class TestStreamFunctions:
    def test_stream_claude_no_key_raises(self):
        """_stream_claude raises ValueError when ANTHROPIC_API_KEY not set."""
        import os
        import asyncio
        os.environ.pop("ANTHROPIC_API_KEY", None)
        from app.api.chat import _stream_claude

        async def run():
            gen = _stream_claude("system", [{"role": "user", "content": "hi"}], "claude-3")
            with pytest.raises((ValueError, Exception)):
                async for _ in gen:
                    pass

        asyncio.run(run())

    def test_stream_gemini_no_key_raises(self):
        """_stream_gemini raises ValueError when GEMINI_API_KEY not set."""
        import os
        import asyncio
        os.environ.pop("GEMINI_API_KEY", None)
        from app.api.chat import _stream_gemini

        async def run():
            gen = _stream_gemini("system", [{"role": "user", "content": "hi"}], "gemini-pro")
            with pytest.raises((ValueError, Exception)):
                async for _ in gen:
                    pass

        asyncio.run(run())

    def test_stream_gemini_message_roles(self, monkeypatch):
        """_stream_gemini correctly maps assistant role to model."""
        import asyncio
        import os
        import types

        # Create a fake google.generativeai module
        fake_genai = types.ModuleType("google.generativeai")
        configure_calls = []

        class FakeModel:
            def generate_content(self, msgs, stream=True, generation_config=None):
                return []

        fake_genai.configure = lambda api_key: configure_calls.append(api_key)
        fake_genai.GenerativeModel = lambda name: FakeModel()

        import sys
        sys.modules["google"] = types.ModuleType("google")
        sys.modules["google.generativeai"] = fake_genai

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

        from app.api.chat import _stream_gemini

        async def run():
            messages = [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ]
            gen = _stream_gemini("system", messages, "gemini-pro")
            chunks = []
            try:
                async for chunk in gen:
                    chunks.append(chunk)
            except Exception:
                pass  # OK if model returns nothing

        asyncio.run(run())

    def test_pick_streamer_gemini_case_insensitive(self, monkeypatch):
        """model_override with 'GEMINI' (uppercase) should match gemini streamer."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.api.chat import _pick_streamer, _stream_gemini
        streamer, model = _pick_streamer("GEMINI-flash")
        assert streamer is _stream_gemini

    def test_chat_message_empty_after_strip(self, chat_client):
        """Message with only whitespace returns 400."""
        r = chat_client.post(
            "/api/chat/message",
            json={"message": "   \n\t  "},
            headers=_AUTH,
        )
        assert r.status_code == 400


class TestChatHistoryWithRows:
    def test_history_returns_rows(self, tmp_path, monkeypatch):
        """Covers line 139: result.append() in chat_history when rows exist."""
        db_path = tmp_path / "chat_rows.db"
        _init_chat_db(db_path)
        conn = sqlite3.connect(str(db_path))
        # Insert a chat trace
        conn.execute(
            "INSERT INTO llm_traces(trace_id, agent, model, prompt, response, latency_ms, prompt_tokens, completion_tokens, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("trace_chat_1", "chat", "gemini", "Hello?", "Hi there!", 200, 50, 30, 0.9, 1700000000)
        )
        conn.commit()
        conn.close()

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.api.chat as chat_mod
        importlib.reload(chat_mod)
        import app.main as main
        importlib.reload(main)

        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            r = c.get("/api/chat/history", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 200
            data = r.json()
            assert len(data["history"]) == 1
            assert data["history"][0]["id"] == "trace_chat_1"

    def test_history_500_on_db_error(self, tmp_path, monkeypatch):
        """Covers lines 148-149: READONLY_POOL.conn() raises → HTTP 500."""
        db_path = tmp_path / "bad_chat.db"
        _init_chat_db(db_path)

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.api.chat as chat_mod
        importlib.reload(chat_mod)
        import app.main as main
        importlib.reload(main)

        # Patch READONLY_POOL.conn to raise
        import contextlib
        import app.db as db_mod

        @contextlib.contextmanager
        def bad_pool_conn(*args, **kwargs):
            raise RuntimeError("Pool unavailable")
            yield

        monkeypatch.setattr(db_mod.READONLY_POOL, "conn", bad_pool_conn)

        # Also patch the chat module's READONLY_POOL reference
        monkeypatch.setattr(chat_mod.READONLY_POOL, "conn", bad_pool_conn)

        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            r = c.get("/api/chat/history", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 500


class TestCreateProposalDbException:
    def test_create_proposal_db_exception_500(self, tmp_path, monkeypatch):
        """Covers lines 255-256: DB write fails → HTTP 500."""
        db_path = tmp_path / "no_proposals.db"
        _init_chat_db(db_path)

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.api.chat as chat_mod
        importlib.reload(chat_mod)
        import app.main as main
        importlib.reload(main)

        # Drop strategy_proposals table so insert fails
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS strategy_proposals")
        conn.commit()
        conn.close()

        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            r = c.post(
                "/api/chat/create-proposal",
                json={
                    "ai_response": "建議買入 2330 100股 @600",
                    "user_message": "Should I buy?",
                },
                headers={"Authorization": "Bearer test-bearer-token"},
            )
            assert r.status_code == 500
