# Dual-Source Watchlist Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace single-source universe watchlist with dual-source system (rule-based screener + manual tracking), merging both into active monitoring.

**Architecture:** New `stock_screener.py` module does rule-based screening of all TWSE stocks using EOD data (prices, institution flows, margin data), with optional Gemini refinement. Results stored in `system_candidates` DB table. `ticker_watcher.py` merges manual watchlist + unexpired system candidates into active monitoring list (no cap). Frontend shows two distinct sections with "pin to manual" capability.

**Tech Stack:** Python 3 / SQLite / FastAPI / React + Tailwind CSS / Gemini LLM (optional refinement)

---

## Task 1: Create `stock_screener.py` — DB schema + data loading

**Files:**
- Create: `src/openclaw/stock_screener.py`
- Test: `src/tests/test_stock_screener.py`

**Step 1: Write failing tests for schema creation and data loading**

```python
# src/tests/test_stock_screener.py
"""Tests for stock_screener.py — rule-based candidate screening engine."""
from __future__ import annotations

import json
import sqlite3
import pytest
from datetime import date, timedelta


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, market TEXT, symbol TEXT, name TEXT,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        PRIMARY KEY (trade_date, market, symbol))""")
    conn.execute("""CREATE TABLE eod_institution_flows (
        trade_date TEXT, symbol TEXT, name TEXT,
        foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
        PRIMARY KEY (trade_date, symbol))""")
    conn.execute("""CREATE TABLE eod_margin_data (
        trade_date TEXT, symbol TEXT, name TEXT,
        margin_balance REAL, short_balance REAL,
        PRIMARY KEY (trade_date, symbol))""")
    return conn


class TestEnsureSchema:
    def test_creates_system_candidates_table(self):
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema
        ensure_screener_schema(conn)
        # Table exists and can be queried
        rows = conn.execute("SELECT * FROM system_candidates").fetchall()
        assert rows == []

    def test_idempotent(self):
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema
        ensure_screener_schema(conn)
        ensure_screener_schema(conn)  # No error on second call


class TestLoadMarketSymbols:
    def test_filters_low_volume(self):
        """Symbols with volume < 500 are excluded."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, _load_market_symbols
        ensure_screener_schema(conn)
        td = "2026-03-06"
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?)",
                     (td, "TWSE", "2330", "台積電", 900, 910, 895, 905, 10000))
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?)",
                     (td, "TWSE", "9999", "冷門股", 10, 10, 10, 10, 100))
        conn.commit()
        symbols = _load_market_symbols(conn, td, exclude=set())
        assert "2330" in symbols
        assert "9999" not in symbols

    def test_excludes_manual_watchlist(self):
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, _load_market_symbols
        ensure_screener_schema(conn)
        td = "2026-03-06"
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?)",
                     (td, "TWSE", "2330", "台積電", 900, 910, 895, 905, 10000))
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?)",
                     (td, "TWSE", "2317", "鴻海", 100, 105, 98, 103, 5000))
        conn.commit()
        symbols = _load_market_symbols(conn, td, exclude={"2330"})
        assert "2330" not in symbols
        assert "2317" in symbols
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/openclaw/.openclaw/shared/projects/ai-trader && python -m pytest src/tests/test_stock_screener.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'openclaw.stock_screener'`

**Step 3: Write minimal implementation**

```python
# src/openclaw/stock_screener.py
"""stock_screener.py — Rule-based stock screening engine.

Screens all TWSE stocks from EOD data using technical + institutional rules.
Produces short-term and long-term candidates stored in system_candidates table.
Optional Gemini LLM refinement pass with fallback (llm_filtered flag).

Triggered by: eod_analysis.py (daily 16:35 TWN)
Consumed by: ticker_watcher.py (daily merge into active monitoring)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Dict, List, Optional, Set

log = logging.getLogger(__name__)


def ensure_screener_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_candidates (
            symbol        TEXT NOT NULL,
            trade_date    TEXT NOT NULL,
            label         TEXT NOT NULL,
            score         REAL NOT NULL,
            source        TEXT NOT NULL DEFAULT 'rule_screener',
            reasons       TEXT,
            llm_filtered  INTEGER NOT NULL DEFAULT 0,
            expires_at    TEXT NOT NULL,
            created_at    INTEGER NOT NULL,
            PRIMARY KEY (symbol, trade_date, label)
        )
    """)
    conn.commit()


def _load_market_symbols(
    conn: sqlite3.Connection, trade_date: str, *, exclude: Set[str],
) -> List[str]:
    """Load all symbols from eod_prices on trade_date with volume >= 500, excluding manual watchlist."""
    rows = conn.execute(
        "SELECT symbol FROM eod_prices "
        "WHERE trade_date=? AND volume >= 500 AND symbol NOT IN ({}) "
        "ORDER BY symbol".format(",".join("?" for _ in exclude)) if exclude else
        "SELECT symbol FROM eod_prices WHERE trade_date=? AND volume >= 500 ORDER BY symbol",
        (trade_date, *exclude) if exclude else (trade_date,),
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["symbol"] for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/openclaw/.openclaw/shared/projects/ai-trader && python -m pytest src/tests/test_stock_screener.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): add stock_screener schema + market symbol loading"
```

---

## Task 2: Short-term screening rules

**Files:**
- Modify: `src/openclaw/stock_screener.py`
- Modify: `src/tests/test_stock_screener.py`

**Step 1: Write failing tests for short-term rule checks**

Add to `src/tests/test_stock_screener.py`:

```python
def _seed_eod_prices(conn, symbol, name, days=10, base_close=100.0, base_volume=1000):
    """Insert N days of eod_prices with ascending dates, slight uptrend."""
    from datetime import date, timedelta
    today = date(2026, 3, 6)
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        c = base_close + i * 0.5
        v = base_volume if i < days - 1 else base_volume  # default flat volume
        conn.execute("INSERT OR REPLACE INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?)",
                     (d, "TWSE", symbol, name, c - 1, c + 1, c - 2, c, v))
    conn.commit()


def _seed_institution_flows(conn, symbol, name, days=5, net=100):
    from datetime import date, timedelta
    today = date(2026, 3, 6)
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO eod_institution_flows VALUES (?,?,?,?,?,?,?)",
            (d, symbol, name, net * 0.6, net * 0.3, net * 0.1, net))
    conn.commit()


class TestShortTermRules:
    def test_volume_surge_detected(self):
        """Volume >= 1.5x of 5-day avg triggers volume surge rule."""
        conn = _make_db()
        from openclaw.stock_screener import _check_short_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        # Spike today's volume to 2000 (2x avg)
        conn.execute("UPDATE eod_prices SET volume=2000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        score, reasons = _check_short_term_rules(conn, "2330", td)
        assert score >= 0.25
        assert any("量能" in r for r in reasons)

    def test_institution_buying_detected(self):
        """Foreign + trust net > 0 for >= 2 consecutive days triggers rule."""
        conn = _make_db()
        from openclaw.stock_screener import _check_short_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)
        score, reasons = _check_short_term_rules(conn, "2330", td)
        assert score >= 0.25
        assert any("法人" in r for r in reasons)

    def test_no_rules_triggered_returns_zero(self):
        """Symbol with flat volume and no institution data scores 0."""
        conn = _make_db()
        from openclaw.stock_screener import _check_short_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "9901", "冷門股", days=10, base_volume=1000)
        score, reasons = _check_short_term_rules(conn, "9901", td)
        assert score == 0.0
        assert reasons == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/tests/test_stock_screener.py::TestShortTermRules -v`
