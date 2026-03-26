"""market_data_fetcher.py — TWSE 盤後公開資料抓取工具

每交易日 EOD 後（由 eod_analysis.py 呼叫）從 TWSE 公開 API 抓取：
  - 三大法人買賣超（T86）
  - 融資借券餘額（MI_MARGN）

資料寫入：
  eod_institution_flows (trade_date, symbol, name, foreign_net, trust_net, dealer_net, total_net)
  eod_margin_data       (trade_date, symbol, name, margin_balance, short_balance)

使用 urllib.request（stdlib，無額外依賴）。
"""
from __future__ import annotations

import datetime
import json
import logging
import sqlite3
import ssl
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

# TWSE 憑證有問題（Missing Subject Key Identifier），需停用 SSL 驗證
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

log = logging.getLogger(__name__)

# ── TWSE API URLs ────────────────────────────────────────────────────────────

_T86_URL = (
    "https://www.twse.com.tw/rwd/zh/fund/T86"
    "?response=json&date={date}&selectType=ALLBUT0999"
)
_MARGN_URL = (
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
    "?response=json&date={date}&selectType=ALL"
)

# HTTP request timeout (seconds)
_TIMEOUT = 20

# ── DB schema ────────────────────────────────────────────────────────────────

_CREATE_INSTITUTION_FLOWS = """
CREATE TABLE IF NOT EXISTS eod_institution_flows (
    trade_date  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    name        TEXT,
    foreign_net REAL,
    trust_net   REAL,
    dealer_net  REAL,
    total_net   REAL,
    PRIMARY KEY (trade_date, symbol)
)
"""

_CREATE_MARGIN_DATA = """
CREATE TABLE IF NOT EXISTS eod_margin_data (
    trade_date     TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    name           TEXT,
    margin_balance REAL,
    short_balance  REAL,
    PRIMARY KEY (trade_date, symbol)
)
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_api_date(trade_date: str) -> str:
    """'2026-03-03' → '20260303'"""
    return trade_date.replace("-", "")


def _parse_num(s: Any) -> Optional[float]:
    """Parse TWSE number string '12,345' → 12345.0; returns None on failure."""
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _fetch_json(url: str, _redirects: int = 5) -> dict:
    """Fetch JSON from TWSE API; follows 307/308 redirects that urllib skips."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
            raw = resp.read()
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code in (307, 308) and _redirects > 0:
            location = e.headers.get("Location")
            if location:
                return _fetch_json(location, _redirects - 1)
        raise


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create eod_institution_flows and eod_margin_data tables if not exists."""
    conn.execute(_CREATE_INSTITUTION_FLOWS)
    conn.execute(_CREATE_MARGIN_DATA)
    conn.commit()


# ── Institution Flows (T86) ──────────────────────────────────────────────────

def fetch_institution_flows(trade_date: str) -> List[Dict]:
    """
    Fetch 三大法人買賣超 from TWSE T86 API for *trade_date* ('YYYY-MM-DD').

    Returns list of dicts:
      {symbol, name, foreign_net, trust_net, dealer_net, total_net}

    Returns empty list if trade_date is non-trading or API is unavailable.
    """
    url = _T86_URL.format(date=_to_api_date(trade_date))
    try:
        data = _fetch_json(url)
    except Exception as exc:
        log.warning("[market_data_fetcher] T86 fetch failed: %s", exc)
        return []

    if data.get("stat") in ("no data", "很抱歉，沒有符合條件的資料！") or data.get("status") == "no data":
        log.info("[market_data_fetcher] T86 no data for %s (non-trading day?)", trade_date)
        return []

    rows = data.get("data") or []
    if not rows:
        log.info("[market_data_fetcher] T86 empty data for %s", trade_date)
        return []

    result = []
    for row in rows:
        if len(row) < 16:
            continue
        symbol = str(row[0]).strip()
        # skip summary / total rows (non-numeric symbol codes)
        if not symbol or not symbol[:4].isdigit():
            continue
        result.append({
            "symbol": symbol,
            "name": str(row[1]).strip(),
            "foreign_net": _parse_num(row[8]),   # 外陸資+外資自營商 合計
            "trust_net":   _parse_num(row[11]),  # 投信
            "dealer_net":  _parse_num(row[14]),  # 自營商
            "total_net":   _parse_num(row[15]),  # 三大法人合計
        })
    log.info("[market_data_fetcher] T86 fetched %d records for %s", len(result), trade_date)
    return result


def save_institution_flows(
    conn: sqlite3.Connection,
    trade_date: str,
    rows: List[Dict],
) -> int:
    """Upsert institution flow rows. Returns number of rows written."""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO eod_institution_flows
        (trade_date, symbol, name, foreign_net, trust_net, dealer_net, total_net)
        VALUES (:trade_date, :symbol, :name, :foreign_net, :trust_net, :dealer_net, :total_net)
        """,
        [{"trade_date": trade_date, **r} for r in rows],
    )
    conn.commit()
    return len(rows)


