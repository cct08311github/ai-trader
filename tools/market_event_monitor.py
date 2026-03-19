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

# 事件累積冷卻期（小時）— 同類型事件觸發後，COOLDOWN_HOURS 內不重複觸發 PM Review
COOLDOWN_HOURS    = float(os.environ.get("MONITOR_COOLDOWN_HOURS",    "6.0"))   # hours

# 重大新聞閾值：關鍵字命中數超過此值才觸發
NEWS_KEYWORD_THRESHOLD = int(os.environ.get("MONITOR_NEWS_KEYWORD_THRESHOLD", "2"))

# ── 路徑常數 ────────────────────────────────────────────────────────────────

_HERE    = Path(__file__).resolve().parent
_PROJECT = _HERE.parent
_ROOT    = Path(os.getenv("OPENCLAW_ROOT_ENV", Path.home() / ".openclaw" / ".env")).parent

_ROOT_ENV    = _ROOT / ".env"
_PROJ_ENV    = _PROJECT / "frontend" / "backend" / ".env"
_DB_PATH     = _PROJECT / "data" / "sqlite" / "trades.db"
_STATE_FILE  = _PROJECT / "config" / "market_monitor_state.json"

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


# ── 事件累積冷卻機制 ─────────────────────────────────────────────────────────

def _read_monitor_state() -> dict:
    """讀取監控狀態檔（不存在時回傳空 dict）。"""
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("讀取監控狀態失敗: %s", exc)
    return {}


def _write_monitor_state(state: dict) -> None:
    """寫入監控狀態檔。"""
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("寫入監控狀態失敗: %s", exc)


def is_in_cooldown() -> bool:
    """若上次觸發距今不足 COOLDOWN_HOURS，回傳 True（冷卻中）。"""
    state = _read_monitor_state()
    last_ts = state.get("last_trigger_ts")
    if not last_ts:
        return False
    try:
        last_dt = datetime.fromisoformat(last_ts)
        elapsed = datetime.now(_TZ_TWN) - last_dt
        return elapsed.total_seconds() < COOLDOWN_HOURS * 3600
    except Exception:
        return False


def record_trigger() -> None:
    """記錄本次觸發時間戳（更新冷卻計時器）。"""
    state = _read_monitor_state()
    state["last_trigger_ts"] = datetime.now(_TZ_TWN).isoformat()
    _write_monitor_state(state)


def cooldown_remaining_minutes() -> float:
    """回傳冷卻剩餘分鐘數（0 表示不在冷卻期）。"""
    state = _read_monitor_state()
    last_ts = state.get("last_trigger_ts")
    if not last_ts:
        return 0.0
    try:
        last_dt = datetime.fromisoformat(last_ts)
        elapsed_sec = (datetime.now(_TZ_TWN) - last_dt).total_seconds()
        remaining = COOLDOWN_HOURS * 3600 - elapsed_sec
        return max(0.0, remaining / 60)
    except Exception:
        return 0.0


# ── 重大新聞監控 ─────────────────────────────────────────────────────────────

# 重大事件關鍵字（Fed 政策、AI 管制、地緣政治）
_NEWS_KEYWORDS: dict[str, list[str]] = {
    "FED_POLICY": [
        "federal reserve", "fed rate", "interest rate", "fomc", "powell",
        "rate hike", "rate cut", "聯準會", "升息", "降息", "利率決策",
    ],
    "AI_REGULATION": [
        "ai ban", "chip ban", "export control", "nvidia ban", "semiconductor ban",
        "ai restriction", "晶片禁令", "ai管制", "出口管制", "半導體禁令",
    ],
    "GEOPOLITICAL": [
        "taiwan strait", "china invasion", "war", "military conflict",
        "sanction", "embargo", "台海", "兩岸", "制裁", "戰爭",
    ],
}

