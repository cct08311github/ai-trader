"""tests/test_daily_snapshot.py — daily_snapshot 單元測試 [Issue #282]"""
from __future__ import annotations

import sqlite3

import pytest

from openclaw.daily_snapshot import (
    get_nav_history,
    write_nav_snapshot,
)

INITIAL = 1_000_000.0


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    # orders + fills
    conn.execute("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            status TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE fills (
            fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            qty INTEGER,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL
        )
    """)
    conn.execute("""
        CREATE TABLE eod_prices (
            trade_date TEXT,
            symbol TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.commit()
    return conn


def _buy(conn, symbol, qty, price, fee=0.0):
    oid = f"buy-{symbol}-{qty}"
    conn.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?)",
                 (oid, symbol, "buy", qty, price, "filled"))
    conn.execute("INSERT INTO fills (order_id, qty, price, fee, tax) VALUES (?,?,?,?,0)",
                 (oid, qty, price, fee))
    conn.execute("INSERT OR REPLACE INTO positions (symbol, quantity, avg_price) VALUES (?,?,?)",
                 (symbol, qty, price))
    conn.commit()


def _sell(conn, symbol, qty, price, avg_price, fee=0.0, tax=0.0):
    oid = f"sell-{symbol}-{qty}"
    conn.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?)",
                 (oid, symbol, "sell", qty, price, "filled"))
    conn.execute("INSERT INTO fills (order_id, qty, price, fee, tax) VALUES (?,?,?,?,?)",
                 (oid, qty, price, fee, tax))
    # 賣出後清除持倉
    conn.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
    conn.commit()


class TestWriteNavSnapshot:
    def test_no_positions_no_trades(self):
        """無交易無持倉 → NAV ≈ initial_capital。"""
        conn = _make_conn()
        result = write_nav_snapshot(conn, "2024-01-02", INITIAL)
        assert abs(result["nav"] - INITIAL) < 0.01
        assert abs(result["cash"] - INITIAL) < 0.01
        assert result["unrealized_pnl"] == 0.0
        assert result["realized_pnl_cumulative"] == 0.0

    def test_open_position_uses_eod_close(self):
        """有持倉且有 EOD 收盤 → unrealized_pnl 正確。"""
        conn = _make_conn()
        _buy(conn, "2330", 1000, 500.0)
        conn.execute("INSERT INTO eod_prices VALUES ('2024-01-02','2330',0,0,0,520.0,0)")
        conn.commit()
        result = write_nav_snapshot(conn, "2024-01-02", INITIAL)
        # unrealized = (520 - 500) * 1000 = 20,000
        assert abs(result["unrealized_pnl"] - 20_000.0) < 0.01
        # nav = cash + 520*1000
        assert result["nav"] > INITIAL

    def test_open_position_fallback_avg_price_when_no_eod(self):
        """無 EOD 收盤時 fallback avg_price → unrealized = 0。"""
        conn = _make_conn()
        _buy(conn, "0050", 500, 200.0)
        result = write_nav_snapshot(conn, "2024-01-02", INITIAL)
        assert result["unrealized_pnl"] == 0.0

    def test_realized_pnl_after_sell(self):
        """賣出後 realized_pnl_cumulative 正確反映獲利。"""
        conn = _make_conn()
        _buy(conn, "2454", 1000, 100.0)
        _sell(conn, "2454", 1000, 120.0, avg_price=100.0)
        result = write_nav_snapshot(conn, "2024-01-03", INITIAL)
        # 賣出收入 = 120*1000 = 120,000; 買入成本 = 100*1000 = 100,000 → realized = 20,000
        assert result["realized_pnl_cumulative"] > 0

    def test_idempotent_second_call_skips(self):
        """相同 trade_date 第二次呼叫（overwrite=False）應跳過，回傳已有資料。"""
        conn = _make_conn()
        r1 = write_nav_snapshot(conn, "2024-01-02", INITIAL)
        r2 = write_nav_snapshot(conn, "2024-01-02", INITIAL, overwrite=False)
        assert r1["nav"] == r2["nav"]
        count = conn.execute("SELECT COUNT(*) FROM daily_nav WHERE trade_date='2024-01-02'").fetchone()[0]
        assert count == 1

    def test_overwrite_updates_record(self):
        """overwrite=True 應覆蓋既有記錄。"""
        conn = _make_conn()
        write_nav_snapshot(conn, "2024-01-02", INITIAL)
        # 加入持倉後強制覆蓋
        _buy(conn, "2330", 1000, 500.0)
        conn.execute("INSERT INTO eod_prices VALUES ('2024-01-02','2330',0,0,0,600.0,0)")
        conn.commit()
        r2 = write_nav_snapshot(conn, "2024-01-02", INITIAL, overwrite=True)
        assert r2["unrealized_pnl"] == 100_000.0  # (600-500)*1000

    def test_table_created_automatically(self):
        """daily_nav 表不存在時應自動建立。"""
        conn = _make_conn()
        write_nav_snapshot(conn, "2024-01-02", INITIAL)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "daily_nav" in tables

    def test_result_dict_has_required_keys(self):
        conn = _make_conn()
        result = write_nav_snapshot(conn, "2024-01-02", INITIAL)
        for key in ("trade_date", "nav", "cash", "unrealized_pnl", "realized_pnl_cumulative"):
            assert key in result


class TestGetNavHistory:
    def test_returns_chronological_order(self):
        conn = _make_conn()
        for d in ("2024-01-02", "2024-01-03", "2024-01-04"):
            write_nav_snapshot(conn, d, INITIAL, overwrite=True)
        history = get_nav_history(conn, days=10)
        dates = [r["trade_date"] for r in history]
        assert dates == sorted(dates)

    def test_limits_results(self):
        conn = _make_conn()
        for i in range(5):
            write_nav_snapshot(conn, f"2024-01-0{i+2}", INITIAL, overwrite=True)
        assert len(get_nav_history(conn, days=3)) == 3

    def test_empty_returns_empty_list(self):
        conn = _make_conn()
        assert get_nav_history(conn) == []