Expected: FAIL — `_check_short_term_rules` not defined

**Step 3: Write implementation**

Add to `src/openclaw/stock_screener.py`:

```python
from openclaw.technical_indicators import calc_ma, calc_rsi, find_support_resistance


def _get_closes(conn: sqlite3.Connection, symbol: str, trade_date: str, limit: int = 60) -> List[float]:
    rows = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol=? AND trade_date<=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT ?", (symbol, trade_date, limit)
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["close"] for r in reversed(rows)]


def _get_volumes(conn: sqlite3.Connection, symbol: str, trade_date: str, limit: int = 10) -> List[int]:
    rows = conn.execute(
        "SELECT volume FROM eod_prices WHERE symbol=? AND trade_date<=? AND volume IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT ?", (symbol, trade_date, limit)
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["volume"] for r in reversed(rows)]


def _get_highs_lows(conn: sqlite3.Connection, symbol: str, trade_date: str, limit: int = 60):
    rows = conn.execute(
        "SELECT high, low, close FROM eod_prices WHERE symbol=? AND trade_date<=? "
        "ORDER BY trade_date DESC LIMIT ?", (symbol, trade_date, limit)
    ).fetchall()
    rows = list(reversed(rows))
    highs = [r[0] if isinstance(r, tuple) else r["high"] for r in rows]
    lows = [r[1] if isinstance(r, tuple) else r["low"] for r in rows]
    closes = [r[2] if isinstance(r, tuple) else r["close"] for r in rows]
    return highs, lows, closes


def _check_short_term_rules(
    conn: sqlite3.Connection, symbol: str, trade_date: str,
) -> tuple[float, List[str]]:
    """Evaluate short-term screening rules. Returns (score, reasons)."""
    score = 0.0
    reasons: List[str] = []

    # Rule 1: Volume surge — today >= 1.5x of 5-day avg
    volumes = _get_volumes(conn, symbol, trade_date, limit=6)
    if len(volumes) >= 6:
        avg_5 = sum(volumes[:-1]) / 5
        today_vol = volumes[-1]
        if avg_5 > 0 and today_vol >= avg_5 * 1.5:
            ratio = round(today_vol / avg_5, 1)
            score += 0.25
            reasons.append(f"量能爆發({ratio}x)")

    # Rule 2: Institution buying — foreign+trust net > 0 for >= 2 consecutive days
    inst_rows = conn.execute(
        "SELECT foreign_net, trust_net FROM eod_institution_flows "
        "WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 5",
        (symbol, trade_date),
    ).fetchall()
    if len(inst_rows) >= 2:
        consec = 0
        for r in inst_rows:
            fn = r[0] if isinstance(r, tuple) else r["foreign_net"]
            tn = r[1] if isinstance(r, tuple) else r["trust_net"]
            if (fn or 0) + (tn or 0) > 0:
                consec += 1
            else:
                break
        if consec >= 2:
            score += 0.25
            reasons.append(f"法人連{consec}買")

    # Rule 3: MA golden cross — MA5 crosses above MA20
    closes = _get_closes(conn, symbol, trade_date, limit=25)
    if len(closes) >= 21:
        ma5 = calc_ma(closes, 5)
        ma20 = calc_ma(closes, 20)
        if (ma5[-1] is not None and ma20[-1] is not None and
            ma5[-2] is not None and ma20[-2] is not None and
            ma5[-1] > ma20[-1] and ma5[-2] <= ma20[-2]):
            score += 0.25
            reasons.append("MA5上穿MA20")

    # Rule 4: RSI rebound — RSI14 was < 30, now 30~50
    if len(closes) >= 16:
        rsi = calc_rsi(closes, 14)
        rsi_vals = [v for v in rsi[-3:] if v is not None]
        if len(rsi_vals) >= 2:
            if rsi_vals[-2] < 30 and 30 <= rsi_vals[-1] <= 50:
                score += 0.15
                reasons.append(f"RSI回升({rsi_vals[-1]:.0f})")

    # Rule 5: Price breaks above resistance
    highs, lows, sr_closes = _get_highs_lows(conn, symbol, trade_date, limit=25)
    if len(sr_closes) >= 20:
        sr = find_support_resistance(highs, lows, sr_closes)
        if sr_closes[-1] > sr["resistance"]:
            score += 0.10
            reasons.append("突破壓力位")

    return round(score, 2), reasons
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest src/tests/test_stock_screener.py -v`
Expected: PASS (all tests including new short-term rules)

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): short-term screening rules (volume/institution/MA/RSI/resistance)"
```

---

## Task 3: Long-term screening rules

**Files:**
- Modify: `src/openclaw/stock_screener.py`
- Modify: `src/tests/test_stock_screener.py`

**Step 1: Write failing tests for long-term rules**

Add to `src/tests/test_stock_screener.py`:

```python
def _seed_margin_data(conn, symbol, name, days=5, start_balance=10000, decrease=True):
    from datetime import date, timedelta
    today = date(2026, 3, 6)
    for i in range(days):
        d = (today - timedelta(days=days - 1 - i)).isoformat()
        bal = start_balance - (i * 200 if decrease else 0)
        conn.execute(
            "INSERT OR REPLACE INTO eod_margin_data VALUES (?,?,?,?,?)",
            (d, symbol, name, bal, 500))
    conn.commit()


