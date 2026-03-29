#!/bin/bash
# bin/run_backup.sh — SQLite 每日備份腳本 [Issue #279]
#
# 將 trades.db dump 壓縮至 data/backup/，保留最近 30 份。
# 環境變數（可 override）：
#   DB_PATH         — SQLite 路徑（預設 <repo>/data/sqlite/trades.db）
#   BACKUP_DIR      — 備份目錄（預設 <repo>/data/backup）
#   BACKUP_RETAIN   — 保留份數（預設 30）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

OPENCLAW_ENV="${OPENCLAW_ROOT_ENV:-$HOME/.openclaw/.env}"
if [ -f "$OPENCLAW_ENV" ]; then
    set -a
    source "$OPENCLAW_ENV"
    set +a
fi

_ORIG_DB_PATH="${DB_PATH:-}"
if [ -f "$REPO/frontend/backend/.env" ]; then
    set -a
    source "$REPO/frontend/backend/.env"
    set +a
fi
if [ -n "$_ORIG_DB_PATH" ]; then
    DB_PATH="$_ORIG_DB_PATH"
elif [ -z "${DB_PATH:-}" ]; then
    unset DB_PATH
fi

DB_PATH="${DB_PATH:-$REPO/data/sqlite/trades.db}"
BACKUP_DIR="${BACKUP_DIR:-$REPO/data/backup}"
BACKUP_RETAIN="${BACKUP_RETAIN:-30}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/trades_${TIMESTAMP}.sql.gz"

echo "[run_backup] DB_PATH=$DB_PATH BACKUP_DIR=$BACKUP_DIR retain=${BACKUP_RETAIN}"

# DB が存在しない場合はスキップ
if [ ! -f "$DB_PATH" ]; then
    echo "[run_backup] WARN: DB not found at $DB_PATH, skipping"
    exit 0
fi

mkdir -p "$BACKUP_DIR"

# dump + compress
sqlite3 "$DB_PATH" .dump | gzip > "$BACKUP_FILE"
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[run_backup] OK: $BACKUP_FILE ($SIZE)"

# 超過保留數量的舊備份刪除（最舊的先刪）
COUNT=$(ls -1 "$BACKUP_DIR"/trades_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
if [ "$COUNT" -gt "$BACKUP_RETAIN" ]; then
    EXCESS=$(( COUNT - BACKUP_RETAIN ))
    ls -1t "$BACKUP_DIR"/trades_*.sql.gz | tail -n "$EXCESS" | xargs rm -f
    echo "[run_backup] pruned $EXCESS old backup(s), keeping $BACKUP_RETAIN"
fi
