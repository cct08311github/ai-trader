import sqlite3

from openclaw.orders import OrderStateError, summarize_fill_status, transition_order_status


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
        CREATE TABLE fills (
          fill_id TEXT PRIMARY KEY,
          order_id TEXT NOT NULL,
          ts_fill TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL NOT NULL,
          fee REAL NOT NULL,
          tax REAL NOT NULL
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


def test_transition_valid_submitted_to_partial():
    conn = _conn()
    transition_order_status(conn, "o1", "partially_filled")
    row = conn.execute("SELECT status FROM orders WHERE order_id = 'o1'").fetchone()
    assert row[0] == "partially_filled"


def test_transition_invalid_filled_to_submitted():
    conn = _conn()
    transition_order_status(conn, "o1", "filled")
    try:
        transition_order_status(conn, "o1", "submitted")
        assert False, "expected OrderStateError"
    except OrderStateError:
        assert True


def test_summarize_fill_status_partial_and_filled():
    conn = _conn()
    conn.execute(
        "INSERT INTO fills(fill_id, order_id, ts_fill, qty, price, fee, tax) VALUES ('f1', 'o1', '2026-02-27T00:01:00Z', 40, 1000.0, 10.0, 10.0)"
    )
    assert summarize_fill_status(conn, "o1") == "partially_filled"

    conn.execute(
        "INSERT INTO fills(fill_id, order_id, ts_fill, qty, price, fee, tax) VALUES ('f2', 'o1', '2026-02-27T00:02:00Z', 60, 1001.0, 10.0, 10.0)"
    )
    assert summarize_fill_status(conn, "o1") == "filled"


def test_get_order_status_raises_for_missing_order():
    """Line 31: OrderStateError raised when order not found."""
    conn = _conn()
    try:
        from openclaw.orders import get_order_status
        get_order_status(conn, "does_not_exist")
        assert False, "expected OrderStateError"
    except OrderStateError as e:
        assert "does_not_exist" in str(e)


def test_transition_order_status_noop_when_same():
    """Line 38: transition_order_status returns early when current == next."""
    conn = _conn()
    # o1 is 'submitted'; transitioning to 'submitted' again is a no-op (no error)
    transition_order_status(conn, "o1", "submitted")
    row = conn.execute("SELECT status FROM orders WHERE order_id = 'o1'").fetchone()
    assert row[0] == "submitted"


def test_summarize_fill_status_raises_for_missing_order():
    """Line 47: OrderStateError raised when order_id not in orders table."""
    conn = _conn()
    try:
        summarize_fill_status(conn, "ghost_order")
        assert False, "expected OrderStateError"
    except OrderStateError as e:
        assert "ghost_order" in str(e)


def test_summarize_fill_status_returns_terminal_status_immediately():
    """Line 51: terminal status (e.g. 'cancelled') is returned without querying fills."""
    conn = _conn()
    # Move o1 to a terminal status
    transition_order_status(conn, "o1", "cancelled")
    result = summarize_fill_status(conn, "o1")
    assert result == "cancelled"


def test_summarize_fill_status_returns_current_when_no_fills():
    """Line 56: fill_qty <= 0 branch returns current_status unchanged."""
    conn = _conn()
    # o1 is 'submitted' with no fills → should return 'submitted'
    result = summarize_fill_status(conn, "o1")
    assert result == "submitted"
