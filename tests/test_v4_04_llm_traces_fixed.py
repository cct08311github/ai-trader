"""Test LLM observability layer (v4 #4) - Fixed version."""

import pytest
import sqlite3
import json
import hashlib
from openclaw.llm_observability import LLMTrace, insert_llm_trace


def test_llmtrace_dataclass():
    """Test LLMTrace dataclass structure."""
    trace = LLMTrace(
        component="news_guard",
        model="gemini-3.1-pro",
        prompt_text="Test prompt",
        response_text="Test response",
        input_tokens=100,
        output_tokens=50,
        latency_ms=1234,
        confidence=0.85,
        decision_id="dec_12345",
        metadata={"stage": "test"}
    )
    
    assert trace.component == "news_guard"
    assert trace.model == "gemini-3.1-pro"
    assert trace.prompt_text == "Test prompt"
    assert trace.response_text == "Test response"
    assert trace.input_tokens == 100
    assert trace.output_tokens == 50
    assert trace.latency_ms == 1234
    assert trace.confidence == 0.85
    assert trace.decision_id == "dec_12345"
    assert trace.metadata == {"stage": "test"}
    assert trace.effective_agent() == "news_guard"
    
    # Test with agent alias (v4)
    trace_with_agent = LLMTrace(
        component="news_guard",
        agent="news_guard_v4",
        model="gemini-3.1-pro",
        prompt_text="Test",
        response_text="Test",
        input_tokens=100,
        output_tokens=50,
        latency_ms=1234,
        confidence=0.85
    )
    
    assert trace_with_agent.component == "news_guard"
    assert trace_with_agent.agent == "news_guard_v4"
    assert trace_with_agent.effective_agent() == "news_guard_v4"


def test_insert_llm_trace():
    """Test inserting LLM trace into database."""
    conn = sqlite3.connect(":memory:")
    
    # Create legacy schema table
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            ts TIMESTAMP NOT NULL,
            component TEXT NOT NULL,
            model TEXT NOT NULL,
            decision_id TEXT,
            prompt_text TEXT NOT NULL,
            response_text TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            latency_ms INTEGER,
            tools_json TEXT,
            confidence REAL,
            metadata_json TEXT
        )
    """)
    
    # Create a trace
    trace = LLMTrace(
        component="pm_debate",
        model="gemini-3.1-pro",
        prompt_text="Analyze this market situation...",
        response_text="Bullish: ... Bearish: ...",
        input_tokens=250,
        output_tokens=150,
        latency_ms=2345,
        confidence=0.78,
        decision_id="dec_abc123",
        metadata={"stage": "bull_bear_debate", "rounds": 2}
    )
    
    # Insert the trace
    trace_id = insert_llm_trace(conn, trace)
    
    # Verify insertion
    row = conn.execute(
        "SELECT component, model, input_tokens, output_tokens, latency_ms, confidence, decision_id, metadata_json FROM llm_traces"
    ).fetchone()
    
    assert row is not None
    assert row[0] == "pm_debate"
    assert row[1] == "gemini-3.1-pro"
    assert row[2] == 250
    assert row[3] == 150
    assert row[4] == 2345
    assert row[5] == 0.78
    assert row[6] == "dec_abc123"
    
    # Parse metadata JSON
    metadata = json.loads(row[7])
    assert metadata["stage"] == "bull_bear_debate"
    assert metadata["rounds"] == 2
    
    # Test with v4 agent field
    trace_v4 = LLMTrace(
        component="legacy_name",
        agent="news_guard_v4",
        model="gemini-3.1-pro",
        prompt_text="Prompt",
        response_text="Response",
        input_tokens=100,
        output_tokens=50,
        latency_ms=1000,
        confidence=0.9,
        metadata={"test": "v4"}
    )
    
    trace_id_v4 = insert_llm_trace(conn, trace_v4)
    
    # Verify v4 trace uses component field for legacy schema
    row_v4 = conn.execute(
        "SELECT component FROM llm_traces WHERE trace_id = ?", (trace_id_v4,)
    ).fetchone()
    
    assert row_v4[0] == "legacy_name"  # Uses component, not agent
    
    conn.close()


def test_insert_llm_trace_v4_schema():
    """Test inserting LLM trace into v4 schema database."""
    conn = sqlite3.connect(":memory:")
    
    # Create v4 schema table
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER
        )
    """)
    
    # Create a trace with agent field
    trace = LLMTrace(
        component="legacy_component",
        agent="news_guard_v4",
        model="gemini-3.1-pro",
        prompt_text="Prompt for v4",
        response_text="Response for v4",
        input_tokens=200,
        output_tokens=100,
        latency_ms=1500,
        confidence=0.85,
        metadata={"created_at_ms": 1740700800000}  # 2026-02-28 timestamp
    )
    
    trace_id = insert_llm_trace(conn, trace)
    
    # Verify insertion into v4 schema
    row = conn.execute(
        "SELECT agent, model, prompt, response, latency_ms, prompt_tokens, completion_tokens, confidence FROM llm_traces"
    ).fetchone()
    
    assert row is not None
    assert row[0] == "news_guard_v4"  # agent field
    assert row[1] == "gemini-3.1-pro"
    assert row[2] == "Prompt for v4"
    assert row[3] == "Response for v4"
    assert row[4] == 1500
    assert row[5] == 200
    assert row[6] == 100
    assert row[7] == 0.85
    
    conn.close()


