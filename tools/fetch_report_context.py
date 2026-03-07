from __future__ import annotations

import argparse
import json
import os
import sys

from openclaw.report_context_client import fetch_report_context


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch /api/reports/context from the local ai-trader API.")
    parser.add_argument("--base-url", default=os.environ.get("AI_TRADER_API_BASE_URL", "https://127.0.0.1:8080"))
    parser.add_argument("--token", default=os.environ.get("AUTH_TOKEN", ""))
    parser.add_argument("--type", dest="report_type", choices=("morning", "evening", "weekly"), default="morning")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for local self-signed certs.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.token:
        parser.error("--token is required (or set AUTH_TOKEN)")

    payload = fetch_report_context(
        base_url=args.base_url,
        token=args.token,
        report_type=args.report_type,
        timeout_sec=args.timeout,
        verify_tls=not args.insecure,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
