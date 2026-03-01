#!/bin/bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend
# Get absolute path to the venv
VENV_PYTHON="/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python"

# Ensure requirements are met (optional on every start, but safe)
# $VENV_PYTHON -m pip install -r requirements.txt > /dev/null 2>&1

export PYTHONPATH="/Users/openclaw/.openclaw/shared/projects/ai-trader/src:/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/backend"
export DB_PATH="/Users/openclaw/.openclaw/shared/projects/ai-trader/data/sqlite/trades.db"

# SSL certificates from agent-monitor-web
CERT_PATH="/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/cert.pem"
KEY_PATH="/Users/openclaw/.openclaw/shared/projects/agent-monitor-web/cert/key.pem"

if [ -f "$CERT_PATH" ] && [ -f "$KEY_PATH" ]; then
    echo "Using SSL certificates for HTTPS (Localhost only)"
    # IMPORTANT: Listen on 127.0.0.1 only to allow Tailscale to handle the public interface on 8080
    exec $VENV_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --ssl-certfile "$CERT_PATH" --ssl-keyfile "$KEY_PATH"
else
    echo "SSL certificates not found, falling back to HTTP (localhost only)"
    # Fallback: bind to localhost only for security
    exec $VENV_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8080
fi
