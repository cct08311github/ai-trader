#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.operator_jobs import run_incident_hygiene_job


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve duplicate unresolved incidents.")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/sqlite/trades.db"))
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("INCIDENT_HYGIENE_OUTPUT_DIR", "data/ops/incident_hygiene"),
    )
    args = parser.parse_args()

    result = run_incident_hygiene_job(db_path=args.db_path, output_dir=args.output_dir)
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"[incident-hygiene] wrote {result['output_path']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