class TestLongTermRules:
    def test_institution_steady_buying(self):
        """Foreign net > 0 for >= 5 consecutive days triggers steady buying rule."""
        conn = _make_db()
        from openclaw.stock_screener import _check_long_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=5000)
        _seed_institution_flows(conn, "2330", "台積電", days=6, net=1000)
        score, reasons = _check_long_term_rules(conn, "2330", td)
        assert score >= 0.30
        assert any("法人穩定佈局" in r for r in reasons)

    def test_margin_decrease(self):
        """Margin balance decreasing for >= 3 consecutive days triggers margin rule."""
        conn = _make_db()
        from openclaw.stock_screener import _check_long_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=5000)
        _seed_margin_data(conn, "2330", "台積電", days=5, decrease=True)
        score, reasons = _check_long_term_rules(conn, "2330", td)
        assert score >= 0.20
        assert any("融資減少" in r for r in reasons)

    def test_ma_bullish_alignment(self):
        """MA5 > MA20 > MA60 triggers bullish alignment rule."""
        conn = _make_db()
        from openclaw.stock_screener import _check_long_term_rules
        td = "2026-03-06"
        # Strong uptrend: each day adds 2.0 so MA5 >> MA20 >> MA60
        _seed_eod_prices(conn, "2330", "台積電", days=65, base_close=50.0, base_volume=5000)
        # Override: make close steadily rising by larger amount
        from datetime import date as _date, timedelta as _td
        for i in range(65):
            d = (_date(2026, 3, 6) - _td(days=64 - i)).isoformat()
            c = 50 + i * 2.0  # strong uptrend
            conn.execute("UPDATE eod_prices SET close=?, high=?, low=? WHERE symbol='2330' AND trade_date=?",
                         (c, c + 1, c - 1, d))
        conn.commit()
        score, reasons = _check_long_term_rules(conn, "2330", td)
        assert score >= 0.25
        assert any("多頭排列" in r for r in reasons)

    def test_no_rules_returns_zero(self):
        conn = _make_db()
        from openclaw.stock_screener import _check_long_term_rules
        td = "2026-03-06"
        _seed_eod_prices(conn, "9901", "冷門", days=10, base_volume=1000)
        score, reasons = _check_long_term_rules(conn, "9901", td)
        assert score == 0.0
        assert reasons == []
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest src/tests/test_stock_screener.py::TestLongTermRules -v`
Expected: FAIL — `_check_long_term_rules` not defined

**Step 3: Write implementation**

Add to `src/openclaw/stock_screener.py`:

```python
def _check_long_term_rules(
    conn: sqlite3.Connection, symbol: str, trade_date: str,
) -> tuple[float, List[str]]:
    """Evaluate long-term screening rules. Returns (score, reasons)."""
    score = 0.0
    reasons: List[str] = []

    # Rule 1: Steady institution buying — foreign net > 0 for >= 5 consecutive days
    inst_rows = conn.execute(
        "SELECT foreign_net FROM eod_institution_flows "
        "WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 10",
        (symbol, trade_date),
    ).fetchall()
    if len(inst_rows) >= 5:
        consec = 0
        for r in inst_rows:
            fn = r[0] if isinstance(r, tuple) else r["foreign_net"]
            if (fn or 0) > 0:
                consec += 1
            else:
                break
        if consec >= 5:
            score += 0.30
            reasons.append(f"法人穩定佈局(連{consec}日)")

    # Rule 2: Margin balance decreasing >= 3 consecutive days
    margin_rows = conn.execute(
        "SELECT margin_balance FROM eod_margin_data "
        "WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 5",
        (symbol, trade_date),
    ).fetchall()
    if len(margin_rows) >= 3:
        consec_dec = 0
        balances = [r[0] if isinstance(r, tuple) else r["margin_balance"] for r in margin_rows]
        for i in range(len(balances) - 1):
            if balances[i] < balances[i + 1]:  # DESC order: newer < older = decreasing
                consec_dec += 1
            else:
                break
        if consec_dec >= 3:
            score += 0.20
            reasons.append(f"融資減少(連{consec_dec}日)")

    # Rule 3: MA bullish alignment — MA5 > MA20 > MA60
    closes = _get_closes(conn, symbol, trade_date, limit=65)
    ma5 = calc_ma(closes, 5) if len(closes) >= 5 else []
    ma20 = calc_ma(closes, 20) if len(closes) >= 20 else []
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else []
    if ma5 and ma20 and ma60:
        v5, v20, v60 = ma5[-1], ma20[-1], ma60[-1]
        if v5 is not None and v20 is not None and v60 is not None:
            if v5 > v20 > v60:
                score += 0.25
                reasons.append("多頭排列(MA5>MA20>MA60)")

    # Rule 4: MACD histogram turns positive
    if len(closes) >= 35:
        from openclaw.technical_indicators import calc_macd
        macd_result = calc_macd(closes)
        hist = macd_result["histogram"]
        hist_vals = [v for v in hist[-3:] if v is not None]
        if len(hist_vals) >= 2 and hist_vals[-2] < 0 and hist_vals[-1] >= 0:
            score += 0.15
            reasons.append("MACD翻正")

    # Rule 5: Price above support
    highs, lows, sr_closes = _get_highs_lows(conn, symbol, trade_date, limit=25)
    if len(sr_closes) >= 20:
        sr = find_support_resistance(highs, lows, sr_closes)
        if sr_closes[-1] > sr["support"]:
            score += 0.10
            reasons.append("站穩支撐位")

    return round(score, 2), reasons
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest src/tests/test_stock_screener.py -v`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): long-term screening rules (institution/margin/MA/MACD/support)"
```

---

## Task 4: Main `screen_candidates()` orchestrator + DB write

**Files:**
- Modify: `src/openclaw/stock_screener.py`
- Modify: `src/tests/test_stock_screener.py`

**Step 1: Write failing tests**

Add to `src/tests/test_stock_screener.py`:

```python
class TestScreenCandidates:
    def test_full_screening_writes_to_db(self):
        """screen_candidates finds and persists candidates."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        # Seed a stock with volume surge + institution buying (score >= 0.5)
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)

        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=10, llm_refine=False)
        assert len(result) >= 1
        # Check DB was written
        rows = conn.execute("SELECT * FROM system_candidates WHERE trade_date=?", (td,)).fetchall()
        assert len(rows) >= 1

    def test_respects_max_candidates(self):
        """Max candidates per label is max_candidates/2."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        # Seed 10 stocks with volume surge
        for i in range(10):
            sym = str(1000 + i)
            _seed_eod_prices(conn, sym, f"Stock{i}", days=10, base_volume=1000)
            conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol=? AND trade_date=?", (sym, td))
            _seed_institution_flows(conn, sym, f"Stock{i}", days=3, net=500)
        conn.commit()
        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=4, llm_refine=False)
        short_term = [r for r in result if r["label"] == "short_term"]
        assert len(short_term) <= 2  # max_candidates/2

    def test_excludes_manual_watchlist(self):
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)
        result = screen_candidates(conn, td, manual_watchlist=["2330"], max_candidates=10, llm_refine=False)
        symbols = [r["symbol"] for r in result]
        assert "2330" not in symbols

    def test_llm_filtered_false_when_no_llm(self):
        """When llm_refine=False, all candidates have llm_filtered=0."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)
        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=10, llm_refine=False)
        for r in result:
            assert r["llm_filtered"] == 0

    def test_expiry_dates(self):
        """Short-term expires in 3 days, long-term in 5 days."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)
        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=10, llm_refine=False)
        for r in result:
            if r["label"] == "short_term":
                assert r["expires_at"] == "2026-03-09"
            elif r["label"] == "long_term":
                assert r["expires_at"] == "2026-03-11"
```

**Step 2: Run tests — expected FAIL**

**Step 3: Write implementation**

Add to `src/openclaw/stock_screener.py`:

```python
from datetime import date as _date, timedelta as _timedelta

_SHORT_TERM_EXPIRY_DAYS = 3
_LONG_TERM_EXPIRY_DAYS = 5
_MIN_SCORE_THRESHOLD = 0.4  # Minimum score (>= 2 rules) to qualify


def screen_candidates(
    conn: sqlite3.Connection,
    trade_date: str,
    *,
    manual_watchlist: List[str],
    max_candidates: int = 10,
    llm_refine: bool = True,
) -> List[dict]:
    """Screen all market symbols and persist qualified candidates.

    Returns list of candidate dicts written to system_candidates table.
    """
    ensure_screener_schema(conn)
    exclude = set(s.strip().upper() for s in manual_watchlist)
    symbols = _load_market_symbols(conn, trade_date, exclude=exclude)
    log.info("[SCREENER] Scanning %d symbols for %s (excluding %d manual)",
             len(symbols), trade_date, len(exclude))

    short_candidates: List[dict] = []
    long_candidates: List[dict] = []

    for sym in symbols:
        # Short-term check
        st_score, st_reasons = _check_short_term_rules(conn, sym, trade_date)
        if st_score >= _MIN_SCORE_THRESHOLD:
            short_candidates.append({
                "symbol": sym, "label": "short_term",
                "score": st_score, "reasons": st_reasons,
            })

        # Long-term check
        lt_score, lt_reasons = _check_long_term_rules(conn, sym, trade_date)
        if lt_score >= _MIN_SCORE_THRESHOLD:
            long_candidates.append({
                "symbol": sym, "label": "long_term",
                "score": lt_score, "reasons": lt_reasons,
            })

    # Sort by score desc, cap each at half of max_candidates
    half = max(max_candidates // 2, 1)
    short_candidates.sort(key=lambda c: c["score"], reverse=True)
    long_candidates.sort(key=lambda c: c["score"], reverse=True)
    short_candidates = short_candidates[:half]
    long_candidates = long_candidates[:half]

    all_candidates = short_candidates + long_candidates
    td = _date.fromisoformat(trade_date)
    now_ms = int(time.time() * 1000)

    # Gemini refinement (optional)
    llm_filtered = 0
    if llm_refine and all_candidates:
        try:
            all_candidates = _llm_refine_candidates(conn, trade_date, all_candidates)
            llm_filtered = 1
        except Exception as e:
            log.warning("[SCREENER] Gemini refinement failed, using rule-only results: %s", e)
            llm_filtered = 0

    # Write to DB
    results: List[dict] = []
    for c in all_candidates:
        expiry_days = _SHORT_TERM_EXPIRY_DAYS if c["label"] == "short_term" else _LONG_TERM_EXPIRY_DAYS
        expires = (td + _timedelta(days=expiry_days)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c["symbol"], trade_date, c["label"], c["score"], "rule_screener",
             json.dumps(c["reasons"], ensure_ascii=False), llm_filtered, expires, now_ms),
        )
        results.append({
            "symbol": c["symbol"], "label": c["label"], "score": c["score"],
            "reasons": c["reasons"], "llm_filtered": llm_filtered,
            "trade_date": trade_date, "expires_at": expires,
        })
    conn.commit()

    log.info("[SCREENER] Found %d candidates (short=%d, long=%d, llm_filtered=%s)",
             len(results), len(short_candidates), len(long_candidates), bool(llm_filtered))
    return results


def _llm_refine_candidates(
    conn: sqlite3.Connection, trade_date: str, candidates: List[dict],
) -> List[dict]:
    """Use Gemini to refine candidate list. May remove unsuitable ones."""
    # Placeholder — will be implemented in Task 5
    raise NotImplementedError("LLM refinement not yet implemented")
```

**Step 4: Run tests — expected PASS**

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): screen_candidates orchestrator with DB persistence + expiry"
```

---

## Task 5: Gemini LLM refinement pass

**Files:**
- Modify: `src/openclaw/stock_screener.py`
- Modify: `src/tests/test_stock_screener.py`

**Step 1: Write failing tests**

Add to `src/tests/test_stock_screener.py`:

```python
class TestLLMRefinement:
    def test_llm_refine_success_sets_flag(self, monkeypatch):
        """When Gemini succeeds, llm_filtered=1."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)

        # Mock the LLM call to return the candidates unchanged
        import openclaw.stock_screener as screener_mod
        monkeypatch.setattr(screener_mod, "_llm_refine_candidates",
                           lambda conn, td, cands: cands)
        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=10, llm_refine=True)
        for r in result:
            assert r["llm_filtered"] == 1

    def test_llm_refine_failure_fallback(self, monkeypatch):
        """When Gemini fails, llm_filtered=0 and candidates still saved."""
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, screen_candidates
        ensure_screener_schema(conn)
        td = "2026-03-06"
        _seed_eod_prices(conn, "2330", "台積電", days=10, base_volume=1000)
        conn.execute("UPDATE eod_prices SET volume=3000 WHERE symbol='2330' AND trade_date=?", (td,))
        conn.commit()
        _seed_institution_flows(conn, "2330", "台積電", days=3, net=500)

        import openclaw.stock_screener as screener_mod
        def _fail(*a, **kw): raise RuntimeError("Gemini down")
        monkeypatch.setattr(screener_mod, "_llm_refine_candidates", _fail)
        result = screen_candidates(conn, td, manual_watchlist=[], max_candidates=10, llm_refine=True)
        assert len(result) >= 1
        for r in result:
            assert r["llm_filtered"] == 0
```

**Step 2: Run tests — expected FAIL**

**Step 3: Write `_llm_refine_candidates` implementation**

Replace the placeholder in `src/openclaw/stock_screener.py`:

```python
def _llm_refine_candidates(
    conn: sqlite3.Connection, trade_date: str, candidates: List[dict],
) -> List[dict]:
    """Use Gemini to refine candidate list. May remove unsuitable ones or adjust scores."""
    from openclaw.agents.base import call_agent_llm, DEFAULT_MODEL, write_trace

    summary = json.dumps(
        [{"symbol": c["symbol"], "label": c["label"], "score": c["score"], "reasons": c["reasons"]}
         for c in candidates],
        ensure_ascii=False, indent=2,
    )
    prompt = (
        f"你是 AI Trader 選股篩選器。以下是 {trade_date} 規則引擎篩出的候選股票：\n\n"
        f"{summary}\n\n"
        "請審查每支候選股，移除明顯不適合的（如近期有重大利空、被處置、流動性不足等）。\n"
        "對剩餘候選微調分數（0.0~1.0），並補充理由。\n\n"
        "輸出 JSON 陣列（僅保留通過審查的）：\n"
        '[{"symbol": "2330", "label": "short_term", "score": 0.8, "reasons": ["..."]}, ...]'
    )
    result = call_agent_llm(prompt, model=DEFAULT_MODEL)
    write_trace(conn, agent="screener_llm", prompt=prompt[:500], result=result)

    # Parse LLM result — expect a list
    refined: List[dict] = []
    if isinstance(result, list):
        refined = result
    elif isinstance(result, dict) and "candidates" in result:
        refined = result["candidates"]
    else:
        log.warning("[SCREENER] LLM returned unexpected format, keeping rule results")
        return candidates

    # Validate: only keep items with required fields
    valid = []
    for item in refined:
        if isinstance(item, dict) and "symbol" in item and "label" in item:
            valid.append({
                "symbol": item["symbol"],
                "label": item.get("label", "short_term"),
                "score": float(item.get("score", 0.5)),
                "reasons": item.get("reasons", []),
            })
    return valid if valid else candidates
```

**Step 4: Run tests — expected PASS**

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): Gemini LLM refinement with fallback to rule-only"
```

---

## Task 6: Load system candidates helper (for ticker_watcher)

**Files:**
- Modify: `src/openclaw/stock_screener.py`
- Modify: `src/tests/test_stock_screener.py`

**Step 1: Write failing test**

```python
class TestLoadSystemCandidates:
    def test_loads_unexpired_candidates(self):
        conn = _make_db()
        from openclaw.stock_screener import ensure_screener_schema, load_system_candidates
        ensure_screener_schema(conn)
        now_ms = int(time.time() * 1000)
        # Insert one valid (future expiry) and one expired
        conn.execute(
            "INSERT INTO system_candidates VALUES (?,?,?,?,?,?,?,?,?)",
            ("2330", "2026-03-06", "short_term", 0.75, "rule_screener",
             '["test"]', 1, "2099-12-31", now_ms))
        conn.execute(
            "INSERT INTO system_candidates VALUES (?,?,?,?,?,?,?,?,?)",
            ("9999", "2026-03-01", "long_term", 0.50, "rule_screener",
             '["old"]', 0, "2020-01-01", now_ms))
        conn.commit()
        symbols = load_system_candidates(conn)
        assert "2330" in symbols
        assert "9999" not in symbols
```

Add `import time` to top of test file if not already present.

**Step 2: Run tests — expected FAIL**

**Step 3: Write implementation**

Add to `src/openclaw/stock_screener.py`:

```python
def load_system_candidates(conn: sqlite3.Connection) -> List[str]:
    """Load unexpired system candidate symbols for active monitoring."""
    ensure_screener_schema(conn)
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM system_candidates WHERE expires_at >= date('now')"
    ).fetchall()
    return [r[0] if isinstance(r, tuple) else r["symbol"] for r in rows]


def load_system_candidates_full(conn: sqlite3.Connection) -> List[dict]:
    """Load full candidate details (for API response)."""
    ensure_screener_schema(conn)
    rows = conn.execute(
        "SELECT symbol, trade_date, label, score, reasons, llm_filtered, expires_at "
        "FROM system_candidates WHERE expires_at >= date('now') "
        "ORDER BY score DESC"
    ).fetchall()
    result = []
    for r in rows:
        if isinstance(r, tuple):
            sym, td, label, score, reasons_json, llm_f, exp = r
        else:
            sym, td, label, score, reasons_json, llm_f, exp = (
                r["symbol"], r["trade_date"], r["label"], r["score"],
                r["reasons"], r["llm_filtered"], r["expires_at"])
        result.append({
            "symbol": sym, "trade_date": td, "label": label,
            "score": score, "reasons": json.loads(reasons_json) if reasons_json else [],
            "llm_filtered": bool(llm_f), "expires_at": exp,
        })
    return result
```

**Step 4: Run tests — expected PASS**

**Step 5: Commit**

```bash
git add src/openclaw/stock_screener.py src/tests/test_stock_screener.py
git commit -m "feat(screener): load_system_candidates for ticker_watcher merge"
```

---

## Task 7: Integrate screener into `eod_analysis.py`

**Files:**
- Modify: `src/openclaw/agents/eod_analysis.py` (around line 155, after market_data_fetcher)

**Step 1: Write failing test**

Create `src/tests/test_eod_screener_integration.py`:

```python
"""Test eod_analysis → stock_screener integration."""
from __future__ import annotations
import json, sqlite3, types, sys
import pytest


@pytest.fixture(autouse=True)
def _mock_gemini(monkeypatch):
    """Mock google.genai so call_agent_llm doesn't hit real API."""
    fake_genai = types.ModuleType("google.genai")
    fake_types = types.ModuleType("google.genai.types")

    class FakeResponse:
        text = json.dumps({"summary": "test", "confidence": 0.5, "action_type": "suggest",
                           "market_outlook": {"sentiment": "neutral", "sector_focus": [], "confidence": 0.5},
                           "position_actions": [], "watchlist_opportunities": [], "risk_notes": [], "proposals": []})

    class FakeModels:
        def generate_content(self, **kw):
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kw):
            self.models = FakeModels()

    fake_genai.Client = FakeClient
    fake_genai.types = fake_types
    fake_types.GenerateContentConfig = lambda **kw: {}
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)


