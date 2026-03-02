import sqlite3

from openclaw.order_store import transition_with_event


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          broker_order_id TEXT,
          ts_submit TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL,
          order_type TEXT NOT NULL,
          tif TEXT NOT NULL,
          status TEXT NOT NULL,
          strategy_version TEXT NOT NULL
        );
        CREATE TABLE order_events (
          event_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          from_status TEXT,
          to_status TEXT,
          source TEXT NOT NULL,
          reason_code TEXT,
          payload_json TEXT NOT NULL
        );
        INSERT INTO orders (
          order_id, decision_id, broker_order_id, ts_submit, symbol, side, qty, price,
          order_type, tif, status, strategy_version
        ) VALUES (
          'o1', 'd1', 'b1', '2026-02-27T00:00:00Z', '2330', 'buy', 100, 1000.0, 'limit', 'IOC', 'submitted', 'v1'
        );
        """
    )
    return conn


def test_transition_with_event_writes_order_events():
    conn = _conn()
    transition_with_event(
        conn,
        order_id="o1",
        next_status="partially_filled",
        source="broker",
        reason_code=None,
        payload={"note": "first fill"},
    )
    status = conn.execute("SELECT status FROM orders WHERE order_id = 'o1'").fetchone()[0]
    assert status == "partially_filled"
    count = conn.execute("SELECT COUNT(*) FROM order_events WHERE order_id = 'o1'").fetchone()[0]
    assert count == 1


def test_transition_with_event_raises_when_order_not_found():
    """Line 56: RuntimeError raised when order_id does not exist."""
    conn = _conn()
    try:
        transition_with_event(
            conn,
            order_id="nonexistent",
            next_status="filled",
            source="broker",
            reason_code=None,
            payload={},
        )
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "nonexistent" in str(e)


def test_transition_with_event_noop_when_same_status():
    """Line 59: early return (no DB write) when next_status == current status."""
    conn = _conn()
    # 'o1' starts at 'submitted'; requesting 'submitted' again is a no-op
    transition_with_event(
        conn,
        order_id="o1",
        next_status="submitted",
        source="broker",
        reason_code=None,
        payload={},
    )
    count = conn.execute("SELECT COUNT(*) FROM order_events WHERE order_id = 'o1'").fetchone()[0]
    assert count == 0
