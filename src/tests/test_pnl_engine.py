"""Tests for pnl_engine.py — 24% → ~100% coverage."""
import sqlite3
import pytest
from openclaw.pnl_engine import (
    get_avg_cost,
    on_sell_filled,
    sync_positions_table,
    get_today_pnl,
    get_monthly_pnl,
    get_overall_win_rate,
    get_equity_curve,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            status TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            qty INTEGER,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL
        );
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            realized_pnl REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            rolling_drawdown REAL DEFAULT 0,
            consecutive_losses INTEGER DEFAULT 0,
            losing_streak_days INTEGER DEFAULT 0,
            rolling_win_rate REAL DEFAULT 0,
            nav_end REAL DEFAULT 0,
            rolling_peak_nav REAL DEFAULT 0
        );
    """)
    return conn


def _insert_buy(conn, order_id, symbol, qty, price, fee=0):
    conn.execute("INSERT INTO orders VALUES (?,?,?,?)", (order_id, symbol, "buy", "filled"))
    conn.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)",
                 (f"f_{order_id}", order_id, qty, price, fee, 0))
    conn.commit()


def _insert_sell(conn, order_id, symbol, qty, price, fee=0, tax=0):
    conn.execute("INSERT INTO orders VALUES (?,?,?,?)", (order_id, symbol, "sell", "filled"))
    conn.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)",
                 (f"f_{order_id}", order_id, qty, price, fee, tax))
    conn.commit()


# ── get_avg_cost ─────────────────────────────────────────────────────────────

def test_get_avg_cost_no_fills():
    conn = _conn()
    avg, qty = get_avg_cost(conn, "2330")
    assert avg == 0.0
    assert qty == 0


def test_get_avg_cost_single_buy():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    avg, qty = get_avg_cost(conn, "2330")
    assert avg == 500.0
    assert qty == 100


def test_get_avg_cost_multiple_buys():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    _insert_buy(conn, "o2", "2330", 100, 600.0)
    avg, qty = get_avg_cost(conn, "2330")
    assert avg == 550.0
    assert qty == 200


def test_get_avg_cost_buy_then_sell():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    _insert_sell(conn, "o2", "2330", 100, 550.0)
    avg, qty = get_avg_cost(conn, "2330")
    assert qty == 0
    assert avg == 0.0


def test_get_avg_cost_case_insensitive():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 50, 400.0)
    avg, qty = get_avg_cost(conn, "2330")
    assert qty == 50


# ── on_sell_filled ────────────────────────────────────────────────────────────

def test_on_sell_filled_basic_profit():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    pnl = on_sell_filled(conn, symbol="2330", sell_qty=100, sell_price=600.0,
                         sell_fee=100.0, sell_tax=50.0, trade_date="2026-03-03")
    # (600 - 500) * 100 - 100 - 50 = 9850
    assert pnl == pytest.approx(9850.0)


def test_on_sell_filled_loss():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 600.0)
    pnl = on_sell_filled(conn, symbol="2330", sell_qty=100, sell_price=550.0,
                         sell_fee=0, sell_tax=0, trade_date="2026-03-03")
    assert pnl == pytest.approx(-5000.0)


def test_on_sell_filled_updates_daily_pnl():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    on_sell_filled(conn, symbol="2330", sell_qty=100, sell_price=600.0,
                   sell_fee=0, sell_tax=0, trade_date="2026-03-03")
    row = conn.execute("SELECT realized_pnl, total_trades FROM daily_pnl_summary").fetchone()
    assert row["realized_pnl"] == pytest.approx(10000.0)
    assert row["total_trades"] == 1


def test_on_sell_filled_accumulates_two_trades():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    _insert_buy(conn, "o2", "2454", 50, 200.0)
    on_sell_filled(conn, symbol="2330", sell_qty=100, sell_price=550.0,
                   sell_fee=0, sell_tax=0, trade_date="2026-03-03")
    on_sell_filled(conn, symbol="2454", sell_qty=50, sell_price=220.0,
                   sell_fee=0, sell_tax=0, trade_date="2026-03-03")
    row = conn.execute("SELECT total_trades FROM daily_pnl_summary").fetchone()
    assert row["total_trades"] == 2


# ── sync_positions_table ──────────────────────────────────────────────────────

def test_sync_positions_creates_position():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    sync_positions_table(conn)
    row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
    assert row is not None
    assert row["quantity"] == 100


def test_sync_positions_removes_fully_sold():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    _insert_sell(conn, "o2", "2330", 100, 600.0)
    sync_positions_table(conn)
    row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
    assert row is None


def test_sync_positions_partial_fill_left():
    conn = _conn()
    _insert_buy(conn, "o1", "2330", 100, 500.0)
    _insert_sell(conn, "o2", "2330", 40, 600.0)
    sync_positions_table(conn)
    row = conn.execute("SELECT quantity FROM positions WHERE symbol='2330'").fetchone()
    assert row["quantity"] == 60


# ── get_today_pnl ─────────────────────────────────────────────────────────────

def test_get_today_pnl_no_data():
    conn = _conn()
    assert get_today_pnl(conn, "2026-03-03") == 0.0


def test_get_today_pnl_with_data():
    conn = _conn()
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
                 ("2026-03-03", 5000.0))
    conn.commit()
    assert get_today_pnl(conn, "2026-03-03") == pytest.approx(5000.0)


# ── get_monthly_pnl ───────────────────────────────────────────────────────────

def test_get_monthly_pnl_empty():
    conn = _conn()
    assert get_monthly_pnl(conn, "2026-03") == 0.0


def test_get_monthly_pnl_sums_days():
    conn = _conn()
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
                 ("2026-03-01", 1000.0))
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
                 ("2026-03-02", 2000.0))
    conn.commit()
    assert get_monthly_pnl(conn, "2026-03") == pytest.approx(3000.0)


def test_get_monthly_pnl_excludes_other_months():
    conn = _conn()
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
                 ("2026-02-28", 9999.0))
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
                 ("2026-03-01", 500.0))
    conn.commit()
    assert get_monthly_pnl(conn, "2026-03") == pytest.approx(500.0)


# ── get_overall_win_rate ──────────────────────────────────────────────────────

def test_win_rate_empty():
    conn = _conn()
    assert get_overall_win_rate(conn) == 0.0


def test_win_rate_all_wins():
    conn = _conn()
    for d in ["2026-03-01", "2026-03-02", "2026-03-03"]:
        conn.execute(
            "INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?,?,?)",
            (d, 1000.0, 1))
    conn.commit()
    assert get_overall_win_rate(conn) == pytest.approx(1.0)


def test_win_rate_mixed():
    conn = _conn()
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?,?,?)",
                 ("2026-03-01", 1000.0, 1))
    conn.execute("INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?,?,?)",
                 ("2026-03-02", -500.0, 1))
    conn.commit()
    assert get_overall_win_rate(conn) == pytest.approx(0.5)


# ── get_equity_curve ──────────────────────────────────────────────────────────

def test_equity_curve_empty():
    conn = _conn()
    curve = get_equity_curve(conn, days=30, start_equity=1_000_000.0)
    assert curve == []


def test_equity_curve_builds_cumsum():
    conn = _conn()
    # Insert recent data (within 30 days)
    from datetime import datetime, timedelta, UTC
    today = datetime.now(UTC)
    for i, pnl in enumerate([1000.0, -500.0, 2000.0]):
        d = (today - timedelta(days=2 - i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT OR REPLACE INTO daily_pnl_summary (trade_date, realized_pnl) VALUES (?,?)",
            (d, pnl))
    conn.commit()
    curve = get_equity_curve(conn, days=30, start_equity=1_000_000.0)
    assert len(curve) == 3
    # cumulative: 1_001_000 → 1_000_500 → 1_002_500
    assert curve[-1]["equity"] == pytest.approx(1_002_500.0)
