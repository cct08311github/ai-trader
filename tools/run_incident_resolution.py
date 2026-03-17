#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = get_repo_root()
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.incident_resolution import list_open_incident_clusters, resolve_open_incidents
from openclaw.operator_remediation import list_operator_remediations
from openclaw.path_utils import get_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="List or resolve open incident clusters.")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/sqlite/trades.db"))
    parser.add_argument("--source", default="", help="incident source filter or resolve target")
    parser.add_argument("--code", default="", help="incident code filter or resolve target")
    parser.add_argument("--severity", default="", help="incident severity filter for listing")
    parser.add_argument("--fingerprint", default="", help="specific cluster fingerprint to resolve")
    parser.add_argument("--reason", default="", help="operator reason recorded in remediation log")
    parser.add_argument("--limit", type=int, default=20, help="max remediation history items to include")
    parser.add_argument("--action-type", default="", help="remediation history action_type filter")
    parser.add_argument("--target-ref", default="", help="remediation history target_ref substring filter")
    parser.add_argument("--apply", action="store_true", help="resolve the selected cluster")
    parser.add_argument("--summary-only", action="store_true", help="print only count summary instead of full payload")
    parser.add_argument("--jsonl", action="store_true", help="emit JSON Lines for easier shell processing")
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db_path))
    conn.row_factory = sqlite3.Row
    try:
        payload: dict[str, object] = {
            "open_incident_clusters": list_open_incident_clusters(
                conn,
                source=args.source or None,
                code=args.code or None,
                severity=args.severity or None,
            ),
            "remediation_history": list_operator_remediations(
                conn,
                limit=max(int(args.limit), 1),
                action_type=args.action_type or None,
                target_ref=args.target_ref or None,
            ),
        }
        if args.apply:
            if not args.source or not args.code:
                raise SystemExit("--apply requires --source and --code")
            payload["resolution"] = resolve_open_incidents(
                conn,
                source=args.source,
                code=args.code,
                fingerprint=args.fingerprint or None,
                reason=args.reason,
            )
            payload["open_incident_clusters"] = list_open_incident_clusters(
                conn,
                source=args.source or None,
                code=args.code or None,
                severity=args.severity or None,
            )
            payload["remediation_history"] = list_operator_remediations(
                conn,
                limit=max(int(args.limit), 1),
                action_type=args.action_type or None,
                target_ref=args.target_ref or None,
            )
    finally:
        conn.close()

    if args.summary_only:
        summary = {
            "open_incident_clusters": payload["open_incident_clusters"]["count"],
            "remediation_history": payload["remediation_history"]["count"],
        }
        if "resolution" in payload:
            summary["resolved_count"] = payload["resolution"]["resolved_count"]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.jsonl:
        for item in payload["open_incident_clusters"]["items"]:
            print(json.dumps({"type": "incident_cluster", **item}, ensure_ascii=False))
        for item in payload["remediation_history"]["items"]:
            print(json.dumps({"type": "remediation_action", **item}, ensure_ascii=False))
        if "resolution" in payload:
            print(json.dumps({"type": "resolution", **payload["resolution"]}, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