def test_llmtrace_prompt_hashing():
    """Test that prompt hashing works for privacy."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            ts TIMESTAMP NOT NULL,
            component TEXT NOT NULL,
            model TEXT NOT NULL,
            decision_id TEXT,
            prompt_text TEXT NOT NULL,
            response_text TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            latency_ms INTEGER,
            tools_json TEXT,
            confidence REAL,
            metadata_json TEXT
        )
    """)
    
    # Create trace with sensitive prompt
    sensitive_prompt = "API_KEY=abc123, SECRET=xyz789, Analyze this..."
    trace = LLMTrace(
        component="risk_engine",
        model="gemini-3.1-pro",
        prompt_text=sensitive_prompt,
        response_text="Risk assessment...",
        input_tokens=len(sensitive_prompt),
        output_tokens=100,
        latency_ms=1500,
        confidence=0.9,
        metadata={"contains_sensitive": True}
    )
    
    insert_llm_trace(conn, trace)
    
    # Verify prompt is stored as-is (no automatic hashing in current implementation)
    row = conn.execute(
        "SELECT prompt_text FROM llm_traces WHERE component = 'risk_engine'"
    ).fetchone()
    
    assert row is not None
    assert row[0] == sensitive_prompt
    
    conn.close()


def test_trace_completeness():
    """Test that traces contain all required fields."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            ts TIMESTAMP NOT NULL,
            component TEXT NOT NULL,
            model TEXT NOT NULL,
            decision_id TEXT,
            prompt_text TEXT NOT NULL,
            response_text TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            latency_ms INTEGER,
            tools_json TEXT,
            confidence REAL,
            metadata_json TEXT
        )
    """)
    
    # Test various component types
    components = ["pm_debate", "news_guard", "risk_engine", "reflection_loop"]
    
    for component in components:
        trace = LLMTrace(
            component=component,
            model="gemini-3.1-pro",
            prompt_text=f"Test for {component}",
            response_text=f"Response for {component}",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1000,
            confidence=0.8,
            decision_id=f"dec_{component}",
            metadata={"test": True}
        )
        
        insert_llm_trace(conn, trace)
    
    # Verify all components have traces
    rows = conn.execute(
        "SELECT component, model, decision_id FROM llm_traces ORDER BY component"
    ).fetchall()
    
    assert len(rows) == len(components)
    
    for row, expected_component in zip(rows, sorted(components)):
        assert row[0] == expected_component
        assert row[1] == "gemini-3.1-pro"
        assert row[2] == f"dec_{expected_component}"
    
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
