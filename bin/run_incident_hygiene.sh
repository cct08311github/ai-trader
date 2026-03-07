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
export INCIDENT_HYGIENE_OUTPUT_DIR="${INCIDENT_HYGIENE_OUTPUT_DIR:-$REPO/data/ops/incident_hygiene}"

echo "[run_incident_hygiene] DB_PATH=$DB_PATH"
exec "$PYTHON" "$REPO/tools/run_incident_hygiene.py" --db-path "$DB_PATH" --output-dir "$INCIDENT_HYGIENE_OUTPUT_DIR"
