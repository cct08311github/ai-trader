#!/usr/bin/env python3
"""market_event_monitor.py — 市場事件監控腳本 [Issue #197]

每日盤前執行（建議 08:30 台北時間），檢查是否觸發下列事件條件：
  - 美股大盤：S&P 500 或 Nasdaq 前日收盤漲跌幅 > US_THRESHOLD（預設 3%）
  - VIX 波動：VIX 前日變動 > VIX_THRESHOLD（預設 20%）
  - 持倉警報：任一持倉個股前日漲跌幅 > HOLDING_THRESHOLD（預設 5%）

觸發條件成立時：
  1. 發送 Telegram 警報到 TELEGRAM_CHAT_ID
  2. 呼叫 AI Trader PM Review API（觸發緊急策略審查）

環境變數（從 frontend/backend/.env 或系統環境讀取）：
  AI_TRADER_API       — API base URL（預設 https://127.0.0.1:8080）
  AUTH_TOKEN          — Bearer token
  TELEGRAM_BOT_TOKEN  — Telegram Bot Token
  TELEGRAM_CHAT_ID    — 警報頻道 Chat ID（預設 -1003772422881）

使用方法：
  python3 tools/market_event_monitor.py
  python3 tools/market_event_monitor.py --dry-run   # 只輸出，不發送
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import yfinance as yf
except ImportError:
    yf = None

# ── 監控閾值 ────────────────────────────────────────────────────────────────

US_THRESHOLD      = float(os.environ.get("MONITOR_US_THRESHOLD",      "3.0"))   # %
VIX_THRESHOLD     = float(os.environ.get("MONITOR_VIX_THRESHOLD",     "20.0"))  # %
HOLDING_THRESHOLD = float(os.environ.get("MONITOR_HOLDING_THRESHOLD", "5.0"))   # %

# ── 路徑常數 ────────────────────────────────────────────────────────────────

_HERE    = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
_ROOT    = Path(os.getenv("OPENCLAW_ROOT_ENV", Path.home() / ".openclaw" / ".env")).parent

_ROOT_ENV  = _ROOT / ".env"
_PROJ_ENV  = _PROJECT / "frontend" / "backend" / ".env"
_DB_PATH   = _PROJECT / "data" / "sqlite" / "trades.db"

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[market-monitor] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ── TZ ──────────────────────────────────────────────────────────────────────

_TZ_TWN = timezone(timedelta(hours=8))


# ── 環境變數載入 ─────────────────────────────────────────────────────────────

def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip()


_load_dotenv(_ROOT_ENV)
_load_dotenv(_PROJ_ENV)

API_BASE           = os.environ.get("AI_TRADER_API", "https://127.0.0.1:8080")
AUTH_TOKEN         = os.environ.get("AUTH_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "-1003772422881")

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


# ── 資料抓取 ─────────────────────────────────────────────────────────────────

_US_SYMBOLS = {
    "S&P 500": "^GSPC",
    "Nasdaq":  "^IXIC",
    "Dow":     "^DJI",
}
_VIX_SYMBOL = "^VIX"


def _require_yfinance():
    if yf is None:
        raise RuntimeError("yfinance 未安裝。請執行: pip install yfinance")
    return yf


def _pct_change(symbol: str, label: str) -> float | None:
    """抓取單一 symbol 前日收盤漲跌幅（%）。回傳 None 表示資料不可用。"""
    try:
        ticker = _require_yfinance().Ticker(symbol)
        hist = ticker.history(period="5d")
        if hist.empty or len(hist) < 2:
            log.warning("無法取得 %s (%s) 歷史資料", label, symbol)
            return None
        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        if prev_close == 0:
            return None
        return round((last_close - prev_close) / prev_close * 100, 2)
    except Exception as exc:
        log.warning("取得 %s 資料失敗: %s", label, exc)
        return None


def fetch_us_market() -> dict[str, Any]:
    """抓取美股大盤及 VIX 前日漲跌幅。"""
    _require_yfinance()
    result: dict[str, Any] = {}
    for label, symbol in _US_SYMBOLS.items():
        result[label] = _pct_change(symbol, label)
    result["VIX"] = _pct_change(_VIX_SYMBOL, "VIX")
    return result


def fetch_holdings() -> list[str]:
    """從 SQLite positions 表取出現有持倉股票代碼（quantity > 0）。"""
    if not _DB_PATH.exists():
        log.warning("DB 不存在: %s", _DB_PATH)
        return []
    try:
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        cur = conn.execute(
            "SELECT symbol FROM positions WHERE quantity > 0"
        )
        rows = [row[0] for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        log.warning("讀取 positions 失敗: %s", exc)
        return []


def fetch_holding_changes(symbols: list[str]) -> dict[str, float | None]:
    """抓取台股持倉個股前日漲跌幅（%）。"""
    result: dict[str, float | None] = {}
    for sym in symbols:
        tw_sym = sym if sym.endswith(".TW") else f"{sym}.TW"
        result[sym] = _pct_change(tw_sym, sym)
    return result


# ── 閾值檢查 ─────────────────────────────────────────────────────────────────

def check_alerts(
    us_data: dict[str, Any],
    holding_changes: dict[str, float | None],
) -> list[dict[str, Any]]:
    """回傳觸發的警報清單，每項 {'type', 'label', 'change_pct', 'threshold'}。"""
    alerts: list[dict[str, Any]] = []

    # 美股大盤閾值
    for label in ("S&P 500", "Nasdaq", "Dow"):
        pct = us_data.get(label)
        if pct is not None and abs(pct) >= US_THRESHOLD:
            alerts.append({
                "type": "US_MARKET",
                "label": label,
                "change_pct": pct,
                "threshold": US_THRESHOLD,
            })

    # VIX 閾值
    vix_pct = us_data.get("VIX")
    if vix_pct is not None and abs(vix_pct) >= VIX_THRESHOLD:
        alerts.append({
            "type": "VIX",
            "label": "VIX",
            "change_pct": vix_pct,
            "threshold": VIX_THRESHOLD,
        })

    # 持倉個股閾值
    for sym, pct in holding_changes.items():
        if pct is not None and abs(pct) >= HOLDING_THRESHOLD:
            alerts.append({
                "type": "HOLDING",
                "label": sym,
                "change_pct": pct,
                "threshold": HOLDING_THRESHOLD,
            })

    return alerts


# ── Telegram 發送 ────────────────────────────────────────────────────────────

def _fmt_pct(pct: float) -> str:
    icon = "🔴" if pct < 0 else "🟢"
    return f"{icon} {pct:+.2f}%"


def build_alert_message(alerts: list[dict[str, Any]], us_data: dict[str, Any]) -> str:
    now_str = datetime.now(_TZ_TWN).strftime("%Y-%m-%d %H:%M")
    lines = [f"⚠️ *市場事件警報* [{now_str}]", ""]

    for a in alerts:
        label    = a["label"]
        pct      = a["change_pct"]
        thresh   = a["threshold"]
        atype    = a["type"]
        type_tag = {"US_MARKET": "🇺🇸 美股大盤", "VIX": "📊 VIX", "HOLDING": "📌 持倉"}[atype]
        lines.append(f"{type_tag} *{label}* {_fmt_pct(pct)} （閾值 ±{thresh}%）")

    lines += [
        "",
        "*大盤快照*",
        f"• S\\&P 500: {_fmt_pct(us_data['S&P 500']) if us_data.get('S&P 500') is not None else 'N/A'}",
        f"• Nasdaq:   {_fmt_pct(us_data['Nasdaq']) if us_data.get('Nasdaq') is not None else 'N/A'}",
        f"• VIX:      {_fmt_pct(us_data['VIX']) if us_data.get('VIX') is not None else 'N/A'}",
        "",
        "_已自動觸發緊急 PM Review_",
    ]
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN 未設定，跳過 Telegram 通知")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
    }).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                log.info("Telegram 警報已發送 (chat_id=%s)", TELEGRAM_CHAT_ID)
                return True
            log.warning("Telegram API 回傳 not ok: %s", result)
            return False
    except Exception as exc:
        log.error("Telegram 發送失敗: %s", exc)
        return False


# ── PM Review 觸發 ───────────────────────────────────────────────────────────

def trigger_pm_review() -> bool:
    url = f"{API_BASE}/api/pm/review"
    try:
        req = urllib.request.Request(
            url, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {AUTH_TOKEN}",
            },
            data=b"{}",
        )
        with urllib.request.urlopen(req, timeout=120, context=_ssl_ctx) as resp:
            result = json.loads(resp.read().decode())
            data = result.get("data", {})
            approved = data.get("approved", False)
            reason   = data.get("reason", "")
            conf     = data.get("confidence", 0)
            status   = "✅ 授權" if approved else "🚫 封鎖"
            log.info("PM Review: %s | 信心 %.0f%% | %s", status, conf * 100, reason)
            return True
    except Exception as exc:
        log.error("PM Review 呼叫失敗: %s", exc)
        return False


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> int:
    log.info("市場事件監控啟動（US_THR=%.1f%%, VIX_THR=%.1f%%, HOLD_THR=%.1f%%）",
             US_THRESHOLD, VIX_THRESHOLD, HOLDING_THRESHOLD)

    # 1. 抓取美股大盤與 VIX
    log.info("抓取美股大盤與 VIX...")
    try:
        us_data = fetch_us_market()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    log.info("S&P 500: %s, Nasdaq: %s, VIX: %s",
             us_data.get("S&P 500"), us_data.get("Nasdaq"), us_data.get("VIX"))

    # 2. 抓取持倉個股
    holdings = fetch_holdings()
    log.info("目前持倉: %s", holdings or "(無)")

    holding_changes: dict[str, float | None] = {}
    if holdings:
        log.info("抓取持倉個股漲跌...")
        holding_changes = fetch_holding_changes(holdings)
        for sym, pct in holding_changes.items():
            log.info("  %s: %s", sym, f"{pct:+.2f}%" if pct is not None else "N/A")

    # 3. 判斷是否觸發
    alerts = check_alerts(us_data, holding_changes)

    if not alerts:
        log.info("✅ 無事件觸發，市場狀況正常")
        # 輸出摘要供 cron agent 讀取
        print(f"[market-monitor] 正常 | S&P 500: {us_data.get('S&P 500')}% "
              f"| Nasdaq: {us_data.get('Nasdaq')}% | VIX: {us_data.get('VIX')}%")
        return 0

    # 4. 有警報 → 輸出摘要
    for a in alerts:
        print(f"[market-monitor] ⚠️  {a['type']} {a['label']}: {a['change_pct']:+.2f}% "
              f"（閾值 ±{a['threshold']}%）")

    if dry_run:
        log.info("dry-run 模式：跳過 Telegram 和 PM Review 呼叫")
        return 1

    # 5. 發送 Telegram
    message = build_alert_message(alerts, us_data)
    send_telegram(message)

    # 6. 觸發 PM Review
    if AUTH_TOKEN:
        log.info("觸發緊急 PM Review...")
        trigger_pm_review()
    else:
        log.warning("AUTH_TOKEN 未設定，跳過 PM Review 觸發")

    return 1  # exit code 1 = 有警報觸發（非錯誤，供 cron 日誌區分）


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Trader 市場事件監控")
    parser.add_argument("--dry-run", action="store_true", help="只輸出，不發送 Telegram")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