# ── Margin Data (MI_MARGN) ───────────────────────────────────────────────────

def fetch_margin_data(trade_date: str) -> List[Dict]:
    """
    Fetch 融資借券餘額 from TWSE MI_MARGN API for *trade_date* ('YYYY-MM-DD').

    Returns list of dicts:
      {symbol, name, margin_balance, short_balance}

    Returns empty list if trade_date is non-trading or API is unavailable.
    """
    url = _MARGN_URL.format(date=_to_api_date(trade_date))
    try:
        data = _fetch_json(url)
    except Exception as exc:
        log.warning("[market_data_fetcher] MI_MARGN fetch failed: %s", exc)
        return []

    if data.get("stat") in ("no data", "很抱歉，沒有符合條件的資料！") or data.get("status") == "no data":
        log.info("[market_data_fetcher] MI_MARGN no data for %s", trade_date)
        return []

    # MI_MARGN returns {"tables": [summary_table, detail_table]}
    # table[1] = 融資融券彙總, first field is "代號" (stock code)
    tables = data.get("tables") or []
    detail_table = next((t for t in tables if t.get("fields", [""])[0] == "代號"), None)
    rows = detail_table.get("data", []) if detail_table else data.get("data") or []
    if not rows:
        log.info("[market_data_fetcher] MI_MARGN empty data for %s", trade_date)
        return []

    result = []
    for row in rows:
        if len(row) < 13:
            continue
        symbol = str(row[0]).strip()
        if not symbol or not symbol[:4].isdigit():
            continue
        result.append({
            "symbol": symbol,
            "name": str(row[1]).strip(),
            "margin_balance": _parse_num(row[6]),   # 融資今日餘額（張）
            "short_balance":  _parse_num(row[12]),  # 融券今日餘額（張）
        })
    log.info("[market_data_fetcher] MI_MARGN fetched %d records for %s", len(result), trade_date)
    return result


def save_margin_data(
    conn: sqlite3.Connection,
    trade_date: str,
    rows: List[Dict],
) -> int:
    """Upsert margin data rows. Returns number of rows written."""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO eod_margin_data
        (trade_date, symbol, name, margin_balance, short_balance)
        VALUES (:trade_date, :symbol, :name, :margin_balance, :short_balance)
        """,
        [{"trade_date": trade_date, **r} for r in rows],
    )
    conn.commit()
    return len(rows)


# ── Yahoo Finance fallback ────────────────────────────────────────────────────

_YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.{suffix}"
    "?interval=1d&range=5d"
)


def _get_symbol_markets(
    conn: sqlite3.Connection,
    symbols: List[str],
) -> Dict[str, str]:
    """Best-effort lookup of each symbol's market from existing eod_prices rows."""
    unique_symbols = sorted({str(sym).upper() for sym in symbols if sym})
    if not unique_symbols:
        return {}

    placeholders = ",".join("?" for _ in unique_symbols)
    rows = conn.execute(
        f"""
        SELECT symbol, market
        FROM eod_prices
        WHERE symbol IN ({placeholders})
        ORDER BY trade_date DESC
        """,
        unique_symbols,
    ).fetchall()

    result: Dict[str, str] = {}
    for symbol, market in rows:
        result.setdefault(str(symbol).upper(), str(market))
    return result