# 免費 RSS 來源（不需 API key）
_RSS_FEEDS: list[tuple[str, str]] = [
    ("Fed Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC Markets", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
]


def fetch_news_headlines(max_items: int = 20) -> list[dict[str, str]]:
    """從免費 RSS feeds 抓取最新財經新聞標題。

    回傳 list of {'source', 'title', 'link'}。網路失敗時靜默回傳空清單。
    """
    import xml.etree.ElementTree as ET

    items: list[dict[str, str]] = []
    for source, url in _RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ai-trader/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for item in root.iter("item"):
                title_el = item.find("title")
                link_el  = item.find("link")
                title = (title_el.text or "").strip() if title_el is not None else ""
                link  = (link_el.text or "").strip() if link_el is not None else ""
                if title:
                    items.append({"source": source, "title": title, "link": link})
                if len(items) >= max_items:
                    break
        except Exception as exc:
            log.debug("RSS 抓取失敗 [%s]: %s", source, exc)
    return items[:max_items]


def check_news_alerts(
    headlines: list[dict[str, str]],
) -> list[dict[str, str]]:
    """掃描新聞標題，回傳命中重大關鍵字的警報清單。

    每條警報：{'type': 'NEWS_<CATEGORY>', 'title': ..., 'source': ..., 'keywords': [...]}
    """
    alerts: list[dict[str, str]] = []
    for item in headlines:
        text = item.get("title", "").lower()
        for category, keywords in _NEWS_KEYWORDS.items():
            hits = [kw for kw in keywords if kw.lower() in text]
            if len(hits) >= NEWS_KEYWORD_THRESHOLD:
                alerts.append({
                    "type": f"NEWS_{category}",
                    "title": item["title"],
                    "source": item.get("source", ""),
                    "keywords": hits,
                })
                break  # 每條新聞只歸類一次
    return alerts


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


def build_alert_message(
    alerts: list[dict[str, Any]],
    us_data: dict[str, Any],
    news_alerts: list[dict[str, str]] | None = None,
) -> str:
    now_str = datetime.now(_TZ_TWN).strftime("%Y-%m-%d %H:%M")
    lines = [f"⚠️ *市場事件警報* [{now_str}]", ""]

    for a in alerts:
        atype = a["type"]
        if atype == "NEWS":
            lines.append(f"📰 *重大新聞* [{a.get('source','')}] {a.get('title','')}")
        else:
            label    = a["label"]
            pct      = a["change_pct"]
            thresh   = a["threshold"]
            type_tag = {"US_MARKET": "🇺🇸 美股大盤", "VIX": "📊 VIX", "HOLDING": "📌 持倉"}.get(atype, atype)
            lines.append(f"{type_tag} *{label}* {_fmt_pct(pct)} （閾值 ±{thresh}%）")

    # 附加重大新聞警報
    if news_alerts:
        lines.append("")
        lines.append("*重大新聞事件*")
        for na in news_alerts[:3]:  # 最多顯示 3 條
            lines.append(f"📰 [{na.get('source','')}] {na.get('title','')}")

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

def main(dry_run: bool = False, force: bool = False) -> int:
    log.info(
        "市場事件監控啟動（US_THR=%.1f%%, VIX_THR=%.1f%%, HOLD_THR=%.1f%%, COOLDOWN=%.1fh）",
        US_THRESHOLD, VIX_THRESHOLD, HOLDING_THRESHOLD, COOLDOWN_HOURS,
    )

    # 1. 冷卻期檢查（緊急模式可略過）
    if not force and is_in_cooldown():
        mins = cooldown_remaining_minutes()
        log.info("⏳ 冷卻期中（剩餘 %.0f 分鐘），跳過本次觸發。使用 --force 可強制執行。", mins)
        return 3  # exit code 3 = 冷卻期跳過

    # 2. 抓取美股大盤與 VIX
    log.info("抓取美股大盤與 VIX...")
    try:
        us_data = fetch_us_market()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    log.info("S&P 500: %s, Nasdaq: %s, VIX: %s",
             us_data.get("S&P 500"), us_data.get("Nasdaq"), us_data.get("VIX"))

    # 3. 抓取持倉個股
    holdings = fetch_holdings()
    log.info("目前持倉: %s", holdings or "(無)")

    holding_changes: dict[str, float | None] = {}
    if holdings:
        log.info("抓取持倉個股漲跌...")
        holding_changes = fetch_holding_changes(holdings)
        for sym, pct in holding_changes.items():
            log.info("  %s: %s", sym, f"{pct:+.2f}%" if pct is not None else "N/A")

    # 4. 重大新聞掃描
    log.info("掃描重大新聞...")
    headlines = fetch_news_headlines()
    news_alerts = check_news_alerts(headlines)
    if news_alerts:
        for na in news_alerts:
            log.info("📰 新聞事件 [%s] %s (關鍵字: %s)", na["type"], na["title"], na["keywords"])

    # 5. 判斷市場價格事件
    alerts = check_alerts(us_data, holding_changes)

    if not alerts and not news_alerts:
        log.info("✅ 無事件觸發，市場狀況正常")
        print(f"[market-monitor] 正常 | S&P 500: {us_data.get('S&P 500')}% "
              f"| Nasdaq: {us_data.get('Nasdaq')}% | VIX: {us_data.get('VIX')}%")
        return 0

    # 6. 有警報 → 輸出摘要
    for a in alerts:
        print(f"[market-monitor] ⚠️  {a['type']} {a['label']}: {a['change_pct']:+.2f}% "
              f"（閾值 ±{a['threshold']}%）")
    for na in news_alerts:
        print(f"[market-monitor] 📰 {na['type']} [{na['source']}] {na['title']}")

    if dry_run:
        log.info("dry-run 模式：跳過 Telegram 和 PM Review 呼叫")
        return 1

    # 7. 發送 Telegram
    message = build_alert_message(alerts, us_data, news_alerts=news_alerts)
    send_telegram(message)

    # 8. 觸發 PM Review
    if AUTH_TOKEN:
        log.info("觸發緊急 PM Review...")
        trigger_pm_review()
    else:
        log.warning("AUTH_TOKEN 未設定，跳過 PM Review 觸發")

    # 9. 記錄本次觸發，重置冷卻計時器
    record_trigger()

    return 1  # exit code 1 = 有警報觸發（非錯誤，供 cron 日誌區分）


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Trader 市場事件監控")
    parser.add_argument("--dry-run", action="store_true", help="只輸出，不發送 Telegram")
    parser.add_argument("--force", action="store_true",
                        help="緊急模式：略過冷卻期，強制執行（手動緊急觸發）")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run, force=args.force))
