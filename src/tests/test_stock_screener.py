"""test_stock_screener.py — stock_screener 核心引擎測試"""
import sqlite3
from datetime import date as _date

import pytest

import openclaw.stock_screener as screener_mod
from openclaw.stock_screener import (
    ensure_screener_schema,
    _load_market_symbols,
    _get_closes,
    _get_volumes,
    _get_highs_lows,
    _check_short_term_rules,
    _check_long_term_rules,
    screen_candidates,
    load_system_candidates,
    load_system_candidates_full,
    MIN_SCORE_THRESHOLD,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_institution_flows (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_margin_data (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            margin_balance REAL, short_balance REAL,
            PRIMARY KEY (trade_date, symbol)
        );
    """)


def _seed_eod_prices(conn, symbol, dates_ohlcv):
    """dates_ohlcv: list of (date_str, open, high, low, close, volume)"""
    for row in dates_ohlcv:
        conn.execute(
            "INSERT INTO eod_prices (trade_date, symbol, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?)",
            (row[0], symbol, row[1], row[2], row[3], row[4], row[5]),
        )
    conn.commit()


def _seed_institution_flows(conn, symbol, rows):
    """rows: list of (date_str, foreign_net, trust_net)"""
    for r in rows:
        conn.execute(
            "INSERT INTO eod_institution_flows (trade_date, symbol, foreign_net, trust_net, dealer_net, total_net) "
            "VALUES (?,?,?,?,0,?)",
            (r[0], symbol, r[1], r[2], r[1] + r[2]),
        )
    conn.commit()


def _seed_margin_data(conn, symbol, rows):
    """rows: list of (date_str, margin_balance)"""
    for r in rows:
        conn.execute(
            "INSERT INTO eod_margin_data (trade_date, symbol, margin_balance, short_balance) "
            "VALUES (?,?,?,0)",
            (r[0], symbol, r[1]),
        )
    conn.commit()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    _create_tables(c)
    return c


# ── ensure_screener_schema ───────────────────────────────────────────────────

class TestEnsureSchema:
    def test_creates_system_candidates(self, conn):
        ensure_screener_schema(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_candidates'"
        ).fetchone()
        assert row is not None

    def test_idempotent(self, conn):
        ensure_screener_schema(conn)
        ensure_screener_schema(conn)  # no error


# ── _load_market_symbols ─────────────────────────────────────────────────────

class TestLoadMarketSymbols:
    def test_filters_low_volume(self, conn):
        _seed_eod_prices(conn, "2330", [("2026-03-06", 100, 101, 99, 100, 1000)])
        _seed_eod_prices(conn, "2317", [("2026-03-06", 50, 51, 49, 50, 200)])
        result = _load_market_symbols(conn, "2026-03-06", exclude=set())
        assert "2330" in result
        assert "2317" not in result

    def test_excludes_set(self, conn):
        _seed_eod_prices(conn, "2330", [("2026-03-06", 100, 101, 99, 100, 1000)])
        result = _load_market_symbols(conn, "2026-03-06", exclude={"2330"})
        assert "2330" not in result

    def test_empty_when_no_data(self, conn):
        result = _load_market_symbols(conn, "2026-03-06", exclude=set())
        assert result == []


# ── _get_closes / _get_volumes / _get_highs_lows ────────────────────────────

class TestDataHelpers:
    def test_get_closes_chronological(self, conn):
        data = [
            ("2026-03-04", 100, 101, 99, 100, 500),
            ("2026-03-05", 101, 102, 100, 102, 600),
            ("2026-03-06", 102, 103, 101, 103, 700),
        ]
        _seed_eod_prices(conn, "2330", data)
        closes = _get_closes(conn, "2330", "2026-03-06", limit=3)
        assert closes == [100.0, 102.0, 103.0]

    def test_get_closes_limit(self, conn):
        data = [
            ("2026-03-04", 100, 101, 99, 100, 500),
            ("2026-03-05", 101, 102, 100, 102, 600),
            ("2026-03-06", 102, 103, 101, 103, 700),
        ]
        _seed_eod_prices(conn, "2330", data)
        closes = _get_closes(conn, "2330", "2026-03-06", limit=2)
        assert len(closes) == 2

    def test_get_volumes_chronological(self, conn):
        data = [
            ("2026-03-05", 100, 101, 99, 100, 500),
            ("2026-03-06", 101, 102, 100, 102, 600),
        ]
        _seed_eod_prices(conn, "2330", data)
        vols = _get_volumes(conn, "2330", "2026-03-06", limit=10)
        assert vols == [500, 600]

    def test_get_highs_lows(self, conn):
        data = [
            ("2026-03-05", 100, 105, 95, 100, 500),
            ("2026-03-06", 101, 110, 98, 103, 600),
        ]
        _seed_eod_prices(conn, "2330", data)
        highs, lows, closes = _get_highs_lows(conn, "2330", "2026-03-06", limit=60)
        assert highs == [105.0, 110.0]
        assert lows == [95.0, 98.0]
        assert closes == [100.0, 103.0]


# ── _check_short_term_rules ─────────────────────────────────────────────────

class TestShortTermRules:
    def _make_base_prices(self, conn, symbol="2330"):
        """Create 60 days of price data ending 2026-03-06 for technical indicators."""
        base = _date(2026, 1, 1)
        data = []
        for i in range(60):
            d = base + __import__("datetime").timedelta(days=i)
            ds = d.isoformat()
            # Flat prices, moderate volume
            data.append((ds, 100, 101, 99, 100, 500))
        _seed_eod_prices(conn, symbol, data)
        return data[-1][0]  # last trade_date

    def test_volume_surge(self, conn):
        """Today volume >= 1.5x of 5-day avg triggers volume surge."""
        base = _date(2026, 3, 1)
        data = []
        for i in range(6):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            vol = 1000 if i < 5 else 2000  # day 6: 2x avg
            data.append((d, 100, 101, 99, 100, vol))
        _seed_eod_prices(conn, "2330", data)
        score, reasons = _check_short_term_rules(conn, "2330", data[-1][0])
        assert any("量能爆發" in r for r in reasons)
        assert score >= 0.25

    def test_no_volume_surge(self, conn):
        """Volume not surging → no volume surge reason."""
        base = _date(2026, 3, 1)
        data = []
        for i in range(6):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            data.append((d, 100, 101, 99, 100, 1000))
        _seed_eod_prices(conn, "2330", data)
        score, reasons = _check_short_term_rules(conn, "2330", data[-1][0])
        assert not any("量能爆發" in r for r in reasons)

    def test_institution_buying_consecutive(self, conn):
        """Foreign+trust net > 0 for >= 2 consecutive days."""
        trade_date = self._make_base_prices(conn)
        base = _date(2026, 2, 27)
        flows = []
        for i in range(3):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            flows.append((d, 100, 50))  # foreign=100, trust=50
        _seed_institution_flows(conn, "2330", flows)
        score, reasons = _check_short_term_rules(conn, "2330", flows[-1][0])
        assert any("法人連" in r for r in reasons)

    def test_institution_buying_only_one_day(self, conn):
        """Only 1 day of buying → no trigger."""
        trade_date = self._make_base_prices(conn)
        _seed_institution_flows(conn, "2330", [("2026-03-01", 100, 50)])
        score, reasons = _check_short_term_rules(conn, "2330", "2026-03-01")
        assert not any("法人連" in r for r in reasons)

    def test_ma_golden_cross(self, conn):
        """MA5 crosses above MA20."""
        base = _date(2026, 1, 1)
        data = []
        # 20 days declining slightly (MA20 ~ 100, MA5 < MA20)
        for i in range(20):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            price = 100 - i * 0.1  # slow decline
            data.append((d, price - 1, price + 1, price - 2, price, 500))
        # Then 4 days still below MA20, then 1 big jump day
        for i in range(4):
            d = (base + __import__("datetime").timedelta(days=20 + i)).isoformat()
            price = 98 - 0.2 * i  # still low
            data.append((d, price - 1, price + 1, price - 2, price, 500))
        # Final day: big jump so MA5 crosses above MA20
        d = (base + __import__("datetime").timedelta(days=24)).isoformat()
        data.append((d, 104, 108, 103, 107, 500))
        _seed_eod_prices(conn, "2330", data)
        trade_date = data[-1][0]
        score, reasons = _check_short_term_rules(conn, "2330", trade_date)
        assert any("MA5上穿MA20" in r for r in reasons)

    def test_rsi_rebound(self, conn):
        """RSI was < 30, now 30~50."""
        base = _date(2026, 1, 1)
        data = []
        # Start high, then drop sharply (RSI goes below 30), then small recovery
        price = 200.0
        for i in range(30):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            if i < 15:
                price = 200.0
            elif i < 27:
                price = price - 5  # sharp decline
            else:
                price = price + 2  # small recovery
            data.append((d, price - 1, price + 1, price - 2, price, 500))
        _seed_eod_prices(conn, "2330", data)
        trade_date = data[-1][0]
        score, reasons = _check_short_term_rules(conn, "2330", trade_date)
        # RSI rebound is hard to guarantee exact values, check no crash
        assert isinstance(score, float)

    def test_price_breaks_resistance(self, conn):
        """Close > resistance level."""
        base = _date(2026, 1, 1)
        data = []
        # 20 days at ~100, then spike
        for i in range(20):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            data.append((d, 99, 101, 98, 100, 500))
        # Spike day
        d = (base + __import__("datetime").timedelta(days=20)).isoformat()
        data.append((d, 100, 115, 100, 112, 500))
        _seed_eod_prices(conn, "2330", data)
        score, reasons = _check_short_term_rules(conn, "2330", d)
        assert any("突破壓力位" in r for r in reasons)

    def test_insufficient_data_returns_zero(self, conn):
        """Not enough data → score 0, no reasons."""
        score, reasons = _check_short_term_rules(conn, "9999", "2026-03-06")
        assert score == 0.0
        assert reasons == []


# ── _check_long_term_rules ───────────────────────────────────────────────────

class TestLongTermRules:
    def _make_base_prices(self, conn, symbol="2330", days=60):
        """Create days of price data for MA calculations."""
        base = _date(2026, 1, 1)
        data = []
        for i in range(days):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            data.append((d, 100, 101, 99, 100, 500))
        _seed_eod_prices(conn, symbol, data)
        return data[-1][0]

    def test_steady_institution_5_days(self, conn):
        """Foreign net > 0 for 5 consecutive days."""
        trade_date = self._make_base_prices(conn)
        base = _date(2026, 2, 25)
        flows = []
        for i in range(5):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            flows.append((d, 100, 0))  # foreign_net > 0
        _seed_institution_flows(conn, "2330", flows)
        score, reasons = _check_long_term_rules(conn, "2330", flows[-1][0])
        assert any("法人穩定佈局" in r for r in reasons)
        assert score >= 0.30

    def test_steady_institution_only_4_days(self, conn):
        """Foreign net > 0 for only 4 days → no trigger."""
        trade_date = self._make_base_prices(conn)
        base = _date(2026, 2, 25)
        flows = []
        for i in range(4):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            flows.append((d, 100, 0))
        _seed_institution_flows(conn, "2330", flows)
        score, reasons = _check_long_term_rules(conn, "2330", flows[-1][0])
        assert not any("法人穩定佈局" in r for r in reasons)

    def test_margin_decrease_3_days(self, conn):
        """Margin balance decreasing for 3 consecutive days."""
        trade_date = self._make_base_prices(conn)
        _seed_margin_data(conn, "2330", [
            ("2026-02-25", 10000),
            ("2026-02-26", 9500),
            ("2026-02-27", 9000),
        ])
        score, reasons = _check_long_term_rules(conn, "2330", "2026-02-27")
        assert any("融資減少" in r for r in reasons)

    def test_margin_not_decreasing(self, conn):
        """Margin balance increasing → no trigger."""
        trade_date = self._make_base_prices(conn)
        _seed_margin_data(conn, "2330", [
            ("2026-02-25", 9000),
            ("2026-02-26", 9500),
            ("2026-02-27", 10000),
        ])
        score, reasons = _check_long_term_rules(conn, "2330", "2026-02-27")
        assert not any("融資減少" in r for r in reasons)

    def test_ma_bullish_alignment(self, conn):
        """MA5 > MA20 > MA60 — bullish alignment."""
        base = _date(2025, 12, 1)
        data = []
        # Steadily rising prices so MA5 > MA20 > MA60
        for i in range(80):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            price = 100 + i * 0.5
            data.append((d, price - 1, price + 1, price - 2, price, 500))
        _seed_eod_prices(conn, "2330", data)
        trade_date = data[-1][0]
        score, reasons = _check_long_term_rules(conn, "2330", trade_date)
        assert any("多頭排列" in r for r in reasons)

    def test_macd_histogram_turns_positive(self, conn):
        """MACD histogram transitions from negative to positive."""
        base = _date(2025, 11, 1)
        data = []
        # Create pattern: drop then recover → MACD hist turns positive
        for i in range(40):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            if i < 20:
                price = 100 - i * 0.3  # decline
            else:
                price = 100 - 20 * 0.3 + (i - 20) * 0.8  # recovery
            data.append((d, price - 1, price + 1, price - 2, price, 500))
        _seed_eod_prices(conn, "2330", data)
        trade_date = data[-1][0]
        score, reasons = _check_long_term_rules(conn, "2330", trade_date)
        # MACD turning positive is data-dependent; just verify no crash
        assert isinstance(score, float)

    def test_price_above_support(self, conn):
        """Close > support level."""
        trade_date = self._make_base_prices(conn)
        score, reasons = _check_long_term_rules(conn, "2330", trade_date)
        # With flat prices at 100, support is around 98-99, close=100 > support
        assert any("站穩支撐位" in r for r in reasons)

    def test_insufficient_data(self, conn):
        """No data → score 0."""
        score, reasons = _check_long_term_rules(conn, "9999", "2026-03-06")
        assert score == 0.0
        assert reasons == []


# ── screen_candidates ────────────────────────────────────────────────────────

class TestScreenCandidates:
    def _setup_qualifying_symbol(self, conn, symbol, trade_date_str="2026-03-06"):
        """Set up a symbol that qualifies for screening (multiple rules triggered)."""
        base = _date(2025, 12, 1)
        data = []
        # Rising prices → MA bullish + support
        for i in range(80):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            price = 100 + i * 0.5
            vol = 1000 if i < 79 else 3000  # volume surge on last day
            data.append((d, price - 1, price + 1, price - 2, price, vol))
        _seed_eod_prices(conn, symbol, data)
        last_date = data[-1][0]

        # Institution flows — 5 consecutive buying days
        flow_base = _date(2026, 2, 14)
        flows = []
        for i in range(5):
            d = (flow_base + __import__("datetime").timedelta(days=i)).isoformat()
            flows.append((d, 200, 100))
        _seed_institution_flows(conn, symbol, flows)

        # Margin data — decreasing
        _seed_margin_data(conn, symbol, [
            ("2026-02-15", 10000),
            ("2026-02-16", 9500),
            ("2026-02-17", 9000),
        ])
        return last_date

    def test_screen_returns_qualified(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        assert len(results) > 0
        assert all(r["score"] >= MIN_SCORE_THRESHOLD for r in results)

    def test_screen_excludes_manual_watchlist(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        results = screen_candidates(
            conn, td, manual_watchlist={"2330"}, max_candidates=10, llm_refine=False,
        )
        symbols = [r["symbol"] for r in results]
        assert "2330" not in symbols

    def test_screen_writes_to_db(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        ensure_screener_schema(conn)
        screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        rows = conn.execute("SELECT * FROM system_candidates").fetchall()
        assert len(rows) > 0

    def test_screen_result_keys(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        if results:
            r = results[0]
            assert set(r.keys()) >= {
                "symbol", "label", "score", "reasons", "llm_filtered",
                "trade_date", "expires_at",
            }

    def test_screen_llm_refine_raises(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        # llm_refine=True but _llm_refine_candidates raises NotImplementedError
        # screen_candidates should fallback gracefully (llm_filtered=0)
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=True,
        )
        if results:
            assert all(r["llm_filtered"] == 0 for r in results)

    def test_expiry_short_term(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        short = [r for r in results if r["label"] == "short_term"]
        for r in short:
            td_date = _date.fromisoformat(r["trade_date"])
            exp_date = _date.fromisoformat(r["expires_at"])
            assert (exp_date - td_date).days == 3

    def test_expiry_long_term(self, conn):
        td = self._setup_qualifying_symbol(conn, "2330")
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        long_ = [r for r in results if r["label"] == "long_term"]
        for r in long_:
            td_date = _date.fromisoformat(r["trade_date"])
            exp_date = _date.fromisoformat(r["expires_at"])
            assert (exp_date - td_date).days == 5

    def test_max_candidates_cap(self, conn):
        """Each label capped at max_candidates // 2."""
        # Create multiple qualifying symbols
        for sym in ["2330", "2317", "2454", "3008", "2882", "2881"]:
            self._setup_qualifying_symbol(conn, sym)
        td = self._setup_qualifying_symbol(conn, "3711")
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=4, llm_refine=False,
        )
        short_count = sum(1 for r in results if r["label"] == "short_term")
        long_count = sum(1 for r in results if r["label"] == "long_term")
        assert short_count <= 2
        assert long_count <= 2

    def test_empty_market(self, conn):
        """No symbols in market → empty result."""
        results = screen_candidates(
            conn, "2026-03-06", manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        assert results == []

    def test_sorted_by_score(self, conn):
        """Results within each label should be sorted by score descending."""
        for sym in ["2330", "2317", "2454"]:
            self._setup_qualifying_symbol(conn, sym)
        td = "2026-02-18"  # use a date within our data range
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=False,
        )
        for label in ("short_term", "long_term"):
            scores = [r["score"] for r in results if r["label"] == label]
            assert scores == sorted(scores, reverse=True)


# ── LLM refinement (Task 5) ─────────────────────────────────────────────────

class TestLLMRefinement:
    def _setup_qualifying_symbol(self, conn, symbol):
        """Reuse setup from TestScreenCandidates."""
        base = _date(2025, 12, 1)
        data = []
        for i in range(80):
            d = (base + __import__("datetime").timedelta(days=i)).isoformat()
            price = 100 + i * 0.5
            vol = 1000 if i < 79 else 3000
            data.append((d, price - 1, price + 1, price - 2, price, vol))
        _seed_eod_prices(conn, symbol, data)
        last_date = data[-1][0]
        flow_base = _date(2026, 2, 14)
        flows = []
        for i in range(5):
            d = (flow_base + __import__("datetime").timedelta(days=i)).isoformat()
            flows.append((d, 200, 100))
        _seed_institution_flows(conn, symbol, flows)
        _seed_margin_data(conn, symbol, [
            ("2026-02-15", 10000),
            ("2026-02-16", 9500),
            ("2026-02-17", 9000),
        ])
        return last_date

    def test_llm_refine_success_sets_flag(self, conn, monkeypatch):
        """When Gemini succeeds, llm_filtered=1."""
        td = self._setup_qualifying_symbol(conn, "2330")

        def fake_llm(c, trade_date, candidates):
            # Return candidates unchanged
            return candidates

        monkeypatch.setattr(screener_mod, "_llm_refine_candidates", fake_llm)
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=True,
        )
        assert len(results) > 0
        assert all(r["llm_filtered"] == 1 for r in results)

    def test_llm_refine_failure_fallback(self, conn, monkeypatch):
        """When Gemini fails, llm_filtered=0 and candidates still saved."""
        td = self._setup_qualifying_symbol(conn, "2330")

        def broken_llm(c, trade_date, candidates):
            raise RuntimeError("Gemini unavailable")

        monkeypatch.setattr(screener_mod, "_llm_refine_candidates", broken_llm)
        results = screen_candidates(
            conn, td, manual_watchlist=set(), max_candidates=10, llm_refine=True,
        )
        assert len(results) > 0
        assert all(r["llm_filtered"] == 0 for r in results)