def test_eod_analysis_calls_screener(tmp_path, monkeypatch):
    """After market data fetch, eod_analysis should call screen_candidates."""
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    # Create required tables
    for sql in [
        "CREATE TABLE eod_prices (trade_date TEXT, market TEXT, symbol TEXT, name TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, change REAL, source_url TEXT, ingested_at TEXT, PRIMARY KEY(trade_date,market,symbol))",
        "CREATE TABLE eod_institution_flows (trade_date TEXT, symbol TEXT, name TEXT, foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL, PRIMARY KEY(trade_date,symbol))",
        "CREATE TABLE eod_margin_data (trade_date TEXT, symbol TEXT, name TEXT, margin_balance REAL, short_balance REAL, PRIMARY KEY(trade_date,symbol))",
        "CREATE TABLE positions (symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL, current_price REAL, unrealized_pnl REAL, state TEXT, high_water_mark REAL, entry_trading_day TEXT)",
        "CREATE TABLE llm_traces (trace_id TEXT, agent TEXT, model TEXT, prompt TEXT, response TEXT, latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, confidence REAL, created_at INTEGER NOT NULL, metadata TEXT)",
    ]:
        conn.execute(sql)
    # Seed minimal data
    conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("2026-03-06", "TWSE", "2330", "台積電", 900, 910, 895, 905, 10000, 5.0, "", ""))
    conn.commit()

    screener_called = []
    import openclaw.stock_screener as sm
    original_screen = sm.screen_candidates
    def mock_screen(c, td, **kw):
        screener_called.append(td)
        return []
    monkeypatch.setattr(sm, "screen_candidates", mock_screen)

    # Also mock market_data_fetcher
    monkeypatch.setattr("openclaw.market_data_fetcher.run_daily_fetch", lambda *a, **kw: None)

    from openclaw.agents.eod_analysis import run_eod_analysis
    result = run_eod_analysis(trade_date="2026-03-06", conn=conn)
    assert "2026-03-06" in screener_called
```

**Step 2: Run test — expected FAIL** (screener not called in eod_analysis yet)

**Step 3: Modify `eod_analysis.py`**

After the market_data_fetcher block (line 155), add:

```python
        # 0.5 篩選潛力候選股
        try:
            from openclaw.stock_screener import screen_candidates
            watchlist_cfg_path = _REPO_ROOT / "config" / "watchlist.json"
            manual_wl = []
            if watchlist_cfg_path.exists():
                wl_cfg = json.loads(watchlist_cfg_path.read_text())
                manual_wl = wl_cfg.get("manual_watchlist", wl_cfg.get("universe", []))
            screen_candidates(
                _conn, _date,
                manual_watchlist=manual_wl,
                max_candidates=10,
                llm_refine=True,
            )
        except Exception as _e:
            log.warning("[eod_analysis] stock_screener 失敗，繼續執行: %s", _e)
```

**Step 4: Run test — expected PASS**

**Step 5: Commit**

```bash
git add src/openclaw/agents/eod_analysis.py src/tests/test_eod_screener_integration.py
git commit -m "feat(eod): integrate stock_screener into daily EOD analysis pipeline"
```

---

## Task 8: Update `ticker_watcher.py` — dual-source merge

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`

**Step 1: Write failing test**

Create `src/tests/test_ticker_watcher_merge.py`:

```python
"""Test ticker_watcher dual-source watchlist merge."""
from __future__ import annotations
import json, sqlite3
import pytest
from pathlib import Path


def test_load_manual_watchlist_reads_new_key(tmp_path, monkeypatch):
    """_load_manual_watchlist reads manual_watchlist key."""
    cfg = tmp_path / "watchlist.json"
    cfg.write_text(json.dumps({"manual_watchlist": ["2330", "3008"]}))
    import openclaw.ticker_watcher as tw
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg)
    symbols = tw._load_manual_watchlist()
    assert symbols == ["2330", "3008"]


def test_load_manual_watchlist_fallback_universe(tmp_path, monkeypatch):
    """_load_manual_watchlist falls back to universe key for backward compat."""
    cfg = tmp_path / "watchlist.json"
    cfg.write_text(json.dumps({"universe": ["2317", "2454"]}))
    import openclaw.ticker_watcher as tw
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg)
    symbols = tw._load_manual_watchlist()
    assert symbols == ["2317", "2454"]


def test_load_manual_watchlist_missing_file(tmp_path, monkeypatch):
    """Falls back to _FALLBACK_UNIVERSE when file missing."""
    cfg = tmp_path / "nonexistent.json"
    import openclaw.ticker_watcher as tw
    monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg)
    symbols = tw._load_manual_watchlist()
    assert symbols == tw._FALLBACK_UNIVERSE
```

