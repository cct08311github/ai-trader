#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$REPO/bin/venv/bin/python"

OPENCLAW_ENV="${OPENCLAW_ROOT_ENV:-$HOME/.openclaw/.env}"
if [ -f "$OPENCLAW_ENV" ]; then
    set -a
    source "$OPENCLAW_ENV"
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
