"""SSE smoke / light load test (no extra deps).

Usage:
  python3 scripts/sse_smoke_test.py --url http://localhost:8080/api/stream/logs --clients 20 --seconds 10

This script opens N SSE connections and counts received events.
"""

from __future__ import annotations

import argparse
import threading
import time
import urllib.request


def run_client(url: str, seconds: float, results: dict, idx: int):
    end = time.time() + seconds
    events = 0
    try:
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            buf_event = {}
            while time.time() < end:
                line = resp.readline()
                if not line:
                    break
                line = line.decode("utf-8", errors="ignore").strip("\r\n")
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    buf_event["event"] = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    buf_event.setdefault("data", "")
                    buf_event["data"] += line[len("data:") :].strip()
                elif line.startswith("id:"):
                    buf_event["id"] = line[len("id:") :].strip()
                elif line == "":
                    if buf_event:
                        events += 1
                        buf_event = {}
    except Exception as e:
        results[idx] = (events, str(e))
        return

    results[idx] = (events, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--clients", type=int, default=10)
    ap.add_argument("--seconds", type=float, default=10)
    args = ap.parse_args()

    results: dict[int, tuple[int, str | None]] = {}
    threads = []

    t0 = time.time()
    for i in range(max(1, args.clients)):
        th = threading.Thread(target=run_client, args=(args.url, args.seconds, results, i), daemon=True)
        th.start()
        threads.append(th)

    for th in threads:
        th.join()

    dt = time.time() - t0
    ok = sum(1 for _, err in results.values() if err is None)
    total_events = sum(n for n, _ in results.values())
    errs = [(i, err) for i, (n, err) in results.items() if err]

    print(f"clients={args.clients} seconds={args.seconds} elapsed={dt:.2f}s ok={ok}/{args.clients} total_events={total_events}")
    if errs:
        print("errors (first 5):")
        for i, err in errs[:5]:
            print(f"  client#{i}: {err}")


if __name__ == "__main__":
    main()