**Step 2: Run tests — expected FAIL**

**Step 3: Modify `ticker_watcher.py`**

Rename `_load_universe` → `_load_manual_watchlist` and update its logic:

```python
def _load_manual_watchlist() -> List[str]:
    """Read manual_watchlist from config/watchlist.json. Falls back to 'universe' key for compat."""
    try:
        cfg = json.loads(_WATCHLIST_CFG.read_text(encoding="utf-8"))
        # New key first, fallback to old 'universe'
        symbols = cfg.get("manual_watchlist", cfg.get("universe", []))
        symbols = [str(s).strip() for s in symbols if str(s).strip()]
        if not symbols:
            raise ValueError("manual_watchlist is empty")
        return symbols
    except Exception as e:
        log.warning("watchlist.json read failed (%s) — using fallback %s", e, _FALLBACK_UNIVERSE)
        return list(_FALLBACK_UNIVERSE)
```

Update the main loop (around line 612 and 636-649) to merge sources:

```python
    # Replace old screening block with dual-source merge
    manual_watchlist = _load_manual_watchlist()
    log.info("Ticker watcher started | manual=%d stocks | INTERVAL=%ds | DB=%s",
             len(manual_watchlist), POLL_INTERVAL_SEC, DB_PATH)

    # ... inside the daily screen block (line ~637):
    if last_screen_date != today:
        manual_watchlist = _load_manual_watchlist()
        # Load system candidates from DB
        try:
            from openclaw.stock_screener import load_system_candidates
            sys_candidates = load_system_candidates(conn_tmp)
            log.info("[MERGE] system_candidates=%d unexpired", len(sys_candidates))
        except Exception as _e:
            log.warning("[MERGE] Failed to load system_candidates: %s", _e)
            sys_candidates = []
        active_watchlist = list(dict.fromkeys(manual_watchlist + sys_candidates))
        last_screen_date = today
        _log_screen_trace(conn_tmp, universe=manual_watchlist, active=active_watchlist)
```

Remove `_screen_top_movers` call and `max_active` variable (no longer needed — all symbols monitored).

**Step 4: Run tests — expected PASS**

**Step 5: Commit**

```bash
git add src/openclaw/ticker_watcher.py src/tests/test_ticker_watcher_merge.py
git commit -m "feat(watcher): dual-source merge — manual_watchlist + system_candidates"
```

---

## Task 9: Migrate `config/watchlist.json` structure

**Files:**
- Modify: `config/watchlist.json`

**Step 1: Update config file**

```json
{
  "comment": "manual_watchlist: 手動追蹤清單。system_candidates 由 stock_screener 自動篩選，存 DB。",
  "manual_watchlist": [
    "2330", "2317", "2454", "2308", "2382",
    "2881", "2882", "2886", "2412", "3008",
    "2002", "1301", "1303", "2603", "2609"
  ],
  "max_system_candidates": 10,
  "screener": {
    "enabled": true,
    "short_term": {
      "min_volume_ratio": 1.5,
      "min_foreign_net_days": 2
    },
    "long_term": {
      "min_foreign_net_days": 5,
      "margin_decrease_days": 3
    }
  }
}
```

**Step 2: Commit**

```bash
git add config/watchlist.json
git commit -m "chore: migrate watchlist.json — universe → manual_watchlist"
```

---

## Task 10: Update `settings.py` API — dual-source response

**Files:**
- Modify: `frontend/backend/app/api/settings.py` (lines 218-289)
- Modify: `frontend/backend/tests/test_settings_api.py`

**Step 1: Update failing tests**

Modify `TestWatchlistSettings` in `frontend/backend/tests/test_settings_api.py`:

```python
class TestWatchlistSettings:
    def test_get_watchlist_new_format(self, settings_client):
        c, _, _, _, watchlist_file, db_file = settings_client
        # Write new format
        watchlist_file.write_text(json.dumps({
            "manual_watchlist": ["2330", "2317"],
            "max_system_candidates": 10,
            "screener": {"enabled": True},
        }))
        # Create system_candidates table with one entry
        conn = sqlite3.connect(str(db_file))
        conn.execute("""CREATE TABLE IF NOT EXISTS system_candidates (
            symbol TEXT, trade_date TEXT, label TEXT, score REAL,
            source TEXT, reasons TEXT, llm_filtered INTEGER, expires_at TEXT,
            created_at INTEGER, PRIMARY KEY(symbol,trade_date,label))""")
        conn.execute("INSERT INTO system_candidates VALUES (?,?,?,?,?,?,?,?,?)",
                     ("6442", "2026-03-06", "short_term", 0.75, "rule_screener",
                      '["量能爆發"]', 1, "2099-12-31", 1000))
        conn.commit()
        conn.close()
        r = c.get("/api/settings/watchlist", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "manual_watchlist" in data
        assert "system_candidates" in data
        assert "active_symbols" in data
        assert "6442" in data["active_symbols"]

    def test_get_watchlist_backward_compat(self, settings_client):
        """Old format with 'universe' key still works."""
        c, _, _, _, watchlist_file, _ = settings_client
        watchlist_file.write_text(json.dumps({"universe": ["2330"]}))
        r = c.get("/api/settings/watchlist", headers=_AUTH)
        assert r.status_code == 200
        assert "2330" in r.json()["manual_watchlist"]

    def test_update_watchlist_new_format(self, settings_client):
        c, *_ = settings_client
        payload = {"manual_watchlist": ["2330", "2454"]}
        r = c.put("/api/settings/watchlist", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "2330" in data["manual_watchlist"]

    def test_update_watchlist_empty_list_rejected(self, settings_client):
        c, *_ = settings_client
        payload = {"manual_watchlist": []}
        r = c.put("/api/settings/watchlist", json=payload, headers=_AUTH)
        assert r.status_code == 400

    def test_watchlist_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/watchlist")
        assert r.status_code == 401
```

**Step 2: Run tests — expected FAIL**

**Step 3: Rewrite the Watchlist section in `settings.py`**

Replace lines 218-289 with:

