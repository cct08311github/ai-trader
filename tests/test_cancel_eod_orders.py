"""tests/test_cancel_eod_orders.py

Unit tests for _cancel_stale_pending_orders():
  1. Cancels today's pending order — updates status to 'cancelled'
  2. Cancels today's submitted order
  3. Does NOT cancel already-filled orders
  4. Does NOT cancel orders from a previous day
  5. Returns correct count of cancelled orders
  6. Handles broker cancel failure gracefully (logs warning, continues)
"""
import datetime as dt
import sqlite3
import uuid
from unittest.mock import MagicMock, patch

import pytest

from openclaw.ticker_watcher import _cancel_stale_pending_orders, _TZ_TWN


# ─── DB fixture ─────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    """Build an in-memory DB with the orders table matching production schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE orders (
            order_id        TEXT PRIMARY KEY,
            decision_id     TEXT,
            broker_order_id TEXT,
            ts_submit       TEXT NOT NULL,
            symbol          TEXT,
            side            TEXT,
            qty             INTEGER,
            price           REAL,
            order_type      TEXT,
            tif             TEXT,
            status          TEXT,
            strategy_version TEXT,
            settlement_date TEXT
        )"""
    )
    conn.commit()
    return conn


def _insert_order(conn: sqlite3.Connection, *, order_id: str, symbol: str,
                  status: str, ts_submit_utc: str) -> None:
    conn.execute(
        """INSERT INTO orders
           (order_id, decision_id, broker_order_id, ts_submit, symbol, side,
            qty, price, order_type, tif, status, strategy_version, settlement_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, str(uuid.uuid4()), "broker-" + order_id[:4], ts_submit_utc,
         symbol, "buy", 1000, 100.0, "limit", "IOC", status, "watcher_v1", None),
    )
    conn.commit()


def _today_utc_iso() -> str:
    """Return a UTC ISO timestamp that corresponds to today in TWN (+8h)."""
    now_twn = dt.datetime.now(tz=_TZ_TWN)
    # Express today's noon TWN time as UTC
    noon_twn = now_twn.replace(hour=12, minute=0, second=0, microsecond=0)
    noon_utc = noon_twn.astimezone(dt.timezone.utc)
    return noon_utc.isoformat()


def _yesterday_utc_iso() -> str:
    """Return a UTC ISO timestamp for yesterday in TWN."""
    now_twn = dt.datetime.now(tz=_TZ_TWN)
    yesterday_twn = (now_twn - dt.timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    yesterday_utc = yesterday_twn.astimezone(dt.timezone.utc)
    return yesterday_utc.isoformat()


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_cancels_today_pending_order():
    """Today's 'pending' order is cancelled and DB status updated."""
    conn = _make_db()
    oid = str(uuid.uuid4())
    _insert_order(conn, order_id=oid, symbol="2330", status="pending",
                  ts_submit_utc=_today_utc_iso())

    broker = MagicMock()
    n = _cancel_stale_pending_orders(conn, broker)

    assert n == 1
    broker.cancel_order.assert_called_once()
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
    assert row[0] == "cancelled"


def test_cancels_today_submitted_order():
    """Today's 'submitted' order is also cancelled."""
    conn = _make_db()
    oid = str(uuid.uuid4())
    _insert_order(conn, order_id=oid, symbol="2317", status="submitted",
                  ts_submit_utc=_today_utc_iso())

    broker = MagicMock()
    n = _cancel_stale_pending_orders(conn, broker)

    assert n == 1
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
    assert row[0] == "cancelled"


def test_does_not_cancel_filled_order():
    """'filled' orders are not touched."""
    conn = _make_db()
    oid = str(uuid.uuid4())
    _insert_order(conn, order_id=oid, symbol="2330", status="filled",
                  ts_submit_utc=_today_utc_iso())

    broker = MagicMock()
    n = _cancel_stale_pending_orders(conn, broker)

    assert n == 0
    broker.cancel_order.assert_not_called()
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
    assert row[0] == "filled"


def test_does_not_cancel_previous_day_order():
    """Yesterday's pending orders are not affected."""
    conn = _make_db()
    oid = str(uuid.uuid4())
    _insert_order(conn, order_id=oid, symbol="2330", status="pending",
                  ts_submit_utc=_yesterday_utc_iso())

    broker = MagicMock()
    n = _cancel_stale_pending_orders(conn, broker)

    assert n == 0
    broker.cancel_order.assert_not_called()
    row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
    assert row[0] == "pending"


def test_returns_correct_count_multiple_orders():
    """Returns count of all cancelled orders."""
    conn = _make_db()
    today_iso = _today_utc_iso()
    yesterday_iso = _yesterday_utc_iso()

    oids_today = [str(uuid.uuid4()) for _ in range(3)]
    for oid in oids_today:
        _insert_order(conn, order_id=oid, symbol="2330", status="pending",
                      ts_submit_utc=today_iso)

    # one from yesterday — should not be cancelled
    oid_old = str(uuid.uuid4())
    _insert_order(conn, order_id=oid_old, symbol="2330", status="pending",
                  ts_submit_utc=yesterday_iso)

    broker = MagicMock()
    n = _cancel_stale_pending_orders(conn, broker)

    assert n == 3
    assert broker.cancel_order.call_count == 3
    for oid in oids_today:
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
        assert row[0] == "cancelled"
    old_row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid_old,)).fetchone()
    assert old_row[0] == "pending"


def test_broker_cancel_failure_is_handled_gracefully():
    """If broker.cancel_order raises, the loop continues and warning is logged."""
    conn = _make_db()
    today_iso = _today_utc_iso()

    oid1 = str(uuid.uuid4())
    oid2 = str(uuid.uuid4())
    _insert_order(conn, order_id=oid1, symbol="2330", status="pending",
                  ts_submit_utc=today_iso)
    _insert_order(conn, order_id=oid2, symbol="2317", status="pending",
                  ts_submit_utc=today_iso)

    broker = MagicMock()
    # First call raises, second succeeds
    broker.cancel_order.side_effect = [RuntimeError("broker timeout"), None]

    with patch("openclaw.ticker_watcher.log") as mock_log:
        n = _cancel_stale_pending_orders(conn, broker)

    # Only the second order was successfully cancelled
    assert n == 1
    assert broker.cancel_order.call_count == 2
    mock_log.warning.assert_called_once()
    assert "Failed to cancel" in mock_log.warning.call_args[0][0]
