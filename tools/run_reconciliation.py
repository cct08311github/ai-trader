#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "frontend" / "backend"))

from openclaw.operator_jobs import fetch_broker_snapshot, run_reconciliation_job
from openclaw.path_utils import get_repo_root

REPO_ROOT = get_repo_root()


def _parse_simulation(raw: str | None) -> bool | None:
    if raw is None or raw == "":
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid simulation flag: {raw}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run broker/local reconciliation.")
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/sqlite/trades.db"))
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("RECON_OUTPUT_DIR", "data/ops/reconciliation"),
    )
    parser.add_argument(
        "--broker-source",
        default=os.environ.get("RECON_BROKER_SOURCE", "shioaji"),
        choices=["shioaji", "mock"],
    )
    parser.add_argument(
        "--simulation",
        default=os.environ.get("RECON_SIMULATION"),
        help="true/false; omitted means read system_state.json through service defaults",
    )
    args = parser.parse_args()

    simulation = _parse_simulation(args.simulation)
    snapshot = fetch_broker_snapshot(source=args.broker_source, simulation=simulation)
    result = run_reconciliation_job(
        db_path=args.db_path,
        output_dir=args.output_dir,
        broker_positions=snapshot["positions"],
        broker_source=str(snapshot["source"] or args.broker_source),
        simulation=simulation,
        resolved_simulation=snapshot.get("resolved_simulation"),
        broker_accounts=list(snapshot.get("accounts") or []),
        system_state_path=os.environ.get("SYSTEM_STATE_PATH"),
    )
    print(
        json.dumps(
            {
                "broker_source": str(snapshot["source"] or args.broker_source),
                "requested_simulation": simulation,
                "resolved_simulation": snapshot.get("resolved_simulation"),
                "broker_accounts": snapshot.get("accounts") or [],
                "report": result["report"],
            },
            ensure_ascii=False,
        )
    )
    print(f"[reconciliation] wrote {result['output_path']}", file=sys.stderr)
    return 0 if result["report"].get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