```python
# ─── Watchlist ─────────────────────────────────────────────────────────────────

_WATCHLIST_DEFAULT = {
    "manual_watchlist": ["2330", "2317", "2454", "2308", "2382",
                         "2881", "2882", "2886", "2412", "3008",
                         "2002", "1301", "1303", "2603", "2609"],
    "max_system_candidates": 10,
    "screener": {"enabled": True},
}


class WatchlistSettings(BaseModel):
    manual_watchlist: List[str]


def _load_system_candidates() -> List[dict]:
    """Load unexpired system candidates from DB."""
    try:
        con = sqlite3.connect(DB_PATH_ENV)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT symbol, trade_date, label, score, reasons, llm_filtered, expires_at "
            "FROM system_candidates WHERE expires_at >= date('now') ORDER BY score DESC"
        ).fetchall()
        con.close()
        result = []
        for r in rows:
            # Look up name from eod_prices
            name = ""
            try:
                con2 = sqlite3.connect(DB_PATH_ENV)
                nr = con2.execute(
                    "SELECT name FROM eod_prices WHERE symbol=? ORDER BY trade_date DESC LIMIT 1",
                    (r["symbol"],)
                ).fetchone()
                con2.close()
                if nr:
                    name = nr[0]
            except Exception:
                pass
            result.append({
                "symbol": r["symbol"], "name": name,
                "trade_date": r["trade_date"], "label": r["label"],
                "score": r["score"],
                "reasons": json.loads(r["reasons"]) if r["reasons"] else [],
                "llm_filtered": bool(r["llm_filtered"]),
                "expires_at": r["expires_at"],
            })
        return result
    except Exception:
        return []


@router.get("/watchlist")
def get_watchlist():
    cfg = _load_json(WATCHLIST_PATH, _WATCHLIST_DEFAULT)
    # Backward compat: universe → manual_watchlist
    manual = cfg.get("manual_watchlist", cfg.get("universe", _WATCHLIST_DEFAULT["manual_watchlist"]))
    candidates = _load_system_candidates()
    candidate_symbols = [c["symbol"] for c in candidates]
    active = list(dict.fromkeys(manual + candidate_symbols))
    return {
        "manual_watchlist": manual,
        "system_candidates": candidates,
        "active_symbols": active,
        "screener": cfg.get("screener", {"enabled": True}),
    }


@router.put("/watchlist")
def update_watchlist(req: WatchlistSettings):
    if not req.manual_watchlist:
        raise HTTPException(status_code=400, detail="manual_watchlist 不可為空")
    cfg = _load_json(WATCHLIST_PATH, _WATCHLIST_DEFAULT)
    cfg["manual_watchlist"] = [s.strip().upper() for s in req.manual_watchlist if s.strip()]
    # Remove old 'universe' key if present
    cfg.pop("universe", None)
    cfg.pop("max_active", None)
    _save_json(WATCHLIST_PATH, cfg)
    candidates = _load_system_candidates()
    candidate_symbols = [c["symbol"] for c in candidates]
    active = list(dict.fromkeys(cfg["manual_watchlist"] + candidate_symbols))
    return {
        "status": "ok",
        "manual_watchlist": cfg["manual_watchlist"],
        "system_candidates": candidates,
        "active_symbols": active,
        "screener": cfg.get("screener", {"enabled": True}),
    }
```

**Step 4: Run tests — expected PASS**

Run: `cd frontend/backend && python -m pytest tests/test_settings_api.py -v`

**Step 5: Commit**

```bash
git add frontend/backend/app/api/settings.py frontend/backend/tests/test_settings_api.py
git commit -m "feat(api): dual-source watchlist API — manual + system_candidates"
```

---

## Task 11: Update `Settings.jsx` — dual-section UI

**Files:**
- Modify: `frontend/web/src/pages/Settings.jsx` (WatchlistSection, lines 142-313)

**Step 1: Rewrite WatchlistSection**

Replace the `WatchlistSection` function (lines 142-313) with:

