#!/usr/bin/env python3
"""stress_test_sse.py — SSE throughput stress test for ai-trader dashboard.

Emits synthetic SSE events at configurable rates to test frontend throttling
(rAF batching in LogTerminal, rAF throttle in QuotePanel, debounced refresh
in Strategy page).

Two modes:
  1. inject — Writes rows directly into trades.db so the /api/stream/logs
     endpoint picks them up via its polling loop.
  2. standalone — Runs a local SSE server that emits events at the target
     rate. Point the frontend at this server to test pure consumer throughput.

Usage:
  # Inject mode (default) — writes to DB, real endpoint serves events
  python3 tools/stress_test_sse.py inject --rate 200 --seconds 30

  # Standalone SSE server — emits synthetic events on port 9090
  python3 tools/stress_test_sse.py standalone --rate 200 --seconds 60 --port 9090

  # Consumer mode — connects to a running SSE endpoint and measures throughput
  python3 tools/stress_test_sse.py consume --url https://127.0.0.1:8080/api/stream/logs --seconds 30

Environment:
  AUTH_TOKEN — Bearer token for consume mode (reads from .env if not set)
  DB_PATH    — Override trades.db path for inject mode
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import ssl
import sys
import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── .env loader ───────────────────────────────────────────────────────────────

_ROOT_ENV = Path(os.getenv("OPENCLAW_ROOT_ENV", Path.home() / ".openclaw" / ".env"))
_PROJ_ENV = Path(__file__).resolve().parent.parent / "frontend" / "backend" / ".env"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip()


_load_dotenv(_ROOT_ENV)
_load_dotenv(_PROJ_ENV)

# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "sqlite" / "trades.db"


def _get_db_path() -> str:
    return os.environ.get("DB_PATH", str(_DEFAULT_DB))


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ── Inject mode ──────────────────────────────────────────────────────────────

def _ensure_llm_traces_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT PRIMARY KEY,
            model TEXT,
            prompt TEXT,
            response TEXT,
            token_count INTEGER,
            latency_ms REAL,
            created_at INTEGER NOT NULL,
            shadow_mode INTEGER DEFAULT 0
        )
    """)
    conn.commit()


