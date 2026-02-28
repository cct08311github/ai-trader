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