def fetch_ohlcv_yahoo(
    symbols: List[str],
    market_by_symbol: Optional[Dict[str, str]] = None,
    sleep_sec: float = 1.0,
) -> Dict[str, List[Dict]]:
    """
    Fetch recent OHLCV from Yahoo Finance as fallback when TWSE API is unavailable.

    Returns {symbol: [{trade_date, open, high, low, close, volume}, ...]}
    """
    result: Dict[str, List[Dict]] = {}
    for sym in symbols:
        market = (market_by_symbol or {}).get(str(sym).upper(), "TWSE")
        suffix = "TWO" if market == "TPEx" else "TW"
        url = _YAHOO_CHART_URL.format(symbol=sym, suffix=suffix)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        })
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
                data = json.loads(resp.read())
            chart = data["chart"]["result"][0]
            timestamps = chart.get("timestamp", [])
            quotes = chart["indicators"]["quote"][0]
            rows = []
            for i, ts in enumerate(timestamps):
                dt = datetime.datetime.fromtimestamp(
                    ts, tz=datetime.timezone(datetime.timedelta(hours=8)),
                )
                c = quotes["close"][i]
                if c is None:
                    continue
                rows.append({
                    "trade_date": dt.strftime("%Y-%m-%d"),
                    "open": quotes["open"][i],
                    "high": quotes["high"][i],
                    "low": quotes["low"][i],
                    "close": c,
                    "volume": quotes["volume"][i],
                })
            result[sym] = rows
        except Exception as exc:
            log.warning("[market_data_fetcher] Yahoo fetch failed %s: %s", sym, exc)
            result[sym] = []
        time.sleep(sleep_sec)
    return result


# ── Orchestrator ─────────────────────────────────────────────────────────────

_STOCK_DAY_URL = (
    "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
    "?response=json&date={date}&stockNo={symbol}"
)


def fetch_ohlcv_month(symbol: str, year: int, month: int) -> List[Dict]:
    """
    從 TWSE STOCK_DAY API 抓取指定月份的個股日線 OHLCV。

    Returns list of dicts: {trade_date, open, high, low, close, volume}
    """
    url = _STOCK_DAY_URL.format(
        date=f"{year}{month:02d}01",
        symbol=symbol.upper(),
    )
    try:
        data = _fetch_json(url)
    except Exception as exc:
        log.warning("[market_data_fetcher] STOCK_DAY fetch failed %s %04d-%02d: %s", symbol, year, month, exc)
        return []

    if data.get("stat") not in ("OK", "ok"):
        return []

    result = []
    for row in data.get("data", []):
        if len(row) < 7:
            continue
        # 日期格式：民國 "115/03/02" → 西元
        try:
            parts = str(row[0]).strip().split("/")
            roc_year = int(parts[0])
            td = f"{roc_year + 1911}-{parts[1]}-{parts[2]}"
        except Exception:
            continue
        result.append({
            "trade_date": td,
            "open":   _parse_num(row[3]),
            "high":   _parse_num(row[4]),
            "low":    _parse_num(row[5]),
            "close":  _parse_num(row[6]),
            "volume": _parse_num(row[1]),
        })
    return result


def backfill_ohlcv(
    conn: sqlite3.Connection,
    symbols: List[str],
    months: int = 6,
    sleep_sec: float = 0.8,
) -> Dict[str, int]:
    """
    回填 eod_prices 歷史 OHLCV。

    對 *symbols* 中每支股票抓取最近 *months* 個月資料並寫入 eod_prices。
    每次 API 呼叫後 sleep *sleep_sec* 秒避免觸發 TWSE rate limit。

    Returns {symbol: rows_written}
    """
    today = datetime.date.today()
    # 產生需要抓取的 (year, month) 清單，從最舊到最新
    months_list: List[tuple] = []
    for delta in range(months - 1, -1, -1):
        d = datetime.date(today.year, today.month, 1) - datetime.timedelta(days=delta * 30)
        months_list.append((d.year, d.month))
    # 去重複（前後跨月相差 <30 天時可能重複）
    seen: set = set()
    unique_months = []
    for ym in months_list:
        if ym not in seen:
            seen.add(ym)
            unique_months.append(ym)

    result: Dict[str, int] = {}
    for sym in symbols:
        total = 0
        for year, month in unique_months:
            rows = fetch_ohlcv_month(sym, year, month)
            if rows:
                conn.executemany(
                    """
                    INSERT OR REPLACE INTO eod_prices
                        (trade_date, market, symbol, name, open, high, low, close, volume,
                         source_url, ingested_at)
                    VALUES
                        (:trade_date, 'TWSE', :symbol, NULL, :open, :high, :low, :close, :volume,
                         'TWSE/STOCK_DAY', datetime('now'))
                    """,
                    [{"symbol": sym.upper(), **r} for r in rows],
                )
                conn.commit()
                total += len(rows)
            time.sleep(sleep_sec)
        log.info("[market_data_fetcher] backfill %s: %d rows", sym, total)
        result[sym] = total
    return result


