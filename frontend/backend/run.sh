#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
# Get absolute path to the venv
VENV_PYTHON="$REPO/bin/venv/bin/python"

# Ensure requirements are met (optional on every start, but safe)
# $VENV_PYTHON -m pip install -r requirements.txt > /dev/null 2>&1

# Load shared API keys from openclaw root .env (GEMINI_API_KEY etc.)
OPENCLAW_ENV="${OPENCLAW_ROOT_ENV:-$HOME/.openclaw/.env}"
if [ -f "$OPENCLAW_ENV" ]; then
    set -a
    source "$OPENCLAW_ENV"
    set +a
fi

export PYTHONPATH="${PYTHONPATH:-$REPO/src:$REPO/frontend/backend}"
export DB_PATH="${DB_PATH:-$REPO/data/sqlite/trades.db}"

# SSL certificates from agent-monitor-web
CERT_DIR="${OPENCLAW_CERT_DIR:-$(dirname "$REPO")/agent-monitor-web/cert}"
CERT_PATH="$CERT_DIR/cert.pem"
KEY_PATH="$CERT_DIR/key.pem"

if [ -f "$CERT_PATH" ] && [ -f "$KEY_PATH" ]; then
    echo "Using SSL certificates for HTTPS (Localhost only)"
    # IMPORTANT: Listen on 127.0.0.1 only to allow Tailscale to handle the public interface on 8080
    exec $VENV_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --ssl-certfile "$CERT_PATH" --ssl-keyfile "$KEY_PATH"
else
    echo "SSL certificates not found, falling back to HTTP (localhost only)"
    # Fallback: bind to localhost only for security
    exec $VENV_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8080
fi
