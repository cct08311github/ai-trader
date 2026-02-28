#!/bin/bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend
# Get absolute path to the venv
VENV_PYTHON="/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python"

# Ensure requirements are met (optional on every start, but safe)
# $VENV_PYTHON -m pip install -r requirements.txt > /dev/null 2>&1

export PYTHONPATH="/Users/openclaw/.openclaw/shared/projects/ai-trader/src:/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend"
export DB_PATH="/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db"

# Run uvicorn via python
# Security: bind backend to localhost only; expose via Tailscale reverse-proxy/serve.
exec $VENV_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8080
