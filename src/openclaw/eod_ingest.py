from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.request import Request, urlopen
from openclaw.path_utils import get_repo_root

_REPO_ROOT = get_repo_root()
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")

# TWSE/TPEx certs are missing Subject Key Identifier (RFC 5280 §4.2.1.2),
# which Python 3.14 now enforces. These are trusted government sources.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


TWSE_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEx_URL = "https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=csv"


@dataclass
class EODRow:
    trade_date: str
    market: str
    symbol: str
    name: str
    close: Optional[float]
    change: Optional[float]
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    volume: Optional[float]
    turnover: Optional[float]
    trades: Optional[float]
    source_url: str


def _fetch_text(url: str, timeout: int = 20, encoding: str = "utf-8") -> str:
    req = Request(url, headers={"User-Agent": "OpenClaw/1.2.1"})
    with urlopen(req, context=_SSL_CTX, timeout=timeout) as resp:
        raw = resp.read()
        return raw.decode(encoding, errors="replace")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in {"--", "---", "除權息", "N/A"}:
        return None
    s = s.replace(",", "")
    s = s.replace("X", "").replace("x", "")
    s = s.replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_trade_date_from_payload(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("Date", "date", "資料日期", "交易日期"):
        val = payload.get(key)
        if val:
            s = str(val)
            m = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", s)
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def fetch_twse_rows(trade_date: str) -> List[EODRow]:
    raw = _fetch_text(TWSE_URL)
    items = json.loads(raw)
    rows: List[EODRow] = []
    for it in items:
        symbol = str(it.get("Code") or it.get("證券代號") or "").strip()
        if not symbol:
            continue
        name = str(it.get("Name") or it.get("證券名稱") or "").strip()
        td = _extract_trade_date_from_payload(it) or trade_date
        close = _to_float(it.get("ClosingPrice") or it.get("收盤價"))
        if close is None:
            continue  # 當日未成交（停牌/除息）— 無分析價值，跳過
        rows.append(
            EODRow(
                trade_date=td,
                market="TWSE",
                symbol=symbol,
                name=name,
                close=close,
                change=_to_float(it.get("Change") or it.get("漲跌價差")),
                open=_to_float(it.get("OpeningPrice") or it.get("開盤價")),
                high=_to_float(it.get("HighestPrice") or it.get("最高價")),
                low=_to_float(it.get("LowestPrice") or it.get("最低價")),
                volume=_to_float(it.get("TradeVolume") or it.get("成交股數")),
                turnover=_to_float(it.get("TradeValue") or it.get("成交金額")),
                trades=_to_float(it.get("Transaction") or it.get("成交筆數")),
                source_url=TWSE_URL,
            )
        )
    return rows


def _find_tpex_header(lines: Iterable[str]) -> Optional[List[str]]:
    for ln in lines:
        if "代號" in ln and "名稱" in ln and "收盤" in ln:
            return [c.strip().strip('"') for c in next(csv.reader([ln]))]
    return None


def fetch_tpex_rows(trade_date: str) -> List[EODRow]:
    raw = _fetch_text(TPEx_URL, encoding="cp950")  # TPEx 回傳 MS950 (Big5 超集)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    header = _find_tpex_header(lines)
    if not header:
        return []

    data_start_idx = 0
    for i, ln in enumerate(lines):
        if "代號" in ln and "名稱" in ln and "收盤" in ln:
            data_start_idx = i + 1
            break

    rows: List[EODRow] = []
    for ln in lines[data_start_idx:]:
        if not re.search(r"\d{4}", ln):
            continue
        row = [c.strip().strip('"') for c in next(csv.reader([ln]))]
        if len(row) < 8:
            continue
        symbol = row[0]
        if not re.match(r"^\d{4,6}$", symbol):
            continue
        name = row[1] if len(row) > 1 else ""
        close = _to_float(row[2] if len(row) > 2 else None)
        if close is None:
            continue  # 當日未成交（到期/低流動性）— 無分析價值，跳過
        change = _to_float(row[3] if len(row) > 3 else None)
        open_ = _to_float(row[4] if len(row) > 4 else None)
        high = _to_float(row[5] if len(row) > 5 else None)
        low = _to_float(row[6] if len(row) > 6 else None)
        # col[7] = 均價 (average price) — skip
        volume = _to_float(row[8] if len(row) > 8 else None)    # 成交股數
        turnover = _to_float(row[9] if len(row) > 9 else None)  # 成交金額(元)
        trades = _to_float(row[10] if len(row) > 10 else None)  # 成交筆數
        rows.append(
            EODRow(
                trade_date=trade_date,
                market="TPEx",
                symbol=symbol,
                name=name,
                close=close,
                change=change,
                open=open_,
                high=high,
                low=low,
                volume=volume,
                turnover=turnover,
                trades=trades,
                source_url=TPEx_URL,
            )
        )
    return rows


def upsert_eod_rows(conn: sqlite3.Connection, rows: List[EODRow]) -> int:
    sql = """
    INSERT INTO eod_prices (
      trade_date, market, symbol, name, close, change, open, high, low, volume, turnover, trades, source_url, ingested_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(trade_date, market, symbol) DO UPDATE SET
      name = excluded.name,
      close = excluded.close,
      change = excluded.change,
      open = excluded.open,
      high = excluded.high,
      low = excluded.low,
      volume = excluded.volume,
      turnover = excluded.turnover,
      trades = excluded.trades,
      source_url = excluded.source_url,
      ingested_at = excluded.ingested_at
    """
    conn.executemany(
        sql,
        [
            (
                r.trade_date,
                r.market,
                r.symbol,
                r.name,
                r.close,
                r.change,
                r.open,
                r.high,
                r.low,
                r.volume,
                r.turnover,
                r.trades,
                r.source_url,
            )
            for r in rows
        ],
    )
    return len(rows)


def record_run(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    status: str,
    twse_rows: int,
    tpex_rows: int,
    error_text: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO eod_ingest_runs(run_id, trade_date, status, twse_rows, tpex_rows, error_text)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), trade_date, status, twse_rows, tpex_rows, error_text),
    )


