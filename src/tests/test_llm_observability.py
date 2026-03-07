import sqlite3

from openclaw.llm_observability import LLMTrace, insert_llm_trace


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE llm_traces (
          trace_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          component TEXT NOT NULL,
          model TEXT NOT NULL,
          decision_id TEXT,
          prompt_text TEXT NOT NULL,
          response_text TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          tools_json TEXT NOT NULL DEFAULT '[]',
          confidence REAL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    return conn


def test_insert_llm_trace():
    conn = _conn()
    tid = insert_llm_trace(
        conn,
        LLMTrace(
            component="pm",
            model="gemini-3.1-pro",
            prompt_text="p",
            response_text='{"ok":true}',
            input_tokens=10,
            output_tokens=20,
            latency_ms=300,
            confidence=0.8,
        ),
    )
    row = conn.execute("SELECT model, input_tokens, confidence FROM llm_traces WHERE trace_id = ?", (tid,)).fetchone()
    assert row is not None
    assert row[0] == "gemini-3.1-pro"
    assert row[1] == 10
    assert abs(row[2] - 0.8) < 1e-9


# ---------------------------------------------------------------------------
# New tests targeting previously uncovered lines
# ---------------------------------------------------------------------------


def _conn_v4() -> sqlite3.Connection:
    """v4 schema: agent + prompt + response + created_at (INTEGER)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE llm_traces (
          trace_id TEXT PRIMARY KEY,
          agent TEXT NOT NULL,
          model TEXT NOT NULL,
          prompt TEXT NOT NULL,
          response TEXT NOT NULL,
          latency_ms INTEGER,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          tool_calls_json TEXT NOT NULL DEFAULT '[]',
          confidence REAL,
          created_at INTEGER NOT NULL
        );
        """
    )
    return conn


def _conn_hybrid() -> sqlite3.Connection:
    """Hybrid/unit-test schema: agent + prompt_text + response_text + created_at."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE llm_traces (
          trace_id TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          agent TEXT NOT NULL,
          model TEXT NOT NULL,
          prompt_text TEXT NOT NULL,
          response_text TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          confidence REAL,
          decision_id TEXT,
          metadata TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    return conn


def _conn_bad_schema() -> sqlite3.Connection:
    """Schema that does not match any known version (triggers RuntimeError)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE llm_traces (
          trace_id TEXT PRIMARY KEY,
          unknown_col TEXT
        );
        """
    )
    return conn


def test_table_columns_sqlite_error():
    """Lines 55-56: _table_columns returns [] on sqlite3.Error."""
    from openclaw.llm_observability import _table_columns
    conn = sqlite3.connect(":memory:")
    # Close the connection to provoke an error when PRAGMA is executed
    conn.close()
    result = _table_columns(conn, "llm_traces")
    assert result == []


def test_insert_llm_trace_token_budget_exception_is_swallowed():
    """Lines 82-83: exception in token_budget record is suppressed (best-effort)."""
    from unittest.mock import patch

    conn = _conn()
    # Patch record_token_usage to raise, forcing the except Exception: pass path
    with patch("openclaw.token_budget.record_token_usage", side_effect=RuntimeError("budget explode")):
        tid = insert_llm_trace(
            conn,
            LLMTrace(
                component="strategy",
                model="gemini-3.1-flash",
                prompt_text="hello",
                response_text="world",
                input_tokens=5,
                output_tokens=5,
                latency_ms=100,
                metadata={"est_cost_twd": 0.01, "created_at_ms": 1700000000000},
            ),
        )
    # Exception was silently caught; trace still inserted
    row = conn.execute("SELECT model FROM llm_traces WHERE trace_id = ?", (tid,)).fetchone()
    assert row is not None
    assert row[0] == "gemini-3.1-flash"


def test_insert_llm_trace_v4_schema():
    """Lines 114-141: v4 schema insert path."""
    conn = _conn_v4()
    trace = LLMTrace(
        component="portfolio_review",
        agent="portfolio_review",
        model="gemini-3.1-pro",
        prompt_text="analyse",
        response_text='{"action": "hold"}',
        input_tokens=50,
        output_tokens=30,
        latency_ms=250,
        confidence=0.9,
        metadata={"created_at_ms": 1700000001000},
    )
    tid = insert_llm_trace(conn, trace)
    row = conn.execute(
        """
        SELECT agent, model, prompt_tokens, completion_tokens, created_at,
               prompt_version, model_version, input_hash, shadow_mode
          FROM llm_traces
         WHERE trace_id = ?
        """,
        (tid,),
    ).fetchone()
    assert row is not None
    assert row[0] == "portfolio_review"
    assert row[1] == "gemini-3.1-pro"
    assert row[2] == 50
    assert row[3] == 30
    assert row[4] == 1700000001000
    assert row[5] == "unversioned"
    assert row[6] == "gemini-3.1-pro"
    assert row[7]
    assert row[8] == 0


def test_insert_llm_trace_v4_governance_metadata_persisted():
    conn = _conn_v4()
    tid = insert_llm_trace(
        conn,
        LLMTrace(
            component="pm",
            model="gemini-3.1-pro",
            prompt_text="hello governance",
            response_text="ok",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            metadata={
                "created_at_ms": 1700000002000,
                "prompt_version": "pm/v2",
                "model_version": "gemini-3.1-pro-001",
                "input_snapshot": {"symbol": "2330"},
                "shadow_mode": True,
            },
        ),
    )
    row = conn.execute(
        "SELECT prompt_version, model_version, input_hash, shadow_mode, metadata_json FROM llm_traces WHERE trace_id = ?",
        (tid,),
    ).fetchone()
    assert row[0] == "pm/v2"
    assert row[1] == "gemini-3.1-pro-001"
    assert row[2]
    assert row[3] == 1
    assert '"shadow_mode": true' in row[4].lower()


def test_insert_llm_trace_hybrid_schema():
    """Lines 144-169: hybrid/unit-test schema insert path."""
    conn = _conn_hybrid()
    trace = LLMTrace(
        component="system_health",
        model="gemini-3.1-flash",
        prompt_text="check health",
        response_text='{"status": "ok"}',
        input_tokens=20,
        output_tokens=10,
        latency_ms=80,
        confidence=0.75,
        decision_id="dec-abc",
        metadata={"note": "test"},
    )
    tid = insert_llm_trace(conn, trace)
    row = conn.execute(
        "SELECT agent, model, input_tokens, output_tokens, confidence, decision_id FROM llm_traces WHERE trace_id = ?",
        (tid,),
    ).fetchone()
    assert row is not None
    assert row[0] == "system_health"
    assert row[1] == "gemini-3.1-flash"
    assert row[2] == 20
    assert row[3] == 10
    assert abs(row[4] - 0.75) < 1e-9
    assert row[5] == "dec-abc"


def test_insert_llm_trace_schema_mismatch_raises():
    """Line 171: RuntimeError raised when schema does not match any known version."""
    import pytest
    conn = _conn_bad_schema()
    trace = LLMTrace(
        component="unknown",
        model="some-model",
        prompt_text="x",
        response_text="y",
        input_tokens=1,
        output_tokens=1,
        latency_ms=10,
    )
    with pytest.raises(RuntimeError, match="schema mismatch"):
        insert_llm_trace(conn, trace)
