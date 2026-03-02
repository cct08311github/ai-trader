import json
import sqlite3
import sys
import types
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openclaw.eod_ingest import (
    EODRow,
    _fetch_text,
    _to_float,
    _extract_trade_date_from_payload,
    _find_tpex_header,
    fetch_twse_rows,
    fetch_tpex_rows,
    upsert_eod_rows,
    record_run,
    apply_migration_if_needed,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE eod_prices (
          trade_date TEXT NOT NULL,
          market TEXT NOT NULL,
          symbol TEXT NOT NULL,
          name TEXT,
          close REAL,
          change REAL,
          open REAL,
          high REAL,
          low REAL,
          volume REAL,
          turnover REAL,
          trades REAL,
          source_url TEXT NOT NULL,
          ingested_at TEXT NOT NULL,
          PRIMARY KEY (trade_date, market, symbol)
        );
        """
    )
    return conn


def test_to_float_parsing():
    assert _to_float("1,234.5") == 1234.5
    assert _to_float("--") is None
    assert _to_float("+12.5") == 12.5


def test_upsert_eod_rows():
    conn = _conn()
    row = EODRow(
        trade_date="2026-02-27",
        market="TWSE",
        symbol="2330",
        name="TSMC",
        close=1000.0,
        change=10.0,
        open=990.0,
        high=1005.0,
        low=985.0,
        volume=1000000,
        turnover=1000000000,
        trades=12345,
        source_url="x",
    )
    n1 = upsert_eod_rows(conn, [row])
    assert n1 == 1
    row.close = 1001.0
    n2 = upsert_eod_rows(conn, [row])
    assert n2 == 1
    out = conn.execute("SELECT close FROM eod_prices WHERE symbol='2330'").fetchone()[0]
    assert out == 1001.0

def test_to_float_empty():
    """邊界測試：空字符串和 None。"""
    assert _to_float("") is None
    assert _to_float(None) is None


def test_to_float_scientific():
    """正向測試：科學記號。"""
    assert _to_float("1.23e5") == 123000.0
    assert _to_float("2.5E-3") == 0.0025


def test_upsert_eod_rows_empty():
    """反向測試：空行列表。"""
    conn = _conn()
    n = upsert_eod_rows(conn, [])
    assert n == 0


def test_fetch_tpex_rows_column_mapping():
    """TPEx CSV col[7]=均價 應被跳過，volume=col[8], turnover=col[9], trades=col[10]。"""
    # 19-col TPEx CSV header + 1 trading row + 1 non-trading row
    fake_csv = (
        "日期,2026/03/02\n"
        "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元),成交筆數,"
        "最後買價,最後買量(千股),最後賣價,最後賣量(千股),發行股數,次日參考價,次日漲停價,次日跌停價\n"
        "006201,元大富櫃50,31.41,-0.02,31.10,31.56,30.50,31.16,\"137,665\",\"4,289,822\",100,31.30,1,31.41,5,18000000,31.41,34.56,28.27\n"
        "2724,藝舍-KY,---,---,---,---,---,18.00,0,0,0,18.00,0,---,0,8000000,18.00,19.79,16.21\n"
    )
    with patch("openclaw.eod_ingest._fetch_text", return_value=fake_csv):
        rows = fetch_tpex_rows("2026-03-02")

    # 未成交標的（2724）已被過濾，只剩有收盤價的標的
    assert len(rows) == 1

    trading = next(r for r in rows if r.symbol == "006201")
    assert trading.close == 31.41
    assert trading.volume == 137665.0     # 成交股數，不是 31.16 (均價)
    assert trading.turnover == 4289822.0  # 成交金額
    assert trading.trades == 100.0        # 成交筆數

    # 未成交標的（close=---）應被過濾，不進入結果
    assert all(r.symbol != "2724" for r in rows), "非交易標的應被過濾掉"
    assert len(rows) == 1


def test_upsert_eod_rows_multiple():
    """正向測試：多行插入。"""
    conn = _conn()
    rows = [
        EODRow(
            trade_date="2026-02-27",
            market="TWSE",
            symbol="2330",
            name="TSMC",
            close=1000.0,
            change=10.0,
            open=990.0,
            high=1005.0,
            low=985.0,
            volume=1000000,
            turnover=1000000000,
            trades=12345,
            source_url="x",
        ),
        EODRow(
            trade_date="2026-02-27",
            market="TWSE",
            symbol="2317",
            name="Foxconn",
            close=200.0,
            change=-5.0,
            open=205.0,
            high=210.0,
            low=198.0,
            volume=500000,
            turnover=100000000,
            trades=5678,
            source_url="x",
        ),
    ]
    n = upsert_eod_rows(conn, rows)
    assert n == 2
    count = conn.execute("SELECT COUNT(*) FROM eod_prices").fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------------------
# _fetch_text — lines 39-42
# ---------------------------------------------------------------------------

class TestFetchText:
    def test_fetch_text_success(self):
        # Lines 39-42: HTTP fetch + decode
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"hello world"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.eod_ingest.urlopen", return_value=mock_resp):
            result = _fetch_text("https://example.com/data.json")
        assert result == "hello world"

    def test_fetch_text_with_encoding(self):
        # encoding param is passed through
        mock_resp = MagicMock()
        mock_resp.read.return_value = "台灣".encode("cp950", errors="replace")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.eod_ingest.urlopen", return_value=mock_resp):
            result = _fetch_text("https://example.com/", encoding="cp950")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _to_float — X/x removal and + stripping (lines 52-53)
# ---------------------------------------------------------------------------

class TestToFloatEdgeCases:
    def test_x_removal(self):
        # Line 52: s.replace("X", "").replace("x", "")
        assert _to_float("1X234") == 1234.0
        assert _to_float("12x34") == 1234.0

    def test_plus_removal(self):
        # Line 53: s.replace("+", "")
        assert _to_float("+500") == 500.0

    def test_special_strings_return_none(self):
        # Line 49: "--", "---", "除權息", "N/A"
        assert _to_float("---") is None
        assert _to_float("除權息") is None
        assert _to_float("N/A") is None

    def test_invalid_after_cleanup_returns_none(self):
        # Line 56-57: ValueError
        assert _to_float("abc") is None


# ---------------------------------------------------------------------------
# _extract_trade_date_from_payload — lines 61-68
# ---------------------------------------------------------------------------

class TestExtractTradeDate:
    def test_extracts_from_Date_key(self):
        # Line 62-67: "Date" key with formatted date
        payload = {"Date": "20260302"}
        result = _extract_trade_date_from_payload(payload)
        assert result == "2026-03-02"

    def test_extracts_from_date_key_with_dashes(self):
        payload = {"date": "2026-03-02"}
        result = _extract_trade_date_from_payload(payload)
        assert result == "2026-03-02"

    def test_extracts_from_chinese_key(self):
        payload = {"資料日期": "2026/03/02"}
        result = _extract_trade_date_from_payload(payload)
        assert result == "2026-03-02"

    def test_returns_none_when_no_valid_key(self):
        # Line 68: no matching key → None
        payload = {"other": "2026-03-02"}
        result = _extract_trade_date_from_payload(payload)
        assert result is None

    def test_returns_none_when_value_does_not_match_regex(self):
        payload = {"Date": "not_a_date"}
        result = _extract_trade_date_from_payload(payload)
        assert result is None

    def test_empty_value_returns_none(self):
        # val is falsy → skipped
        payload = {"Date": "", "date": None}
        result = _extract_trade_date_from_payload(payload)
        assert result is None


# ---------------------------------------------------------------------------
# fetch_twse_rows — lines 72-101
# ---------------------------------------------------------------------------

class TestFetchTwseRows:
    def test_basic_twse_fetch(self):
        # Lines 72-101: fetch, parse, return EODRow list
        items = [
            {
                "Code": "2330",
                "Name": "台積電",
                "Date": "20260302",
                "ClosingPrice": "1000",
                "Change": "+10",
                "OpeningPrice": "990",
                "HighestPrice": "1005",
                "LowestPrice": "985",
                "TradeVolume": "1000000",
                "TradeValue": "1000000000",
                "Transaction": "12345",
            }
        ]
        with patch("openclaw.eod_ingest._fetch_text", return_value=json.dumps(items)):
            rows = fetch_twse_rows("2026-03-02")
        assert len(rows) == 1
        assert rows[0].symbol == "2330"
        assert rows[0].close == 1000.0
        assert rows[0].market == "TWSE"
        assert rows[0].trade_date == "2026-03-02"

    def test_skips_item_without_symbol(self):
        # Line 76-78: no symbol → skip
        items = [
            {"Code": "", "ClosingPrice": "100"},
            {"Code": "2317", "Name": "Foxconn", "ClosingPrice": "200"},
        ]
        with patch("openclaw.eod_ingest._fetch_text", return_value=json.dumps(items)):
            rows = fetch_twse_rows("2026-03-02")
        # Only 2317 should be included
        assert all(r.symbol == "2317" for r in rows)

    def test_skips_item_without_close_price(self):
        # Line 82-83: close is None → skip (停牌)
        items = [
            {"Code": "9999", "Name": "Suspended", "ClosingPrice": "--"},
        ]
        with patch("openclaw.eod_ingest._fetch_text", return_value=json.dumps(items)):
            rows = fetch_twse_rows("2026-03-02")
        assert len(rows) == 0

    def test_uses_fallback_trade_date(self):
        # Line 80: _extract_trade_date_from_payload returns None → uses trade_date
        items = [
            {"Code": "2330", "Name": "TSMC", "ClosingPrice": "900"},  # no Date key
        ]
        with patch("openclaw.eod_ingest._fetch_text", return_value=json.dumps(items)):
            rows = fetch_twse_rows("2026-03-02")
        assert rows[0].trade_date == "2026-03-02"

    def test_uses_chinese_field_names(self):
        # Also test alternate Chinese key names
        items = [
            {
                "證券代號": "2412",
                "證券名稱": "中華電",
                "收盤價": "120.5",
                "漲跌價差": "-0.5",
                "開盤價": "121",
                "最高價": "122",
                "最低價": "119",
                "成交股數": "500000",
                "成交金額": "60000000",
                "成交筆數": "5000",
            }
        ]
        with patch("openclaw.eod_ingest._fetch_text", return_value=json.dumps(items)):
            rows = fetch_twse_rows("2026-03-02")
        assert len(rows) == 1
        assert rows[0].symbol == "2412"
        assert rows[0].close == 120.5


# ---------------------------------------------------------------------------
# _find_tpex_header — no header (line 108)
# ---------------------------------------------------------------------------

class TestFindTpexHeader:
    def test_finds_header(self):
        lines = [
            "日期,2026/03/02",
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數",
        ]
        header = _find_tpex_header(lines)
        assert header is not None
        assert "代號" in header

    def test_returns_none_when_no_matching_line(self):
        # Line 108: no line contains all three markers (代號 + 名稱 + 收盤)
        lines = [
            "日期,2026/03/02",
            "只有 code 但無 name 或 price",
        ]
        header = _find_tpex_header(lines)
        assert header is None


# ---------------------------------------------------------------------------
# fetch_tpex_rows edge cases — lines 116, 127, 130, 133
# ---------------------------------------------------------------------------

class TestFetchTpexRowsEdgeCases:
    def test_no_header_returns_empty(self):
        # Line 116: no header → return []
        fake_csv = "日期,2026/03/02\n只有日期，沒有欄位標頭\n"
        with patch("openclaw.eod_ingest._fetch_text", return_value=fake_csv):
            rows = fetch_tpex_rows("2026-03-02")
        assert rows == []

    def test_skips_lines_without_4_digits(self):
        # Line 127: no \d{4} in line → continue
        fake_csv = (
            "日期,2026/03/02\n"
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元),成交筆數\n"
            "本行沒有四位數字\n"  # no 4-digit number → skipped
            "2330,台積電,1000,+10,990,1005,985,992,1000000,1000000000,12345\n"
        )
        with patch("openclaw.eod_ingest._fetch_text", return_value=fake_csv):
            rows = fetch_tpex_rows("2026-03-02")
        # Only 2330 should be included
        assert all(r.symbol == "2330" for r in rows)

    def test_skips_rows_with_fewer_than_8_columns(self):
        # Line 130: len(row) < 8 → continue
        fake_csv = (
            "日期,2026/03/02\n"
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元),成交筆數\n"
            "2330,台積電,1000\n"  # only 3 cols → < 8
        )
        with patch("openclaw.eod_ingest._fetch_text", return_value=fake_csv):
            rows = fetch_tpex_rows("2026-03-02")
        assert rows == []

    def test_skips_rows_with_non_numeric_symbol(self):
        # Line 133: symbol not matching ^\d{4,6}$ → continue
        fake_csv = (
            "日期,2026/03/02\n"
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元),成交筆數\n"
            "ABCD,SomeCompany,100,0,99,101,98,100,10000,1000000,500\n"
        )
        with patch("openclaw.eod_ingest._fetch_text", return_value=fake_csv):
            rows = fetch_tpex_rows("2026-03-02")
        assert rows == []


# ---------------------------------------------------------------------------
# record_run — line 218
# ---------------------------------------------------------------------------

def _conn_with_run_table() -> sqlite3.Connection:
    """In-memory DB with eod_ingest_runs table."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE eod_ingest_runs (
            run_id TEXT PRIMARY KEY,
            trade_date TEXT,
            status TEXT,
            twse_rows INTEGER,
            tpex_rows INTEGER,
            error_text TEXT
        );
    """)
    return conn


class TestRecordRun:
    def test_record_run_inserts(self):
        # Line 218: record_run inserts a row
        conn = _conn_with_run_table()
        record_run(
            conn,
            trade_date="2026-03-02",
            status="success",
            twse_rows=100,
            tpex_rows=50,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM eod_ingest_runs").fetchone()
        assert row is not None
        assert row[1] == "2026-03-02"
        assert row[2] == "success"

    def test_record_run_with_error(self):
        conn = _conn_with_run_table()
        record_run(
            conn,
            trade_date="2026-03-02",
            status="failed",
            twse_rows=0,
            tpex_rows=0,
            error_text="network error",
        )
        conn.commit()
        row = conn.execute("SELECT * FROM eod_ingest_runs").fetchone()
        assert row[2] == "failed"
        assert row[5] == "network error"


# ---------------------------------------------------------------------------
# apply_migration_if_needed — lines 228-229
# ---------------------------------------------------------------------------

class TestApplyMigrationIfNeeded:
    def test_executes_sql_script(self, tmp_path):
        # Lines 228-229: read SQL file and executescript
        sql_file = tmp_path / "migration.sql"
        sql_file.write_text(
            "CREATE TABLE IF NOT EXISTS test_migration (id INTEGER PRIMARY KEY);",
            encoding="utf-8",
        )
        conn = sqlite3.connect(":memory:")
        apply_migration_if_needed(conn, sql_file)
        # Table should exist now
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_migration'"
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# main() function — lines 233-281
# ---------------------------------------------------------------------------

def _make_eod_db_for_main(db_path: Path) -> None:
    """Create a minimal SQLite DB with required tables for main()."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT NOT NULL,
            market TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            close REAL,
            change REAL,
            open REAL,
            high REAL,
            low REAL,
            volume REAL,
            turnover REAL,
            trades REAL,
            source_url TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            PRIMARY KEY (trade_date, market, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_ingest_runs (
            run_id TEXT PRIMARY KEY,
            trade_date TEXT,
            status TEXT,
            twse_rows INTEGER,
            tpex_rows INTEGER,
            error_text TEXT
        );
    """)
    conn.commit()
    conn.close()


class TestMain:
    def test_main_success(self, tmp_path, capsys):
        # Lines 233-265: main() success path
        db_path = tmp_path / "test.db"
        _make_eod_db_for_main(db_path)

        twse_items = [
            {
                "Code": "2330",
                "Name": "台積電",
                "ClosingPrice": "1000",
                "Change": "+10",
                "OpeningPrice": "990",
                "HighestPrice": "1005",
                "LowestPrice": "985",
                "TradeVolume": "1000000",
                "TradeValue": "1000000000",
                "Transaction": "12345",
            }
        ]
        tpex_csv = (
            "日期,2026/03/02\n"
            "代號,名稱,收盤,漲跌,開盤,最高,最低,均價,成交股數,成交金額(元),成交筆數\n"
            "006201,元大富櫃50,31.41,-0.02,31.10,31.56,30.50,31.16,137665,4289822,100\n"
        )

        with patch("openclaw.eod_ingest._fetch_text") as mock_fetch, \
             patch("sys.argv", ["eod_ingest", "--db", str(db_path), "--trade-date", "2026-03-02"]):
            # First call is TWSE (JSON), second is TPEx (CSV)
            mock_fetch.side_effect = [json.dumps(twse_items), tpex_csv]
            from openclaw.eod_ingest import main
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "success"
        assert output["twse_rows"] == 1
        assert output["tpex_rows"] == 1

    def test_main_with_apply_migration(self, tmp_path, capsys):
        # Lines 244-246: --apply-migration path
        db_path = tmp_path / "test2.db"
        _make_eod_db_for_main(db_path)

        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        migration_sql = sql_dir / "migration_v1_2_1_eod_data.sql"
        migration_sql.write_text("-- no-op migration\n", encoding="utf-8")

        twse_items = []
        tpex_csv = "日期,2026/03/02\nOnly date line, no header\n"

        with patch("openclaw.eod_ingest._fetch_text") as mock_fetch, \
             patch("sys.argv", ["eod_ingest", "--db", str(db_path),
                                "--trade-date", "2026-03-02", "--apply-migration"]), \
             patch("openclaw.eod_ingest.Path") as mock_path_cls:
            # Make apply_migration_if_needed use our sql file path
            mock_fetch.side_effect = [json.dumps(twse_items), tpex_csv]
            # Patch the sql path resolution
            mock_path_cls.return_value.resolve.return_value = db_path
            # We need to actually mock the sql path construction
            from openclaw.eod_ingest import main
            with patch("openclaw.eod_ingest.apply_migration_if_needed"):
                with patch("openclaw.eod_ingest.Path", side_effect=lambda x: Path(x)):
                    main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "success"

    def test_main_failure_raises(self, tmp_path, capsys):
        # Lines 266-279: exception path — rollback + re-raise
        db_path = tmp_path / "test3.db"
        _make_eod_db_for_main(db_path)

        with patch("openclaw.eod_ingest._fetch_text", side_effect=RuntimeError("network down")), \
             patch("sys.argv", ["eod_ingest", "--db", str(db_path), "--trade-date", "2026-03-02"]):
            from openclaw.eod_ingest import main
            with pytest.raises(RuntimeError, match="network down"):
                main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "failed"
        assert "network down" in output["error"]


# ---------------------------------------------------------------------------
# __main__ entry point — line 296
# ---------------------------------------------------------------------------

class TestMainEntryPoint:
    def test_main_guard_executes(self, tmp_path, capsys):
        # Line 296: if __name__ == "__main__": main()
        # Use runpy.run_path with urlopen patched at urllib level so it applies to
        # the new execution namespace created by runpy.
        import runpy
        import openclaw.eod_ingest as eod_module

        db_path = tmp_path / "entry.db"
        _make_eod_db_for_main(db_path)

        twse_items: list = []
        tpex_csv = "日期,2026/03/02\n\n"

        # Build fake responses for TWSE (JSON bytes) and TPEx (CSV cp950 bytes)
        twse_bytes = json.dumps(twse_items).encode("utf-8")
        tpex_bytes = tpex_csv.encode("cp950")

        class FakeResp:
            def __init__(self, data: bytes):
                self._data = data
            def read(self):
                return self._data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        source_file = Path(eod_module.__file__)  # type: ignore[arg-type]
        responses = iter([FakeResp(twse_bytes), FakeResp(tpex_bytes)])

        with patch("urllib.request.urlopen", side_effect=lambda *a, **kw: next(responses)), \
             patch("sys.argv", ["eod_ingest", "--db", str(db_path), "--trade-date", "2026-03-02"]):
            runpy.run_path(str(source_file), run_name="__main__")

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["status"] == "success"
