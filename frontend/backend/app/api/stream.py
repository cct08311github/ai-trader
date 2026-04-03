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


# ─── SSE /api/stream/health ─────────────────────────────────────────────────
# Design doc §3.3: "SSE /api/stream/health — 即時推送系統健康狀態變化"

HEALTH_POLL_SEC = max(3, _env_int("HEALTH_POLL_SEC", 5))


def _fetch_health_snapshot() -> Dict[str, Any]:
    """Build a lightweight health snapshot (mirrors /api/system/health)."""
    import psutil

    services: Dict[str, Any] = {
        "fastapi": {"status": "online", "latency_ms": None},
        "shioaji": {"status": "simulation", "latency_ms": None},
    }

    try:
        import time as _t
        conn = connect_readonly(DB_PATH)
        t0 = _t.monotonic()
        conn.execute("SELECT 1").fetchone()
        latency_ms = round((_t.monotonic() - t0) * 1000, 2)
        conn.close()
        services["sqlite"] = {"status": "online", "latency_ms": latency_ms}
    except Exception as e:
        services["sqlite"] = {"status": "offline", "latency_ms": None, "error": str(e)}

    resources: Dict[str, Any] = {}
    try:
        resources["cpu_percent"] = psutil.cpu_percent(interval=0.05)
        mem = psutil.virtual_memory()
        resources["memory_percent"] = mem.percent
        dsk = psutil.disk_usage("/")
        resources["disk_used_gb"] = round(dsk.used / (1024 ** 3), 1)
        resources["disk_total_gb"] = round(dsk.total / (1024 ** 3), 1)
    except Exception:
        resources = {"cpu_percent": 0, "memory_percent": 0, "disk_used_gb": 0, "disk_total_gb": 0}

    has_offline = any(
        v.get("status") == "offline" for v in services.values() if isinstance(v, dict)
    )
    cpu_high = resources.get("cpu_percent", 0) > 80
    overall = "critical" if has_offline else ("warning" if cpu_high else "ok")

    return {
        "services": services,
        "resources": resources,
        "overall": overall,
        "ts": int(time.time() * 1000),
    }


@router.get("/health")
async def stream_health(request: Request):
    """GET /api/stream/health — SSE, design doc §3.3.

    Pushes a `health` event every HEALTH_POLL_SEC seconds containing
    the full system health snapshot.  Frontend can use this instead of
    polling /api/system/health for real-time status indicators.
    """
    try:
        await asyncio.wait_for(_client_sema.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="SSE capacity reached")

    async def health_gen() -> AsyncGenerator[Dict[str, str], None]:
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
                        "data": json.dumps({"ts": int(now * 1000), "type": "heartbeat"}, ensure_ascii=False),
                    }

                try:
                    snapshot = await asyncio.to_thread(_fetch_health_snapshot)
                    yield {
                        "event": "health",
                        "data": json.dumps(snapshot, ensure_ascii=False),
                    }
                except Exception as e:
                    yield {
                        "event": "health",
                        "data": json.dumps(
                            {"overall": "error", "error": str(e), "ts": int(time.time() * 1000)},
                            ensure_ascii=False,
                        ),
                    }

                await asyncio.sleep(HEALTH_POLL_SEC)
        finally:
            _client_sema.release()

    return EventSourceResponse(health_gen())


# ─── SSE /api/stream/market-ticks ────────────────────────────────────────────
# Module 2D: Real-time market index SSE endpoint.
# Fetches indices in-process every 30 s and pushes `market_tick` events.

MARKET_TICK_INTERVAL_SEC = max(10, _env_int("MARKET_TICK_INTERVAL_SEC", 30))

# Separate semaphore: max 10 concurrent market-tick SSE clients.
_market_sema = asyncio.Semaphore(10)


def _fetch_market_indices() -> list[dict]:
    """Fetch latest index rows from research.db market_indices table.

    Returns a list of dicts suitable for JSON serialisation.
    Falls back to [] on any error so the SSE stream stays alive.
    """
    try:
        from app.db.research_db import RESEARCH_DB_PATH, connect_research, init_research_db  # noqa: PLC0415
        init_research_db(RESEARCH_DB_PATH)
        conn = connect_research(RESEARCH_DB_PATH)
        try:
            rows = conn.execute(
                """
                SELECT m.symbol, m.name, m.close_price, m.change_pct, m.trade_date
                FROM market_indices m
                INNER JOIN (
                    SELECT symbol, MAX(trade_date) AS max_date
                    FROM market_indices
                    GROUP BY symbol
                ) latest ON m.symbol = latest.symbol AND m.trade_date = latest.max_date
                ORDER BY m.symbol
                """
            ).fetchall()
            return [
                {
                    "symbol":      r["symbol"],
                    "name":        r["name"],
                    "close_price": r["close_price"],
                    "change_pct":  r["change_pct"],
                    "trade_date":  r["trade_date"],
                }
                for r in rows
            ]
        finally:
            conn.close()
    except Exception as exc:
        import logging as _log
        _log.getLogger(__name__).warning("market_indices fetch failed: %s", exc)
        return []


@router.get("/market-ticks")
async def stream_market_ticks(request: Request):
    """GET /api/stream/market-ticks — SSE, Module 2D.

    Pushes a ``market_tick`` event every MARKET_TICK_INTERVAL_SEC seconds
    (default 30 s) with the latest global index snapshot from research.db.

    Safety:
    - separate semaphore (_market_sema, max 10 clients)
    - in-process fetch, no cross-process IPC
    - read-only research.db access
    """
    try:
        await asyncio.wait_for(_market_sema.acquire(), timeout=0.1)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Market-tick SSE capacity reached")

    async def market_gen() -> AsyncGenerator[Dict[str, str], None]:
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
                            {"ts": int(now * 1000), "type": "heartbeat"},
                            ensure_ascii=False,
                        ),
                    }

                try:
                    indices = await asyncio.to_thread(_fetch_market_indices)
                    yield {
                        "event": "market_tick",
                        "data": json.dumps(
                            {
                                "ts":      int(time.time() * 1000),
                                "indices": indices,
                            },
                            ensure_ascii=False,
                        ),
                    }
                except Exception as exc:
                    yield {
                        "event": "market_tick",
                        "data": json.dumps(
                            {
                                "ts":    int(time.time() * 1000),
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                    }

                await asyncio.sleep(MARKET_TICK_INTERVAL_SEC)
        finally:
            _market_sema.release()

    return EventSourceResponse(market_gen())

