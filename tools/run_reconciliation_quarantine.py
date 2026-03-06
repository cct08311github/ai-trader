#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.position_quarantine import apply_quarantine_plan, build_reconciliation_quarantine_plan


def _load_latest_report(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = payload.get("report")
    if not isinstance(report, dict):
        raise RuntimeError(f"latest reconciliation snapshot missing report: {path}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or apply reconciliation quarantine plan.")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/sqlite/trades.db"))
    parser.add_argument(
        "--snapshot-path",
        default=os.environ.get("RECONCILIATION_LATEST_PATH", "data/ops/reconciliation/latest.json"),
    )
    parser.add_argument("--apply", action="store_true", help="apply quarantine to eligible symbols")
    args = parser.parse_args()

    report = _load_latest_report(Path(args.snapshot_path))
    conn = sqlite3.connect(str(args.db_path))
    conn.row_factory = sqlite3.Row
    try:
        plan = build_reconciliation_quarantine_plan(conn, report=report)
        if args.apply:
            plan = apply_quarantine_plan(conn, plan=plan)
    finally:
        conn.close()

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
