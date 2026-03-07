#!/bin/bash
# run_watcher.sh — 啟動 ai-trader-watcher 並載入憑證
#
# 對標 frontend/backend/run.sh 的憑證載入模式：
#   1. 載入全域 env（Gemini API key 等）
#   2. 載入 backend .env（SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY）
#   3. 設定 PYTHONPATH + DB_PATH
#   4. 啟動 ticker_watcher.py

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="$REPO/bin/venv/bin/python"

# 1. 全域 env（gemini 等共用金鑰）
OPENCLAW_ENV="${OPENCLAW_ROOT_ENV:-$HOME/.openclaw/.env}"
if [ -f "$OPENCLAW_ENV" ]; then
    set -a
    source "$OPENCLAW_ENV"
    set +a
fi

# 2. Backend .env（Shioaji 憑證、DB_PATH 等）
if [ -f "$REPO/frontend/backend/.env" ]; then
    set -a
    source "$REPO/frontend/backend/.env"
    set +a
fi

# 3. 確保 PYTHONPATH 和 DB_PATH（.env 中的值可覆蓋，這裡設 fallback）
export PYTHONPATH="${PYTHONPATH:-$REPO/src:$REPO/frontend/backend}"
export DB_PATH="${DB_PATH:-$REPO/data/sqlite/trades.db}"

echo "[run_watcher] Starting ai-trader-watcher"
echo "[run_watcher] SHIOAJI_API_KEY=${SHIOAJI_API_KEY:+SET} DB_PATH=$DB_PATH"

exec "$PYTHON" "$REPO/src/openclaw/ticker_watcher.py"