```jsx
/* ── Watchlist Section ────────────────────────────────────── */
function WatchlistSection() {
    const [data, setData] = useState(null)
    const [error, setError] = useState(null)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [newSymbol, setNewSymbol] = useState('')
    const [addError, setAddError] = useState('')

    const load = useCallback(async () => {
        try {
            const res = await authFetch(`${getApiBase()}/api/settings/watchlist`)
            if (!res.ok) throw new Error(`HTTP ${res.status}`)
            setData(await res.json())
            setError(null)
        } catch (e) { setError(e.message) }
    }, [])

    useEffect(() => { load() }, [load])

    function addSymbol() {
        const sym = newSymbol.trim().toUpperCase()
        if (!sym) return
        if (!/^\d{4}$/.test(sym) && !/^[A-Z]{1,5}$/.test(sym)) {
            setAddError('格式不正確（台股4位數字或美股英文代碼）')
            return
        }
        if (data.manual_watchlist.includes(sym)) {
            setAddError(`${sym} 已在清單中`)
            return
        }
        setData(d => ({ ...d, manual_watchlist: [...d.manual_watchlist, sym] }))
        setNewSymbol('')
        setAddError('')
        setDirty(true)
        setSaved(false)
    }

    function pinSymbol(sym) {
        if (data.manual_watchlist.includes(sym)) return
        setData(d => ({ ...d, manual_watchlist: [...d.manual_watchlist, sym] }))
        setDirty(true)
        setSaved(false)
    }

    function removeSymbol(sym) {
        setData(d => ({ ...d, manual_watchlist: d.manual_watchlist.filter(s => s !== sym) }))
        setDirty(true)
        setSaved(false)
    }

    async function save() {
        setSaving(true)
        try {
            const res = await authFetch(`${getApiBase()}/api/settings/watchlist`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ manual_watchlist: data.manual_watchlist }),
            })
            if (!res.ok) {
                const b = await res.json().catch(() => ({}))
                throw new Error(b.detail || `HTTP ${res.status}`)
            }
            const updated = await res.json()
            setData(updated)
            setDirty(false)
            setSaved(true)
            setTimeout(() => setSaved(false), 4000)
        } catch (e) { setError(e.message) }
        finally { setSaving(false) }
    }

    const labelStyle = {
        short_term: { bg: 'bg-amber-500/10 border-amber-500/30 text-amber-300', text: '短線' },
        long_term:  { bg: 'bg-blue-500/10 border-blue-500/30 text-blue-300', text: '長線' },
    }

    return (
        <Section title="選股候選池" icon={List} color="text-violet-400" defaultOpen={true}>
            {error && (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300 mt-4">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />{error}
                </div>
            )}
            {!data ? (
                <div className="flex items-center gap-2 text-xs text-slate-400 py-4">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />載入中...
                </div>
            ) : (
                <>
                    {/* Section 1: Manual Watchlist */}
                    <div className="pt-4">
                        <div className="flex items-center gap-2 mb-2">
                            <List className="h-3.5 w-3.5 text-violet-400" />
                            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                                我的追蹤清單
                            </span>
                            <span className="ml-auto text-xs text-slate-500">{data.manual_watchlist.length} 支</span>
                        </div>
                        <p className="text-xs text-slate-500 mb-3">手動維護的長期追蹤股票，全部納入每日監控。</p>
                        <div className="flex flex-wrap gap-2 mb-3">
                            {data.manual_watchlist.map(sym => (
                                <span key={sym} className="flex items-center gap-1 rounded-lg bg-violet-500/10 border border-violet-500/30 px-2.5 py-1 text-xs font-mono font-semibold text-violet-300">
                                    {sym}
                                    <button
                                        onClick={() => removeSymbol(sym)}
                                        className="text-violet-400/50 hover:text-rose-400 transition-colors ml-0.5"
                                        title={`移除 ${sym}`}
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </span>
                            ))}
                        </div>
                        <div className="flex items-center gap-2">
                            <input
                                type="text"
                                placeholder="新增股票代碼（如 2330）"
                                value={newSymbol}
                                onChange={e => { setNewSymbol(e.target.value); setAddError('') }}
                                onKeyDown={e => e.key === 'Enter' && addSymbol()}
                                className="flex-1 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
                            />
                            <button
                                onClick={addSymbol}
                                className="flex items-center gap-1.5 rounded-xl bg-violet-600/20 border border-violet-500/30 px-3 py-2 text-sm font-medium text-violet-300 hover:bg-violet-600/30 transition-colors"
                            >
                                <Plus className="h-4 w-4" />新增
                            </button>
                        </div>
                        {addError && <p className="text-xs text-rose-400 mt-1">{addError}</p>}
                    </div>

                    <div className="my-4 border-t border-slate-800/60" />

                    {/* Section 2: System Candidates */}
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <Zap className="h-3.5 w-3.5 text-amber-400" />
                            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                                系統推薦候選
                            </span>
                            <button onClick={load} className="ml-auto text-slate-500 hover:text-slate-300 transition-colors">
                                <RefreshCw className="h-3 w-3" />
                            </button>
                        </div>
                        <p className="text-xs text-slate-500 mb-3">每日盤後自動篩選的上漲潛力股，到期自動移除。</p>
                        {data.system_candidates && data.system_candidates.length > 0 ? (
                            <div className="space-y-2">
                                {data.system_candidates.map(c => (
                                    <div key={`${c.symbol}-${c.label}`}
                                         className="rounded-lg border border-slate-800/60 bg-slate-900/30 p-3">
                                        <div className="flex items-center gap-2 mb-1.5">
                                            <span className="text-sm font-mono font-semibold text-slate-100">
                                                {c.symbol}
                                            </span>
                                            {c.name && (
                                                <span className="text-xs text-slate-400">{c.name}</span>
                                            )}
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${labelStyle[c.label]?.bg || 'bg-slate-700 text-slate-300'}`}>
                                                {labelStyle[c.label]?.text || c.label}
                                            </span>
                                            {!c.llm_filtered && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/10 border border-yellow-500/30 text-yellow-300"
                                                      title="僅規則篩選，未經 AI 驗證">
                                                    僅規則
                                                </span>
                                            )}
                                            <span className="ml-auto text-[10px] text-slate-600">
                                                到期 {c.expires_at}
                                            </span>
                                        </div>
                                        {/* Score bar */}
                                        <div className="flex items-center gap-2 mb-1.5">
                                            <div className="flex-1 h-1.5 rounded-full bg-slate-800">
                                                <div className="h-1.5 rounded-full bg-emerald-400/70 transition-all"
                                                     style={{ width: `${Math.round(c.score * 100)}%` }} />
                                            </div>
                                            <span className="text-[10px] text-slate-400 w-8 text-right">
                                                {Math.round(c.score * 100)}
                                            </span>
                                        </div>
                                        {/* Reasons */}
                                        <div className="flex flex-wrap gap-1 mb-1.5">
                                            {(c.reasons || []).map((r, i) => (
                                                <span key={i} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400">
                                                    {r}
                                                </span>
                                            ))}
                                        </div>
                                        {/* Pin button */}
                                        {!data.manual_watchlist.includes(c.symbol) && (
                                            <button
                                                onClick={() => pinSymbol(c.symbol)}
                                                className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors"
                                            >
                                                + 加入追蹤
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <span className="text-xs text-slate-500 italic">尚無系統推薦（盤後分析執行後自動更新）</span>
                        )}
                    </div>

                    <div className="my-4 border-t border-slate-800/60" />

                    {/* Section 3: Active Monitoring */}
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <Zap className="h-3.5 w-3.5 text-emerald-400" />
                            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                                目前監控中
                            </span>
                            <span className="ml-auto text-xs text-slate-500">{(data.active_symbols || []).length} 支</span>
                        </div>
                        <p className="text-xs text-slate-500 mb-2">追蹤清單 + 系統推薦合流後的實際監控標的。</p>
                        <div className="flex flex-wrap gap-2 min-h-[2rem]">
                            {(data.active_symbols || []).map(sym => {
                                const isManual = data.manual_watchlist.includes(sym)
                                const sysCandidate = (data.system_candidates || []).find(c => c.symbol === sym)
                                const color = isManual ? 'bg-violet-500/10 border-violet-500/30 text-violet-300'
                                    : sysCandidate?.label === 'short_term' ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                                    : 'bg-blue-500/10 border-blue-500/30 text-blue-300'
                                return (
                                    <span key={sym} className={`rounded-lg border px-2.5 py-1 text-xs font-mono ${color}`}>
                                        {sym}
                                    </span>
                                )
                            })}
                        </div>
                    </div>

                    <SaveBar saving={saving} saved={saved} dirty={dirty} onSave={save} />
                </>
            )}
        </Section>
    )
}
```

**Step 2: Run frontend tests**

Run: `cd frontend/web && npm test -- --run`

**Step 3: Commit**

```bash
git add frontend/web/src/pages/Settings.jsx
git commit -m "feat(ui): dual-section watchlist — manual tracking + system candidates + active monitoring"
```

---

## Task 12: Update existing tests for backward compatibility

**Files:**
- Modify: `frontend/backend/tests/test_settings_api.py` (fixture watchlist format)

**Step 1: Update test fixture**

In `settings_client` fixture, update the watchlist file creation (line 43-48):

```python
    watchlist_file.write_text(json.dumps({
        "manual_watchlist": ["2330", "2317"],
        "max_system_candidates": 10,
        "screener": {"enabled": True},
    }))
```

Also add `system_candidates` table creation in the DB setup (after llm_traces):

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_candidates (
            symbol TEXT, trade_date TEXT, label TEXT, score REAL,
            source TEXT, reasons TEXT, llm_filtered INTEGER,
            expires_at TEXT, created_at INTEGER,
            PRIMARY KEY(symbol, trade_date, label))
    """)
```

**Step 2: Run all backend tests**

Run: `cd frontend/backend && python -m pytest tests/ -v`

**Step 3: Run all core engine tests**

Run: `cd /Users/openclaw/.openclaw/shared/projects/ai-trader && python -m pytest src/tests/ -v`

**Step 4: Fix any remaining failures, then commit**

```bash
git add frontend/backend/tests/test_settings_api.py
git commit -m "test: update settings fixture for dual-source watchlist schema"
```

---

## Task 13: Full test suite + CI verification

**Step 1: Run all Python tests**

```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
python -m pytest src/tests/ -q
cd frontend/backend && python -m pytest tests/ -q
```

**Step 2: Run frontend tests**

```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web && npm test -- --run
```

**Step 3: Final commit with any fixes**

**Step 4: Push and monitor CI**

```bash
git push origin main
gh run list --limit 1
gh run watch <run-id>
```

---

## Summary of all new/modified files

| Action | File | Task |
|--------|------|------|
| Create | `src/openclaw/stock_screener.py` | 1-6 |
| Create | `src/tests/test_stock_screener.py` | 1-6 |
| Create | `src/tests/test_eod_screener_integration.py` | 7 |
| Create | `src/tests/test_ticker_watcher_merge.py` | 8 |
| Modify | `src/openclaw/agents/eod_analysis.py` | 7 |
| Modify | `src/openclaw/ticker_watcher.py` | 8 |
| Modify | `config/watchlist.json` | 9 |
| Modify | `frontend/backend/app/api/settings.py` | 10 |
| Modify | `frontend/backend/tests/test_settings_api.py` | 10, 12 |
| Modify | `frontend/web/src/pages/Settings.jsx` | 11 |
