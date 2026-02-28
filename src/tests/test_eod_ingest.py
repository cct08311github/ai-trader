import sqlite3

from openclaw.eod_ingest import EODRow, _to_float, upsert_eod_rows


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
