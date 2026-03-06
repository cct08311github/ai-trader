#!/bin/bash
set -euo pipefail

REPO="/Users/openclaw/.openclaw/shared/projects/ai-trader"
PYTHON="$REPO/bin/venv/bin/python"

if [ -f /Users/openclaw/.openclaw/.env ]; then
    set -a
    source /Users/openclaw/.openclaw/.env
    set +a
fi

if [ -f "$REPO/frontend/backend/.env" ]; then
    set -a
    source "$REPO/frontend/backend/.env"
    set +a
fi

export PYTHONPATH="${PYTHONPATH:-$REPO/src:$REPO/frontend/backend}"
export DB_PATH="${DB_PATH:-$REPO/data/sqlite/trades.db}"
export RECON_OUTPUT_DIR="${RECON_OUTPUT_DIR:-$REPO/data/ops/reconciliation}"
export RECON_BROKER_SOURCE="${RECON_BROKER_SOURCE:-shioaji}"

echo "[run_reconciliation] DB_PATH=$DB_PATH RECON_BROKER_SOURCE=$RECON_BROKER_SOURCE RECON_SIMULATION=${RECON_SIMULATION:-auto}"

ARGS=(--db-path "$DB_PATH" --output-dir "$RECON_OUTPUT_DIR" --broker-source "$RECON_BROKER_SOURCE")
if [ -n "${RECON_SIMULATION:-}" ]; then
    ARGS+=(--simulation "$RECON_SIMULATION")
fi

exec "$PYTHON" "$REPO/tools/run_reconciliation.py" "${ARGS[@]}"
