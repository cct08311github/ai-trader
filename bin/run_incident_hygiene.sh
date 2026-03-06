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
export INCIDENT_HYGIENE_OUTPUT_DIR="${INCIDENT_HYGIENE_OUTPUT_DIR:-$REPO/data/ops/incident_hygiene}"

echo "[run_incident_hygiene] DB_PATH=$DB_PATH"
exec "$PYTHON" "$REPO/tools/run_incident_hygiene.py" --db-path "$DB_PATH" --output-dir "$INCIDENT_HYGIENE_OUTPUT_DIR"
