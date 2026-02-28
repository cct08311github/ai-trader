from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.request import Request, urlopen


# TWSE OpenAPI (no auth) commonly used for 3-institution flows.
# We keep this as default, but parsing is defensive and unit tests can inject payloads.
DEFAULT_SOURCE_URL = "https://openapi.twse.com.tw/v1/fund/BFI82U"


@dataclass(frozen=True)
class InstitutionFlowRow:
    trade_date: str  # YYYY-MM-DD
    symbol: str
    foreign_net: float
    investment_trust_net: float
    dealer_net: float
    total_net: float
    health_score: float
    source_url: str


def _fetch_text(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": "OpenClaw/1.2.1"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean_symbol(symbol: Any) -> str:
    s = str(symbol or "").strip().upper()
    for suf in (".TW", ".TWO", ".TWSE", ".TPEX"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = re.sub(r"[^0-9A-Z]", "", s)
    return s


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in {"--", "---", "N/A"}:
        return None
    s = s.replace(",", "")
    s = s.replace("+", "")
    try:
        return float(s)
    except Exception:
        return None


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def calculate_chip_health_score(
    foreign_net: float,
    investment_trust_net: float,
    dealer_net: float,
    *,
    abs_ref: float = 1_000_000.0,
) -> float:
    """Return a 0..1 'chip health score'.

    Design goals:
    - monotonic with total net-buy (more net-buy => higher score)
    - rewards alignment (3 parties same direction)
    - bounded and deterministic

    This is a *heuristic* score for v4#18.
    """

    total = float(foreign_net) + float(investment_trust_net) + float(dealer_net)
    direction = _sign(total)

    mag = min(1.0, abs(total) / max(float(abs_ref), 1.0))

    signs = [_sign(float(foreign_net)), _sign(float(investment_trust_net)), _sign(float(dealer_net))]
    aligned = 0
    if direction != 0:
        aligned = sum(1 for s in signs if s == direction)

    # aligned_ratio in [0,1] but minimum 0 when none aligned.
    aligned_ratio = aligned / 3.0

    base = 0.5 + 0.35 * direction * mag

    # Bonus/penalty: if direction exists, reward aligned participants.
    # Map aligned_ratio: 1/3 -> 0, 1 -> +1.
    align_factor = 0.0
    if direction != 0:
        align_factor = (aligned_ratio - (1.0 / 3.0)) / (2.0 / 3.0)
        align_factor = max(0.0, min(1.0, align_factor))

    score = base + 0.15 * direction * align_factor

    # If institutions are strongly conflicting (two vs one) and total is small, dampen.
    if direction == 0 and sum(1 for s in signs if s != 0) >= 2:
        score = 0.5

    return max(0.0, min(1.0, float(score)))


def _extract_trade_date(it: Dict[str, Any], fallback: str) -> str:
    for k in ("trade_date", "TradeDate", "Date", "日期", "交易日期"):
        v = it.get(k)
        if not v:
            continue
        s = str(v)
        m = re.search(r"(20\d{2})[-/]?(\d{2})[-/]?(\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return fallback


def parse_institution_payload(
    payload: Iterable[Dict[str, Any]],
    *,
    trade_date: str,
    source_url: str = DEFAULT_SOURCE_URL,
    abs_ref: float = 1_000_000.0,
) -> List[InstitutionFlowRow]:
    """Parse a TWSE-like JSON payload into rows.

    The real OpenAPI field names can differ across endpoints; we support a set
    of common aliases.
    """

    rows: List[InstitutionFlowRow] = []
    for it in payload:
        if not isinstance(it, dict):
            continue

        symbol = _clean_symbol(it.get("Code") or it.get("證券代號") or it.get("symbol") or "")
        if not symbol:
            continue

        td = _extract_trade_date(it, trade_date)

        # Aliases (prefer already-net if provided)
        f_net = _to_float(it.get("ForeignNet") or it.get("foreign_net") or it.get("外資買賣超") or it.get("Foreign_Dealer_Net"))
        it_net = _to_float(it.get("InvestmentTrustNet") or it.get("investment_trust_net") or it.get("投信買賣超"))
        d_net = _to_float(it.get("DealerNet") or it.get("dealer_net") or it.get("自營商買賣超"))

        # If net is missing, try buy/sell.
        if f_net is None:
            fb = _to_float(it.get("ForeignBuy") or it.get("外資買進"))
            fs = _to_float(it.get("ForeignSell") or it.get("外資賣出"))
            if fb is not None and fs is not None:
                f_net = fb - fs
        if it_net is None:
            ib = _to_float(it.get("InvestmentTrustBuy") or it.get("投信買進"))
            is_ = _to_float(it.get("InvestmentTrustSell") or it.get("投信賣出"))
            if ib is not None and is_ is not None:
                it_net = ib - is_
        if d_net is None:
            db = _to_float(it.get("DealerBuy") or it.get("自營商買進"))
            ds = _to_float(it.get("DealerSell") or it.get("自營商賣出"))
            if db is not None and ds is not None:
                d_net = db - ds

        if f_net is None or it_net is None or d_net is None:
            # Not enough data.
            continue

        total = float(f_net) + float(it_net) + float(d_net)
        health = calculate_chip_health_score(float(f_net), float(it_net), float(d_net), abs_ref=abs_ref)

        rows.append(
            InstitutionFlowRow(
                trade_date=td,
                symbol=symbol,
                foreign_net=float(f_net),
                investment_trust_net=float(it_net),
                dealer_net=float(d_net),
                total_net=float(total),
                health_score=float(health),
                source_url=source_url,
            )
        )

    return rows


def fetch_institution_flows(
    trade_date: str,
    *,
    source_url: str = DEFAULT_SOURCE_URL,
    timeout: int = 20,
    fetcher: Callable[[str, int], str] = _fetch_text,
) -> List[InstitutionFlowRow]:
    raw = fetcher(source_url, timeout)
    items = json.loads(raw)
    if not isinstance(items, list):
        return []
    return parse_institution_payload(items, trade_date=trade_date, source_url=source_url)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS institution_flows (
          trade_date            TEXT NOT NULL,
          symbol                TEXT NOT NULL,
          foreign_net           REAL NOT NULL,
          investment_trust_net  REAL NOT NULL,
          dealer_net            REAL NOT NULL,
          total_net             REAL NOT NULL,
          health_score          REAL NOT NULL,
          source_url            TEXT NOT NULL,
          ingested_at           TEXT NOT NULL,
          PRIMARY KEY (trade_date, symbol)
        )
        """
    )


def upsert_institution_flows(conn: sqlite3.Connection, rows: List[InstitutionFlowRow]) -> int:
    ensure_schema(conn)
    conn.executemany(
        """
        INSERT INTO institution_flows(
          trade_date, symbol, foreign_net, investment_trust_net, dealer_net,
          total_net, health_score, source_url, ingested_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(trade_date, symbol) DO UPDATE SET
          foreign_net = excluded.foreign_net,
          investment_trust_net = excluded.investment_trust_net,
          dealer_net = excluded.dealer_net,
          total_net = excluded.total_net,
          health_score = excluded.health_score,
          source_url = excluded.source_url,
          ingested_at = excluded.ingested_at
        """,
        [
            (
                r.trade_date,
                r.symbol,
                float(r.foreign_net),
                float(r.investment_trust_net),
                float(r.dealer_net),
                float(r.total_net),
                float(r.health_score),
                r.source_url,
            )
            for r in rows
        ],
    )
    return len(rows)


def record_ingest_run(
    conn: sqlite3.Connection,
    *,
    trade_date: str,
    status: str,
    rows: int,
    source_url: str,
    error_text: str = "",
) -> str:
    """Optional: record ingest runs for audit/debug."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS institution_ingest_runs (
          run_id      TEXT PRIMARY KEY,
          trade_date  TEXT NOT NULL,
          status      TEXT NOT NULL,
          rows        INTEGER NOT NULL,
          source_url  TEXT NOT NULL,
          error_text  TEXT NOT NULL,
          created_at  TEXT NOT NULL
        )
        """
    )

    run_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO institution_ingest_runs(
          run_id, trade_date, status, rows, source_url, error_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (run_id, trade_date, status, int(rows), source_url, str(error_text)),
    )
    return run_id