def cmd_inject(args: argparse.Namespace) -> None:
    """Write synthetic llm_traces rows to trigger SSE log polling."""
    db_path = _get_db_path()
    print(f"[inject] DB: {db_path}")
    print(f"[inject] Rate: {args.rate} events/sec for {args.seconds}s")

    conn = sqlite3.connect(db_path)
    _ensure_llm_traces_table(conn)

    interval = 1.0 / args.rate
    total = 0
    t0 = time.time()
    deadline = t0 + args.seconds

    try:
        while time.time() < deadline:
            batch_start = time.time()
            batch_size = max(1, min(args.rate // 10, 50))

            for i in range(batch_size):
                now_ms = int(time.time() * 1000)
                trace_id = f"stress_{now_ms}_{total}"
                conn.execute(
                    """INSERT INTO llm_traces
                       (trace_id, model, prompt, response, token_count, latency_ms, created_at, shadow_mode)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (trace_id, "stress-test", f"stress prompt {total}",
                     f"stress response {total}", 10, 5.0, now_ms, 1),
                )
                total += 1

            conn.commit()

            elapsed_batch = time.time() - batch_start
            expected_batch = batch_size * interval
            if elapsed_batch < expected_batch:
                time.sleep(expected_batch - elapsed_batch)

    except KeyboardInterrupt:
        pass
    finally:
        dt = time.time() - t0
        conn.close()
        print(f"[inject] Done: {total} rows in {dt:.1f}s ({total / max(dt, 0.001):.0f} rows/sec)")
        print(f"[inject] Cleanup: DELETE FROM llm_traces WHERE model='stress-test'")


# ── Standalone SSE server ────────────────────────────────────────────────────

class SSEHandler(BaseHTTPRequestHandler):
    rate: int = 200
    seconds: float = 60

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        interval = 1.0 / self.rate
        deadline = time.time() + self.seconds
        seq = 0

        try:
            while time.time() < deadline:
                t = time.time()
                payload = json.dumps({
                    "type": "log",
                    "ts": _now_iso(),
                    "level": "INFO",
                    "source": "stress_test",
                    "message": f"Synthetic event #{seq}",
                    "seq": seq,
                })
                self.wfile.write(f"id: {seq}\nevent: log\ndata: {payload}\n\n".encode())
                self.wfile.flush()
                seq += 1

                elapsed = time.time() - t
                if elapsed < interval:
                    time.sleep(interval - elapsed)

            # Final summary event
            summary = json.dumps({"type": "summary", "total_events": seq, "rate": self.rate})
            self.wfile.write(f"event: summary\ndata: {summary}\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

        print(f"[standalone] Client disconnected after {seq} events")

    def log_message(self, format, *args):
        pass  # Suppress request logs


def cmd_standalone(args: argparse.Namespace) -> None:
    """Run a standalone SSE server emitting at target rate."""
    SSEHandler.rate = args.rate
    SSEHandler.seconds = args.seconds

    server = HTTPServer(("0.0.0.0", args.port), SSEHandler)
    print(f"[standalone] SSE server on :{args.port} — {args.rate} events/sec for {args.seconds}s")
    print(f"[standalone] Connect: curl -N http://localhost:{args.port}/")
    print(f"[standalone] Ctrl-C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n[standalone] Stopped")


# ── Consumer mode ────────────────────────────────────────────────────────────

def cmd_consume(args: argparse.Namespace) -> None:
    """Connect to a running SSE endpoint and measure throughput."""
    token = os.environ.get("AUTH_TOKEN", "")
    url = args.url

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if "?" in url:
        url += f"&token={token}"
    else:
        url += f"?token={token}"

    print(f"[consume] Connecting to {args.url}")
    print(f"[consume] Duration: {args.seconds}s")

    req = urllib.request.Request(url, headers=headers)
    events = 0
    heartbeats = 0
    bytes_received = 0
    t0 = time.time()
    deadline = t0 + args.seconds

    try:
        with urllib.request.urlopen(req, timeout=args.seconds + 5, context=ssl_ctx) as resp:
            buf = {}
            while time.time() < deadline:
                line = resp.readline()
                if not line:
                    break
                bytes_received += len(line)
                line = line.decode("utf-8", errors="ignore").strip("\r\n")

                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    buf["event"] = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    buf.setdefault("data", "")
                    buf["data"] += line[len("data:"):].strip()
                elif line == "":
                    if buf:
                        if buf.get("event") == "heartbeat":
                            heartbeats += 1
                        else:
                            events += 1
                        buf = {}
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[consume] Error: {e}", file=sys.stderr)

    dt = time.time() - t0
    print(f"\n[consume] Results:")
    print(f"  Duration:    {dt:.1f}s")
    print(f"  Events:      {events}")
    print(f"  Heartbeats:  {heartbeats}")
    print(f"  Throughput:  {events / max(dt, 0.001):.1f} events/sec")
    print(f"  Bandwidth:   {bytes_received / 1024:.1f} KB ({bytes_received / max(dt, 0.001) / 1024:.1f} KB/s)")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SSE throughput stress test for ai-trader dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Inject 200 events/sec into DB for 30s
  python3 tools/stress_test_sse.py inject --rate 200 --seconds 30

  # Run standalone SSE server on port 9090
  python3 tools/stress_test_sse.py standalone --rate 200 --seconds 60 --port 9090

  # Consume from running API and measure throughput
  python3 tools/stress_test_sse.py consume --url https://127.0.0.1:8080/api/stream/logs --seconds 30
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # inject
    p_inject = sub.add_parser("inject", help="Write synthetic rows to trades.db")
    p_inject.add_argument("--rate", type=int, default=200, help="Target events/sec (default: 200)")
    p_inject.add_argument("--seconds", type=float, default=30, help="Duration in seconds (default: 30)")

    # standalone
    p_standalone = sub.add_parser("standalone", help="Run standalone SSE emitter server")
    p_standalone.add_argument("--rate", type=int, default=200, help="Target events/sec (default: 200)")
    p_standalone.add_argument("--seconds", type=float, default=60, help="Duration per client (default: 60)")
    p_standalone.add_argument("--port", type=int, default=9090, help="Server port (default: 9090)")

    # consume
    p_consume = sub.add_parser("consume", help="Connect to SSE endpoint and measure throughput")
    p_consume.add_argument("--url", required=True, help="SSE endpoint URL")
    p_consume.add_argument("--seconds", type=float, default=30, help="Duration in seconds (default: 30)")

    args = parser.parse_args()

    if args.command == "inject":
        cmd_inject(args)
    elif args.command == "standalone":
        cmd_standalone(args)
    elif args.command == "consume":
        cmd_consume(args)


if __name__ == "__main__":
    main()
