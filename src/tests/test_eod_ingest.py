import sqlite3
import types
from unittest.mock import patch

from openclaw.eod_ingest import EODRow, _to_float, fetch_tpex_rows, upsert_eod_rows


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
