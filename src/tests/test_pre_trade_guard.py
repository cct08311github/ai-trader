from __future__ import annotations

import datetime as dt
import sqlite3

from openclaw.pre_trade_guard import evaluate_pre_trade_guard
from openclaw.risk_engine import OrderCandidate


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT,
          broker_order_id TEXT,
          ts_submit TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL,
          order_type TEXT,
          tif TEXT,
          status TEXT NOT NULL,
          strategy_version TEXT
        );

        CREATE TABLE positions (
          symbol TEXT PRIMARY KEY,
          quantity INTEGER NOT NULL,
          avg_price REAL,
          current_price REAL
        );
        """
    )
    return conn


def _candidate(side: str = "buy", qty: int = 100, price: float = 500.0) -> OrderCandidate:
    return OrderCandidate(symbol="2330", side=side, qty=qty, price=price, opens_new_position=(side == "buy"))


def test_pre_trade_guard_allows_normal_order():
    conn = make_db()
    conn.execute("INSERT INTO positions(symbol, quantity, avg_price, current_price) VALUES ('2330', 100, 490, 500)")

    result = evaluate_pre_trade_guard(conn, _candidate())

    assert result.approved is True


def test_pre_trade_guard_rejects_duplicate_order():
    conn = make_db()
    now = dt.datetime(2026, 3, 6, 12, 0, tzinfo=dt.timezone.utc)
    conn.execute(
        """
        INSERT INTO orders(order_id, decision_id, broker_order_id, ts_submit, symbol, side, qty, price, order_type, tif, status, strategy_version)
        VALUES ('o1', 'd1', 'b1', ?, '2330', 'buy', 100, 500.0, 'limit', 'IOC', 'filled', 'v1')
        """,
        (now.isoformat(),),
    )

    result = evaluate_pre_trade_guard(conn, _candidate(), now=now)

    assert result.approved is False
    assert result.reject_code == "RISK_HARD_GUARD_DUPLICATE_ORDER"


def test_pre_trade_guard_rejects_symbol_rate_limit():
    conn = make_db()
    now = dt.datetime(2026, 3, 6, 12, 0, tzinfo=dt.timezone.utc)
    for idx in range(2):
        conn.execute(
            """
            INSERT INTO orders(order_id, decision_id, broker_order_id, ts_submit, symbol, side, qty, price, order_type, tif, status, strategy_version)
            VALUES (?, ?, ?, ?, '2330', 'buy', 50, 500.0, 'limit', 'IOC', 'filled', 'v1')
            """,
            (f"o{idx}", f"d{idx}", f"b{idx}", now.isoformat()),
        )

    result = evaluate_pre_trade_guard(
        conn,
        _candidate(qty=100, price=499.0),
        now=now,
        limits={"duplicate_order_window_sec": 0},
    )

    assert result.approved is False
    assert result.reject_code == "RISK_HARD_GUARD_SYMBOL_RATE_LIMIT"


def test_pre_trade_guard_rejects_sell_above_position():
    conn = make_db()
    conn.execute("INSERT INTO positions(symbol, quantity, avg_price, current_price) VALUES ('2330', 80, 490, 500)")

    result = evaluate_pre_trade_guard(conn, _candidate(side="sell", qty=100, price=500.0))

    assert result.approved is False
    assert result.reject_code == "RISK_HARD_GUARD_SELL_QTY_EXCEEDS_POSITION"


def test_pre_trade_guard_rejects_symbol_notional_limit():
    conn = make_db()
    conn.execute("INSERT INTO positions(symbol, quantity, avg_price, current_price) VALUES ('2330', 1000, 490, 500)")

    result = evaluate_pre_trade_guard(
        conn,
        _candidate(side="buy", qty=1500, price=500.0),
        limits={"max_order_qty": 5000, "max_order_notional": 2_000_000, "max_symbol_position_notional": 1_200_000},
    )

    assert result.approved is False
    assert result.reject_code == "RISK_HARD_GUARD_SYMBOL_NOTIONAL_LIMIT"
