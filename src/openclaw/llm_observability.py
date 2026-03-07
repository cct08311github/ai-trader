from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from openclaw.llm_governance import build_governance_metadata, ensure_llm_trace_governance_columns


@dataclass
class LLMTrace:
    """Normalized LLM trace record.

    This project has multiple historical DB schemas. We keep a single dataclass
    and adapt `insert_llm_trace` to detect the table columns.

    Supported schemas:
    - legacy v1.2.x: component + (prompt_text/response_text) + tools_json + metadata_json
    - v4: agent + (prompt/response) + tool_calls_json
    - "hybrid" (unit-test schema): agent + (prompt_text/response_text) + metadata

    `component` remains the primary field for backwards compatibility.
    """

    component: str
    model: str
    prompt_text: str
    response_text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int

    tools: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Optional[float] = None
    decision_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    trace_id: Optional[str] = None

    # v4 alias
    agent: Optional[str] = None

    def __post_init__(self) -> None:
        # Tests expect agent defaults to component.
        if self.agent is None:
            c = (self.component or "").strip()
            self.agent = c or None

    def effective_agent(self) -> str:
        return (self.agent or self.component or "unknown").strip() or "unknown"


def _table_columns(conn: sqlite3.Connection, table: str) -> Sequence[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return []
    return [str(r[1]) for r in rows]


def insert_llm_trace(conn: sqlite3.Connection, trace: LLMTrace, *, auto_commit: bool = True) -> str:
    """Insert LLM trace into llm_traces.

    Auto-detects schema version by inspecting table columns.
    """

    trace_id = trace.trace_id or str(uuid.uuid4())
    ensure_llm_trace_governance_columns(conn)
    cols = set(_table_columns(conn, "llm_traces"))
    meta: Dict[str, Any] = build_governance_metadata(
        prompt_text=trace.prompt_text,
        model=trace.model,
        metadata=trace.metadata,
    )

    # Best-effort token budget accounting (no-op if tables absent).
    try:
        from openclaw.token_budget import record_token_usage

        record_token_usage(
            conn,
            model=trace.model,
            prompt_tokens=int(trace.input_tokens or 0),
            completion_tokens=int(trace.output_tokens or 0),
            est_cost_twd=float(meta.get("est_cost_twd") or 0.0),
            ts_ms=meta.get("created_at_ms"),
        )
    except Exception:
        pass

    # Legacy schema (v1.2.x)
    if {"component", "prompt_text", "response_text"}.issubset(cols):
        conn.execute(
            """
            INSERT INTO llm_traces (
              trace_id, ts, component, model, decision_id, prompt_text, response_text,
              input_tokens, output_tokens, latency_ms, tools_json, confidence, metadata_json
            )
            VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                trace.component,
                trace.model,
                trace.decision_id,
                trace.prompt_text,
                trace.response_text,
                int(trace.input_tokens or 0),
                int(trace.output_tokens or 0),
                int(trace.latency_ms or 0),
                json.dumps(trace.tools, ensure_ascii=True),
                trace.confidence,
                json.dumps(meta, ensure_ascii=True),
            ),
        )
        if auto_commit:
            conn.commit()
        return trace_id

    # v4 schema
    if {"agent", "prompt", "response", "created_at"}.issubset(cols):
        created_at_ms = meta.get("created_at_ms")
        insert_cols = [
            "trace_id", "agent", "model", "prompt", "response", "latency_ms",
            "prompt_tokens", "completion_tokens", "tool_calls_json", "confidence", "created_at",
        ]
        values: List[Any] = [
            trace_id,
            trace.effective_agent(),
            trace.model,
            trace.prompt_text,
            trace.response_text,
            int(trace.latency_ms) if trace.latency_ms is not None else None,
            int(trace.input_tokens) if trace.input_tokens is not None else None,
            int(trace.output_tokens) if trace.output_tokens is not None else None,
            json.dumps(trace.tools, ensure_ascii=True),
            trace.confidence,
            int(created_at_ms) if created_at_ms is not None else None,
        ]
        for optional_col, value in (
            ("metadata_json", json.dumps(meta, ensure_ascii=True)),
            ("prompt_version", meta.get("prompt_version")),
            ("model_version", meta.get("model_version")),
            ("input_hash", meta.get("input_hash")),
            ("shadow_mode", int(bool(meta.get("shadow_mode", False)))),
        ):
            if optional_col in cols:
                insert_cols.append(optional_col)
                values.append(value)
        placeholders = ", ".join(["?"] * len(insert_cols))
        conn.execute(
            f"INSERT INTO llm_traces ({', '.join(insert_cols)}) VALUES ({placeholders})",
            values,
        )
        if auto_commit:
            conn.commit()
        return trace_id

    # Hybrid/unit-test schema
    if {"agent", "prompt_text", "response_text", "created_at"}.issubset(cols):
        conn.execute(
            """
            INSERT INTO llm_traces (
              trace_id, created_at, agent, model, prompt_text, response_text,
              input_tokens, output_tokens, latency_ms, confidence, decision_id, metadata
            )
            VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                trace.effective_agent(),
                trace.model,
                trace.prompt_text,
                trace.response_text,
                int(trace.input_tokens or 0),
                int(trace.output_tokens or 0),
                int(trace.latency_ms or 0),
                trace.confidence,
                trace.decision_id,
                json.dumps(meta, ensure_ascii=True),
            ),
        )
        if auto_commit:
            conn.commit()
        return trace_id

    raise RuntimeError(
        "llm_traces schema mismatch: expected legacy columns or v4 columns; "
        f"got={sorted(cols)}"
    )
