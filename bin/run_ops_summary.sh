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
export OPS_SUMMARY_OUTPUT_DIR="${OPS_SUMMARY_OUTPUT_DIR:-$REPO/data/ops/ops_summary}"

echo "[run_ops_summary] DB_PATH=$DB_PATH"
exec "$PYTHON" "$REPO/tools/capture_ops_summary.py" --db-path "$DB_PATH" --output-dir "$OPS_SUMMARY_OUTPUT_DIR"