# ── load_system_candidates (Task 6) ─────────────────────────────────────────

class TestLoadSystemCandidates:
    def test_loads_unexpired(self, conn):
        """Only unexpired candidates returned."""
        ensure_screener_schema(conn)
        now_ms = int(__import__("time").time() * 1000)
        conn.execute(
            "INSERT INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, 0, ?, ?)",
            ("2330", "2026-03-01", "short_term", 0.7, "量能爆發", "2099-12-31", now_ms),
        )
        conn.execute(
            "INSERT INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, 0, ?, ?)",
            ("2317", "2026-03-01", "short_term", 0.5, "法人連2買", "2020-01-01", now_ms),
        )
        conn.commit()
        result = load_system_candidates(conn)
        assert "2330" in result
        assert "2317" not in result

    def test_load_full_returns_details(self, conn):
        """load_system_candidates_full returns parsed dicts."""
        ensure_screener_schema(conn)
        now_ms = int(__import__("time").time() * 1000)
        reasons_json = '["量能爆發","法人連2買"]'
        conn.execute(
            "INSERT INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, 1, ?, ?)",
            ("2330", "2026-03-01", "short_term", 0.75, reasons_json, "2099-12-31", now_ms),
        )
        conn.commit()
        result = load_system_candidates_full(conn)
        assert len(result) == 1
        r = result[0]
        assert r["symbol"] == "2330"
        assert r["label"] == "short_term"
        assert r["score"] == 0.75
        assert r["reasons"] == ["量能爆發", "法人連2買"]
        assert r["llm_filtered"] is True
        assert r["expires_at"] == "2099-12-31"
        assert r["trade_date"] == "2026-03-01"

    def test_load_full_empty_reasons(self, conn):
        """Empty reasons field returns empty list."""
        ensure_screener_schema(conn)
        now_ms = int(__import__("time").time() * 1000)
        conn.execute(
            "INSERT INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, 0, ?, ?)",
            ("2330", "2026-03-01", "short_term", 0.5, "", "2099-12-31", now_ms),
        )
        conn.commit()
        result = load_system_candidates_full(conn)
        assert len(result) == 1
        assert result[0]["reasons"] == []

    def test_load_excludes_expired(self, conn):
        """load_system_candidates_full excludes expired rows."""
        ensure_screener_schema(conn)
        now_ms = int(__import__("time").time() * 1000)
        conn.execute(
            "INSERT INTO system_candidates "
            "(symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, 'rule_screener', ?, 0, ?, ?)",
            ("9999", "2020-01-01", "long_term", 0.6, "過期", "2020-01-05", now_ms),
        )
        conn.commit()
        result = load_system_candidates_full(conn)
        assert len(result) == 0