def apply_migration_if_needed(conn: sqlite3.Connection, sql_path: Path) -> None:
    conn.executescript(sql_path.read_text(encoding="utf-8"))
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TWSE + TPEx EOD data into SQLite.")
    parser.add_argument("--db", default=_DEFAULT_DB)
    parser.add_argument("--trade-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--apply-migration", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    if args.apply_migration:
        repo_root = get_repo_root()
        apply_migration_if_needed(conn, repo_root / "sql" / "migration_v1_2_1_eod_data.sql")

    twse_rows = 0
    tpex_rows = 0
    status = "success"
    error_text = ""
    try:
        twse = fetch_twse_rows(args.trade_date)
        tpex = fetch_tpex_rows(args.trade_date)
        conn.execute("BEGIN IMMEDIATE")
        twse_rows = upsert_eod_rows(conn, twse)
        tpex_rows = upsert_eod_rows(conn, tpex)
        record_run(
            conn,
            trade_date=args.trade_date,
            status="success",
            twse_rows=twse_rows,
            tpex_rows=tpex_rows,
        )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        status = "failed"
        error_text = str(exc)
        record_run(
            conn,
            trade_date=args.trade_date,
            status=status,
            twse_rows=twse_rows,
            tpex_rows=tpex_rows,
            error_text=error_text,
        )
        conn.commit()
        raise
    finally:
        # Fetch institution flows (T86) + margin data (MI_MARGN) into
        # eod_institution_flows / eod_margin_data — used by reports API.
        inst_rows = 0
        margin_rows = 0
        inst_error = ""
        try:
            # Support both `python -m openclaw.eod_ingest` and direct script execution
            try:
                from openclaw.market_data_fetcher import run_daily_fetch
            except ModuleNotFoundError:
                import sys as _sys
                _sys.path.insert(0, str(Path(__file__).resolve().parent))
                from market_data_fetcher import run_daily_fetch
            result = run_daily_fetch(args.trade_date, conn)
            inst_rows = result.get("institution_flows", 0)
            margin_rows = result.get("margin_data", 0)
            fetch_errors = result.get("errors", [])
            if fetch_errors:
                inst_error = "; ".join(fetch_errors)
                print(
                    f"[eod_ingest] partial fetch errors: {inst_error}",
                    file=__import__("sys").stderr,
                )
        except Exception as exc:
            inst_error = str(exc)
            print(
                f"[eod_ingest] institution/margin fetch failed: {exc}",
                file=__import__("sys").stderr,
            )

        try:
            print(
                json.dumps(
                    {
                        "status": status,
                        "trade_date": args.trade_date,
                        "twse_rows": twse_rows,
                        "tpex_rows": tpex_rows,
                        "institution_flows": inst_rows,
                        "margin_data": margin_rows,
                        "institution_error": inst_error,
                        "error": error_text,
                    },
                    ensure_ascii=True,
                )
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
