#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.path_utils import get_repo_root
from openclaw.position_quarantine import (
    apply_quarantine_plan,
    build_reconciliation_quarantine_plan,
    clear_quarantine_symbols,
    get_quarantine_status,
)

REPO_ROOT = get_repo_root()


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
    parser.add_argument("--clear", action="store_true", help="clear quarantine instead of building/applying plan")
    parser.add_argument("--symbols", default="", help="comma-separated symbols to clear; empty means clear all")
    args = parser.parse_args()

    conn = sqlite3.connect(str(args.db_path))
    conn.row_factory = sqlite3.Row
    try:
        if args.clear:
            symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
            plan = clear_quarantine_symbols(conn, symbols=symbols)
        else:
            report = _load_latest_report(Path(args.snapshot_path))
            plan = build_reconciliation_quarantine_plan(conn, report=report)
            if args.apply:
                plan = apply_quarantine_plan(conn, plan=plan)
            plan["quarantine_status"] = get_quarantine_status(conn)
    finally:
        conn.close()

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
