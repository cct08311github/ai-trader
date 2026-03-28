"""test_market_data_fetcher.py — 完整測試 market_data_fetcher 模組

正向 / 負向 / 邊界測試全覆蓋。
使用 unittest.mock.patch 攔截 urllib.request.urlopen，
不發送任何真實 HTTP 請求。
"""
from __future__ import annotations

import json
import sqlite3
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from openclaw.market_data_fetcher import (
    _parse_num,
    _to_api_date,
    ensure_schema,
    fetch_institution_flows,
    fetch_margin_data,
    fetch_ohlcv_yahoo,
    run_daily_fetch,
    save_institution_flows,
    save_margin_data,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def conn():
    """In-memory SQLite with schema initialised."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    ensure_schema(c)
    yield c
    c.close()


# ── Helper to build a fake urlopen response ──────────────────────────────────


def _fake_response(payload: dict):
    """Return a context-manager-compatible mock for urlopen."""
    body = json.dumps(payload).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── T86 sample data (two stocks) ─────────────────────────────────────────────

_T86_ROW_UP = [
    "2330", "台積電",
    "1000", "500", "500",   # idx 2-4: 外資買進/賣出/超
    "100", "50", "50",      # idx 5-7: 外資自營
    "550",                  # idx 8:  外陸資+外資自營合計  ← foreign_net
    "200", "100", "100",    # idx 9-11: 投信買進/賣出/超  ← trust_net = 100
    "80", "20", "60",       # idx 12-14: 自營商            ← dealer_net = 60
    "710",                  # idx 15: 三大合計             ← total_net = 710
]
_T86_ROW_DOWN = [
    "2412", "中華電",
    "200", "400", "-200",
    "0", "0", "0",
    "-200",                 # idx 8: foreign_net = -200
    "50", "150", "-100",    # idx 11: trust_net = -100
    "10", "5", "5",         # idx 14: dealer_net = 5
    "-295",                 # idx 15: total_net = -295
]
_T86_PAYLOAD = {
    "stat": "OK",
    "data": [_T86_ROW_UP, _T86_ROW_DOWN],
}

# ── MI_MARGN sample data ──────────────────────────────────────────────────────

# MI_MARGN actual format: 16+ fields per row
# idx: 0=代號, 1=名稱, 2=融資買進, 3=融資賣出, 4=融資現金償還, 5=融資前日餘額,
#      6=融資今日餘額, 7=融資限額, 8=融券賣出, 9=融券買進, 10=融券現金償還,
#      11=融券前日餘額, 12=融券今日餘額, 13=融券限額, 14=資券互抵, 15=備註
_MARGIN_ROW = [
    "2330", "台積電",
    "5000", "3000", "0",   # idx 2-4: 融資買進/賣出/現金償還
    "10000",               # idx 5: 融資前日餘額
    "12000",               # idx 6: margin_balance ← 融資今日餘額
    "50000",               # idx 7: 融資限額
    "1000", "800", "0",    # idx 8-10: 融券賣出/買進/現金償還
    "400",                 # idx 11: 融券前日餘額
    "500",                 # idx 12: short_balance ← 融券今日餘額
    "5000",                # idx 13: 融券限額
    "200",                 # idx 14: 資券互抵
    "",                    # idx 15: 備註
]
_MARGIN_PAYLOAD = {
    "stat": "OK",
    "tables": [
        {"title": "融資融券彙總", "fields": ["代號", "名稱"], "data": [_MARGIN_ROW]},
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# Unit: helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestParseNum:
    def test_positive_integer_string(self):
        assert _parse_num("12,345") == 12345.0

    def test_negative_string(self):
        assert _parse_num("-200") == -200.0

    def test_float_string(self):
        assert _parse_num("1,234.5") == 1234.5

    def test_plain_int(self):
        assert _parse_num(9999) == 9999.0

    def test_zero_string(self):
        assert _parse_num("0") == 0.0

    def test_none_returns_none(self):
        assert _parse_num(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_num("") is None

    def test_non_numeric_string_returns_none(self):
        assert _parse_num("N/A") is None

    def test_whitespace_stripped(self):
        assert _parse_num(" 100 ") == 100.0


class TestToApiDate:
    def test_basic_conversion(self):
        assert _to_api_date("2026-03-03") == "20260303"

    def test_year_end(self):
        assert _to_api_date("2025-12-31") == "20251231"

    def test_no_dashes(self):
        assert _to_api_date("20260303") == "20260303"


# ══════════════════════════════════════════════════════════════════════════════
# Unit: ensure_schema
# ══════════════════════════════════════════════════════════════════════════════

class TestEnsureSchema:
    def test_creates_institution_flows_table(self):
        c = sqlite3.connect(":memory:")
        ensure_schema(c)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "eod_institution_flows" in tables
        c.close()

    def test_creates_margin_data_table(self):
        c = sqlite3.connect(":memory:")
        ensure_schema(c)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "eod_margin_data" in tables
        c.close()

    def test_idempotent(self):
        c = sqlite3.connect(":memory:")
        ensure_schema(c)
        ensure_schema(c)  # should not raise
        c.close()


# ══════════════════════════════════════════════════════════════════════════════
# Unit: fetch_institution_flows
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchInstitutionFlows:
    def test_parses_rows_correctly(self):
        with patch("urllib.request.urlopen", return_value=_fake_response(_T86_PAYLOAD)):
            rows = fetch_institution_flows("2026-03-03")
        assert len(rows) == 2
        r = rows[0]
        assert r["symbol"] == "2330"
        assert r["name"] == "台積電"
        assert r["foreign_net"] == 550.0
        assert r["trust_net"] == 100.0
        assert r["dealer_net"] == 60.0
        assert r["total_net"] == 710.0

    def test_parses_negative_values(self):
        with patch("urllib.request.urlopen", return_value=_fake_response(_T86_PAYLOAD)):
            rows = fetch_institution_flows("2026-03-03")
        r = rows[1]
        assert r["symbol"] == "2412"
        assert r["foreign_net"] == -200.0
        assert r["total_net"] == -295.0

    def test_returns_empty_on_no_data_stat(self):
        payload = {"stat": "no data", "data": []}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-03-01")
        assert rows == []

    def test_returns_empty_on_twse_chinese_message(self):
        payload = {"stat": "很抱歉，沒有符合條件的資料！"}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-01-01")
        assert rows == []

    def test_returns_empty_on_status_no_data(self):
        payload = {"status": "no data"}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-01-01")
        assert rows == []

    def test_returns_empty_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            rows = fetch_institution_flows("2026-03-03")
        assert rows == []

    def test_returns_empty_on_json_decode_error(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            rows = fetch_institution_flows("2026-03-03")
        assert rows == []

    def test_returns_empty_on_connection_error(self):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            rows = fetch_institution_flows("2026-03-03")
        assert rows == []

    def test_skips_rows_with_non_numeric_symbol(self):
        payload = {
            "stat": "OK",
            "data": [
                ["合計", "全市場", *["0"] * 14],  # summary row — should be skipped
                _T86_ROW_UP,
            ],
        }
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-03-03")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "2330"

    def test_skips_short_rows(self):
        payload = {
            "stat": "OK",
            "data": [
                ["2330", "台積電"],  # too short
                _T86_ROW_UP,
            ],
        }
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-03-03")
        assert len(rows) == 1

    def test_empty_data_list(self):
        payload = {"stat": "OK", "data": []}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-03-03")
        assert rows == []

    def test_missing_data_key(self):
        payload = {"stat": "OK"}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_institution_flows("2026-03-03")
        assert rows == []

    def test_url_contains_correct_date(self):
        captured = []

        def capture_urlopen(req, **kwargs):
            captured.append(req.full_url)
            return _fake_response({"stat": "no data"})

        with patch("urllib.request.urlopen", side_effect=capture_urlopen):
            fetch_institution_flows("2026-03-03")

        assert "20260303" in captured[0]
        assert "T86" in captured[0]


# ══════════════════════════════════════════════════════════════════════════════
# Unit: fetch_margin_data
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchMarginData:
    def test_parses_rows_correctly(self):
        with patch("urllib.request.urlopen", return_value=_fake_response(_MARGIN_PAYLOAD)):
            rows = fetch_margin_data("2026-03-03")
        assert len(rows) == 1
        r = rows[0]
        assert r["symbol"] == "2330"
        assert r["name"] == "台積電"
        assert r["margin_balance"] == 12000.0
        assert r["short_balance"] == 500.0

    def test_returns_empty_on_no_data(self):
        payload = {"stat": "no data"}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_margin_data("2026-03-01")
        assert rows == []

    def test_returns_empty_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            rows = fetch_margin_data("2026-03-03")
        assert rows == []

    def test_returns_empty_on_timeout(self):
        import socket
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timeout")):
            rows = fetch_margin_data("2026-03-03")
        assert rows == []

    def test_skips_short_rows(self):
        payload = {"stat": "OK", "tables": [
            {"fields": ["代號", "名稱"], "data": [["2330", "台積電"]]}
        ]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_margin_data("2026-03-03")
        assert rows == []

    def test_skips_non_numeric_symbol(self):
        payload = {
            "stat": "OK",
            "tables": [{"fields": ["代號", "名稱"], "data": [
                ["上市合計", "全市場", *["0"] * 14],
                _MARGIN_ROW,
            ]}],
        }
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_margin_data("2026-03-03")
        assert len(rows) == 1

    def test_url_contains_correct_date_and_endpoint(self):
        captured = []

        def capture(req, **kwargs):
            captured.append(req.full_url)
            return _fake_response({"stat": "no data"})

        with patch("urllib.request.urlopen", side_effect=capture):
            fetch_margin_data("2026-03-03")

        assert "20260303" in captured[0]
        assert "MI_MARGN" in captured[0]

    def test_zero_balances_allowed(self):
        row = [*_MARGIN_ROW]
        row[6] = "0"   # margin_balance at idx 6
        row[12] = "0"  # short_balance at idx 12
        payload = {"stat": "OK", "tables": [
            {"fields": ["代號", "名稱"], "data": [row]}
        ]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            rows = fetch_margin_data("2026-03-03")
        assert rows[0]["margin_balance"] == 0.0
        assert rows[0]["short_balance"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Unit: save_institution_flows
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveInstitutionFlows:
    def test_saves_rows(self, conn):
        rows = [
            {"symbol": "2330", "name": "台積電", "foreign_net": 550, "trust_net": 100,
             "dealer_net": 60, "total_net": 710},
        ]
        n = save_institution_flows(conn, "2026-03-03", rows)
        assert n == 1
        r = conn.execute(
            "SELECT * FROM eod_institution_flows WHERE trade_date='2026-03-03'"
        ).fetchone()
        assert r["symbol"] == "2330"
        assert r["total_net"] == 710

    def test_upserts_on_duplicate(self, conn):
        rows = [{"symbol": "2330", "name": "台積電", "foreign_net": 100,
                 "trust_net": 0, "dealer_net": 0, "total_net": 100}]
        save_institution_flows(conn, "2026-03-03", rows)
        rows[0]["total_net"] = 200
        save_institution_flows(conn, "2026-03-03", rows)
        count = conn.execute(
            "SELECT COUNT(*) FROM eod_institution_flows WHERE trade_date='2026-03-03'"
        ).fetchone()[0]
        assert count == 1
        val = conn.execute(
            "SELECT total_net FROM eod_institution_flows WHERE trade_date='2026-03-03'"
        ).fetchone()[0]
        assert val == 200

    def test_empty_rows_returns_zero(self, conn):
        n = save_institution_flows(conn, "2026-03-03", [])
        assert n == 0

    def test_saves_multiple_rows(self, conn):
        rows = [
            {"symbol": "2330", "name": "A", "foreign_net": 1, "trust_net": 1, "dealer_net": 1, "total_net": 3},
            {"symbol": "2412", "name": "B", "foreign_net": -1, "trust_net": -1, "dealer_net": -1, "total_net": -3},
        ]
        n = save_institution_flows(conn, "2026-03-03", rows)
        assert n == 2

    def test_null_values_allowed(self, conn):
        rows = [{"symbol": "9999", "name": None, "foreign_net": None,
                 "trust_net": None, "dealer_net": None, "total_net": None}]
        n = save_institution_flows(conn, "2026-03-03", rows)
        assert n == 1


# ══════════════════════════════════════════════════════════════════════════════
# Unit: save_margin_data
# ══════════════════════════════════════════════════════════════════════════════

class TestSaveMarginData:
    def test_saves_row(self, conn):
        rows = [{"symbol": "2330", "name": "台積電", "margin_balance": 12000, "short_balance": 500}]
        n = save_margin_data(conn, "2026-03-03", rows)
        assert n == 1
        r = conn.execute(
            "SELECT * FROM eod_margin_data WHERE trade_date='2026-03-03'"
        ).fetchone()
        assert r["margin_balance"] == 12000
        assert r["short_balance"] == 500

    def test_upserts_on_duplicate(self, conn):
        rows = [{"symbol": "2330", "name": "台積電", "margin_balance": 5000, "short_balance": 100}]
        save_margin_data(conn, "2026-03-03", rows)
        rows[0]["margin_balance"] = 9999
        save_margin_data(conn, "2026-03-03", rows)
        val = conn.execute(
            "SELECT margin_balance FROM eod_margin_data WHERE trade_date='2026-03-03' AND symbol='2330'"
        ).fetchone()[0]
        assert val == 9999

    def test_empty_rows_returns_zero(self, conn):
        n = save_margin_data(conn, "2026-03-03", [])
        assert n == 0


# ══════════════════════════════════════════════════════════════════════════════
# Integration: run_daily_fetch
# ══════════════════════════════════════════════════════════════════════════════

class TestRunDailyFetch:
    def _urlopen_side_effect(self, t86_payload, margin_payload):
        """Returns alternating responses for T86 then MI_MARGN calls."""
        calls = []

        def side_effect(req, **kwargs):
            url = req.full_url
            if "T86" in url:
                return _fake_response(t86_payload)
            if "MI_MARGN" in url:
                return _fake_response(margin_payload)
            return _fake_response({"stat": "no data"})

        return side_effect

    def test_writes_both_tables(self, conn):
        side_effect = self._urlopen_side_effect(_T86_PAYLOAD, _MARGIN_PAYLOAD)
        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-03-03", conn)

        assert result["institution_flows"] == 2
        assert result["margin_data"] == 1

    def test_continues_if_institution_fetch_fails(self, conn):
        calls = []

        def side_effect(req, **kwargs):
            url = req.full_url
            if "T86" in url:
                raise urllib.error.URLError("T86 down")
            return _fake_response(_MARGIN_PAYLOAD)

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-03-03", conn)

        assert result["institution_flows"] == 0
        assert result["margin_data"] == 1  # margin still saved

    def test_continues_if_margin_fetch_fails(self, conn):
        def side_effect(req, **kwargs):
            if "T86" in req.full_url:
                return _fake_response(_T86_PAYLOAD)
            raise urllib.error.URLError("MI_MARGN down")

        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-03-03", conn)

        assert result["institution_flows"] == 2
        assert result["margin_data"] == 0  # institution still saved

    def test_returns_zero_when_both_fail(self, conn):
        with patch("urllib.request.urlopen", side_effect=ConnectionError("all down")):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-03-03", conn)

        assert result["institution_flows"] == 0
        assert result["margin_data"] == 0

    def test_idempotent_on_same_date(self, conn):
        side_effect = self._urlopen_side_effect(_T86_PAYLOAD, _MARGIN_PAYLOAD)
        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep"):
                run_daily_fetch("2026-03-03", conn)

        side_effect2 = self._urlopen_side_effect(_T86_PAYLOAD, _MARGIN_PAYLOAD)
        with patch("urllib.request.urlopen", side_effect=side_effect2):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-03-03", conn)

        count = conn.execute(
            "SELECT COUNT(*) FROM eod_institution_flows WHERE trade_date='2026-03-03'"
        ).fetchone()[0]
        assert count == 2  # upsert, not duplicate

    def test_uses_sleep_between_requests(self, conn):
        side_effect = self._urlopen_side_effect(_T86_PAYLOAD, _MARGIN_PAYLOAD)
        with patch("urllib.request.urlopen", side_effect=side_effect):
            with patch("time.sleep") as mock_sleep:
                run_daily_fetch("2026-03-03", conn)
        mock_sleep.assert_called_once_with(1)

    def test_non_trading_day_returns_zero(self, conn):
        no_data = {"stat": "no data"}
        with patch("urllib.request.urlopen", return_value=_fake_response(no_data)):
            with patch("time.sleep"):
                result = run_daily_fetch("2026-01-01", conn)

        assert result["institution_flows"] == 0
        assert result["margin_data"] == 0


# ── Regression: TPEx market preservation in Yahoo fallback (#481) ──────────


class TestTPExYahooFallback:
    """TPEx symbols must use .TWO suffix and preserve market='TPEx' on insert."""

    @pytest.fixture
    def conn_with_tpex(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        ensure_schema(c)
        c.execute("""
            CREATE TABLE IF NOT EXISTS eod_prices (
                trade_date TEXT NOT NULL,
                market TEXT NOT NULL DEFAULT 'TWSE',
                symbol TEXT NOT NULL,
                name TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER DEFAULT 0,
                source_url TEXT,
                ingested_at TEXT,
                PRIMARY KEY (trade_date, symbol)
            )
        """)
        c.execute(
            """INSERT INTO eod_prices
               (trade_date, market, symbol, open, high, low, close, volume)
               VALUES ('2026-03-27', 'TPEx', '6515', 100, 110, 95, 105, 1000)"""
        )
        c.commit()
        return c

    def test_yahoo_url_uses_two_suffix_for_tpex(self):
        """fetch_ohlcv_yahoo must call .TWO URL for TPEx symbols."""
        yahoo_resp = {
            "chart": {
                "result": [{
                    "timestamp": [1711500000],
                    "indicators": {"quote": [{"open": [100], "high": [110], "low": [95], "close": [105], "volume": [1000]}]},
                }]
            }
        }
        urls_called = []

        def fake_urlopen(req, **kwargs):
            urls_called.append(req.full_url)
            return _fake_response(yahoo_resp)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            fetch_ohlcv_yahoo(["6515"], market_map={"6515": "TPEx"})

        assert len(urls_called) == 1
        assert ".TWO" in urls_called[0], f"Expected .TWO in URL but got: {urls_called[0]}"

    def test_yahoo_url_uses_tw_suffix_for_twse(self):
        """fetch_ohlcv_yahoo must call .TW URL for TWSE symbols."""
        yahoo_resp = {
            "chart": {
                "result": [{
                    "timestamp": [1711500000],
                    "indicators": {"quote": [{"open": [500], "high": [510], "low": [490], "close": [505], "volume": [5000]}]},
                }]
            }
        }
        urls_called = []

        def fake_urlopen(req, **kwargs):
            urls_called.append(req.full_url)
            return _fake_response(yahoo_resp)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            fetch_ohlcv_yahoo(["2330"], market_map={"2330": "TWSE"})

        assert len(urls_called) == 1
        assert ".TW?" in urls_called[0], f"Expected .TW in URL but got: {urls_called[0]}"

    def test_run_daily_fetch_preserves_tpex_market(self, conn_with_tpex):
        """Yahoo fallback for TPEx symbol must write market='TPEx', not 'TWSE'."""
        yahoo_resp = {
            "chart": {
                "result": [{
                    "timestamp": [1711500000],
                    "indicators": {"quote": [{"open": [100], "high": [110], "low": [95], "close": [108], "volume": [2000]}]},
                }]
            }
        }
        twse_err = urllib.error.HTTPError(
            "http://twse", 404, "Not Found", {}, BytesIO(b"")
        )

        def fake_urlopen(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "twse" in url.lower() or "tse.com" in url.lower():
                raise twse_err
            return _fake_response(yahoo_resp)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            result = run_daily_fetch("2026-03-28", conn_with_tpex, ohlcv_symbols=["6515"])

        assert result["ohlcv"] >= 1
        row = conn_with_tpex.execute(
            "SELECT market FROM eod_prices WHERE symbol='6515' ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        assert row["market"] == "TPEx", f"Expected TPEx but got {row['market']}"

    def test_tpex_symbols_skip_twse_stock_day(self, conn_with_tpex):
        """TPEx symbols should NOT attempt TWSE STOCK_DAY — go directly to Yahoo."""
        yahoo_resp = {
            "chart": {
                "result": [{
                    "timestamp": [1711500000],
                    "indicators": {"quote": [{"open": [100], "high": [110], "low": [95], "close": [108], "volume": [2000]}]},
                }]
            }
        }
        stock_day_called = []

        def fake_urlopen(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "STOCK_DAY" in url:
                stock_day_called.append(url)
            return _fake_response(yahoo_resp)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            run_daily_fetch("2026-03-28", conn_with_tpex, ohlcv_symbols=["6515"])

        assert stock_day_called == [], f"STOCK_DAY should not be called for TPEx, but was: {stock_day_called}"
