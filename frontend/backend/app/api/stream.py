from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.db import DB_PATH, connect_readonly

router = APIRouter(prefix="/api/stream", tags=["stream"])


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


# Tuning / safety knobs
SSE_MAX_CLIENTS = max(1, _env_int("SSE_MAX_CLIENTS", 10))
SSE_POLL_INTERVAL_MS = max(200, _env_int("SSE_POLL_INTERVAL_MS", 800))
SSE_HEARTBEAT_SEC = max(1, _env_int("SSE_HEARTBEAT_SEC", 5))
SSE_BATCH_LIMIT = max(1, min(_env_int("SSE_BATCH_LIMIT", 50), 200))

_client_sema = asyncio.Semaphore(SSE_MAX_CLIENTS)


@dataclass
class Cursor:
    """SSE cursor.

    We use SQLite `rowid` as the cursor because it is monotonic for inserts.
    """

    rowid: int = 0


def _parse_last_event_id(value: Optional[str]) -> Cursor:
    if not value:
        return Cursor(rowid=0)
    try:
        return Cursor(rowid=max(0, int(str(value).strip())))
    except Exception:
        return Cursor(rowid=0)


def _mask_sensitive(s: str) -> str:
    """Best-effort redaction.

    Streaming prompt/response is OFF by default; if enabled, we still do a light mask.
    """

    if not s:
        return s

    for token in ["sk-", "AIza", "xoxb-", "xoxp-"]:
        if token in s:
            s = s.replace(token, token[0] + "***")

    return s


def _to_log_event(row: Dict[str, Any]) -> Dict[str, Any]:
    created_at = row.get("created_at")
    try:
        ts_ms = int(created_at) * 1000
    except Exception:
        ts_ms = int(time.time() * 1000)

    evt: Dict[str, Any] = {
        "type": "trace",
        "level": "INFO",
        "ts": ts_ms,
        "trace_id": row.get("trace_id"),
        "agent": row.get("agent"),
        "model": row.get("model"),
        "latency_ms": row.get("latency_ms"),
        "prompt_tokens": row.get("prompt_tokens"),
        "completion_tokens": row.get("completion_tokens"),
        "confidence": row.get("confidence"),
        "message": "LLM decision trace recorded",
    }

    # Sensitive fields are excluded unless explicitly enabled.
    include_prompt = os.environ.get("LOG_STREAM_INCLUDE_PROMPT", "0") == "1"
    include_response = os.environ.get("LOG_STREAM_INCLUDE_RESPONSE", "0") == "1"

    if include_prompt:
        evt["prompt_excerpt"] = _mask_sensitive(str(row.get("prompt") or ""))[:800]
    if include_response:
        evt["response_excerpt"] = _mask_sensitive(str(row.get("response") or ""))[:1200]

    return evt


def _fetch_new_traces(cursor: Cursor) -> list[dict[str, Any]]:
    conn = connect_readonly(DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT rowid, trace_id, agent, model, prompt, response,
                   latency_ms, prompt_tokens, completion_tokens, confidence, created_at
            FROM llm_traces
            WHERE rowid > ?
            ORDER BY rowid ASC
            LIMIT ?
            """,
            (cursor.rowid, SSE_BATCH_LIMIT),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/logs")
async def stream_logs(request: Request):
    """GET /api/stream/logs

    Server-Sent Events stream:
    - event `heartbeat`: JSON heartbeat (no id)
    - event `log`: JSON decision/system log (id=rowid for resume)

    Connection recovery:
    - client reconnect will send `Last-Event-ID` header; we resume from that rowid.

    Safety:
    - read-only DB (mode=ro + query_only)
    - connection limit (SSE_MAX_CLIENTS)
    """

    try:
        await asyncio.wait_for(_client_sema.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="SSE capacity reached; try again later")

    cursor = _parse_last_event_id(request.headers.get("last-event-id"))

    async def event_gen() -> AsyncGenerator[Dict[str, str], None]:
        last_heartbeat = 0.0
        try:
            while True:
                if await request.is_disconnected():
                    break

                now = time.time()
                if now - last_heartbeat >= SSE_HEARTBEAT_SEC:
                    last_heartbeat = now
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps(
                            {
                                "type": "heartbeat",
                                "level": "INFO",
                                "ts": int(now * 1000),
                                "message": "sentinel_heartbeat",
                            },
                            ensure_ascii=False,
                        ),
                    }

                try:
                    rows = await asyncio.to_thread(_fetch_new_traces, cursor)
                    for r in rows:
                        rid = int(r.get("rowid") or 0)
                        if rid <= cursor.rowid:
                            continue
                        cursor.rowid = rid
                        yield {
                            "event": "log",
                            "id": str(cursor.rowid),
                            "data": json.dumps(_to_log_event(r), ensure_ascii=False),
                        }
                except Exception as e:
                    # Keep stream alive, but inform the client.
                    yield {
                        "event": "log",
                        "data": json.dumps(
                            {
                                "type": "system_warning",
                                "level": "WARN",
                                "ts": int(time.time() * 1000),
                                "message": f"log stream warning: {e}",
                            },
                            ensure_ascii=False,
                        ),
                    }

                await asyncio.sleep(SSE_POLL_INTERVAL_MS / 1000.0)
        finally:
            _client_sema.release()

    return EventSourceResponse(event_gen())
