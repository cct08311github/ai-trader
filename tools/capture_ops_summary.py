#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = get_repo_root()
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.operator_jobs import run_ops_summary_job
from openclaw.path_utils import get_repo_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture AI Trader ops summary snapshot.")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/sqlite/trades.db"))
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("OPS_SUMMARY_OUTPUT_DIR", "data/ops/ops_summary"),
    )
    args = parser.parse_args()

    result = run_ops_summary_job(db_path=args.db_path, output_dir=args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"[ops-summary] wrote {result['output_path']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
