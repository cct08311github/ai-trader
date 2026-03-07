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
export OPS_SUMMARY_OUTPUT_DIR="${OPS_SUMMARY_OUTPUT_DIR:-$REPO/data/ops/ops_summary}"

echo "[run_ops_summary] DB_PATH=$DB_PATH"
exec "$PYTHON" "$REPO/tools/capture_ops_summary.py" --db-path "$DB_PATH" --output-dir "$OPS_SUMMARY_OUTPUT_DIR"