def run_daily_fetch(
    trade_date: str,
    conn: sqlite3.Connection,
    ohlcv_symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Fetch all market data for *trade_date* and save to DB.

    Each data source is fetched independently — one failure does NOT prevent
    the others from completing.

    If *ohlcv_symbols* is provided, also fetches OHLCV close prices for those
    symbols. Tries TWSE first; falls back to Yahoo Finance on failure.

    Returns dict: {institution_flows: N, margin_data: M, ohlcv: K}
    """
    ensure_schema(conn)
    result: Dict[str, Any] = {
        "institution_flows": 0, "margin_data": 0, "ohlcv": 0, "errors": [],
    }

    # Source 1: Institution flows (T86) — independent error isolation
    try:
        institution_rows = fetch_institution_flows(trade_date)
        result["institution_flows"] = save_institution_flows(conn, trade_date, institution_rows)
    except Exception as exc:
        log.error("[market_data_fetcher] institution save failed: %s", exc, exc_info=True)
        result["errors"].append(f"institution: {exc}")

    # Polite delay between requests (TWSE rate-limits aggressive crawlers)
    time.sleep(1)

    # Source 2: Margin data (MI_MARGN) — independent error isolation
    try:
        margin_rows = fetch_margin_data(trade_date)
        result["margin_data"] = save_margin_data(conn, trade_date, margin_rows)
    except Exception as exc:
        log.error("[market_data_fetcher] margin save failed: %s", exc, exc_info=True)
        result["errors"].append(f"margin: {exc}")

    # Source 3: OHLCV close prices — TWSE first, Yahoo Finance fallback
    if ohlcv_symbols:
        time.sleep(1)
        ohlcv_count = 0
        twse_failed_symbols: List[str] = []
        market_by_symbol = _get_symbol_markets(conn, ohlcv_symbols)
        today = datetime.date.today()

        # Try TWSE STOCK_DAY first (current month only)
        for sym in ohlcv_symbols:
            market = market_by_symbol.get(str(sym).upper(), "TWSE")
            if market == "TPEx":
                twse_failed_symbols.append(sym)
                continue
            try:
                rows = fetch_ohlcv_month(sym, today.year, today.month)
                if rows:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO eod_prices
                            (trade_date, market, symbol, name, open, high, low, close, volume,
                             source_url, ingested_at)
                        VALUES
                            (:trade_date, 'TWSE', :symbol, NULL, :open, :high, :low, :close, :volume,
                             'TWSE/STOCK_DAY', datetime('now'))
                        """,
                        [{"symbol": sym.upper(), **r} for r in rows],
                    )
                    conn.commit()
                    ohlcv_count += len(rows)
                else:
                    twse_failed_symbols.append(sym)
            except Exception:
                twse_failed_symbols.append(sym)
            time.sleep(3)  # Conservative delay — one request per 3 seconds

        # Fallback to Yahoo Finance for symbols that TWSE failed
        if twse_failed_symbols:
            log.info(
                "[market_data_fetcher] TWSE failed for %d symbols, trying Yahoo Finance",
                len(twse_failed_symbols),
            )
            yahoo_data = fetch_ohlcv_yahoo(
                twse_failed_symbols,
                market_by_symbol=market_by_symbol,
            )
            for sym, rows in yahoo_data.items():
                if rows:
                    market = market_by_symbol.get(str(sym).upper(), "TWSE")
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO eod_prices
                            (trade_date, market, symbol, name, open, high, low, close, volume,
                             source_url, ingested_at)
                        VALUES
                            (:trade_date, :market, :symbol, NULL, :open, :high, :low, :close, :volume,
                             'Yahoo Finance', datetime('now'))
                        """,
                        [{"symbol": sym.upper(), "market": market, **r} for r in rows],
                    )
                    conn.commit()
                    ohlcv_count += len(rows)

        result["ohlcv"] = ohlcv_count

    log.info(
        "[market_data_fetcher] run_daily_fetch %s: institution=%d margin=%d ohlcv=%d errors=%d",
        trade_date, result["institution_flows"], result["margin_data"],
        result["ohlcv"], len(result["errors"]),
    )
    return result
