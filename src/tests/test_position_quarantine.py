from __future__ import annotations

import sqlite3

from openclaw.pnl_engine import sync_positions_table
from openclaw.position_quarantine import (
    apply_quarantine_plan,
    build_reconciliation_quarantine_plan,
    clear_quarantine_symbols,
    ensure_position_quarantine_schema,
    get_quarantine_status,
)


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE positions (
          symbol TEXT PRIMARY KEY,
          quantity INTEGER,
          avg_price REAL,
          current_price REAL,
          unrealized_pnl REAL,
          state TEXT
        );
        CREATE TABLE orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT,
          broker_order_id TEXT,
          ts_submit TEXT,
          symbol TEXT,
          side TEXT,
          qty INTEGER,
          price REAL,
          order_type TEXT,
          tif TEXT,
          status TEXT,
          strategy_version TEXT
        );
        CREATE TABLE fills (
          order_id TEXT,
          qty INTEGER,
          price REAL,
          fee REAL,
          tax REAL
        );
        """
    )
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500.0, 510.0, 1000.0, 'HOLDING')")
    return conn


def test_build_reconciliation_quarantine_plan_marks_eligible_symbol():
    conn = make_db()

    plan = build_reconciliation_quarantine_plan(
        conn,
        report={
            "report_id": "r1",
            "mismatches": {"missing_broker_position": [{"symbol": "2330"}]},
            "diagnostics": {"suspected_mode_or_account_mismatch": True},
        },
    )

    assert plan["safe_to_apply"] is True
    assert plan["eligible_symbols"] == ["2330"]
    assert plan["actions"][0]["eligible"] is True


def test_build_reconciliation_quarantine_plan_blocks_symbol_with_open_order():
    conn = make_db()
    conn.execute(
        "INSERT INTO orders VALUES ('o1', 'd1', NULL, '2026-03-06T00:00:00Z', '2330', 'sell', 100, 500.0, 'limit', 'DAY', 'submitted', 'v1')"
    )
    conn.commit()

    plan = build_reconciliation_quarantine_plan(
        conn,
        report={
            "report_id": "r1",
            "mismatches": {"missing_broker_position": [{"symbol": "2330"}]},
            "diagnostics": {"suspected_mode_or_account_mismatch": True},
        },
    )

    assert plan["eligible_symbols"] == []
    assert plan["actions"][0]["eligible"] is False


def test_apply_quarantine_plan_updates_positions_and_table():
    conn = make_db()
    plan = build_reconciliation_quarantine_plan(
        conn,
        report={
            "report_id": "r1",
            "mismatches": {"missing_broker_position": [{"symbol": "2330"}]},
            "diagnostics": {"suspected_mode_or_account_mismatch": True},
        },
    )

    result = apply_quarantine_plan(conn, plan=plan)

    assert result["applied_symbols"] == ["2330"]
    row = conn.execute("SELECT quantity, state FROM positions WHERE symbol='2330'").fetchone()
    assert row["quantity"] == 0
    assert row["state"] == "QUARANTINED"
    qrow = conn.execute("SELECT active, reason_code FROM position_quarantine WHERE symbol='2330'").fetchone()
    assert qrow["active"] == 1
    assert qrow["reason_code"] == "BROKER_POSITION_MISSING"


def test_sync_positions_table_excludes_active_quarantine():
    conn = make_db()
    ensure_position_quarantine_schema(conn)
    conn.execute(
        "INSERT INTO orders VALUES ('o1', 'd1', NULL, '2026-03-06T00:00:00Z', '2330', 'buy', 100, 500.0, 'limit', 'DAY', 'filled', 'v1')"
    )
    conn.execute("INSERT INTO fills VALUES ('o1', 100, 500.0, 10.0, 0.0)")
    conn.execute(
        "INSERT INTO position_quarantine VALUES ('2330', 1, 'broker_reconciliation', 'BROKER_POSITION_MISSING', 'x', 'r1', 1, NULL, '{}')"
    )
    conn.commit()

    sync_positions_table(conn)

    count = conn.execute("SELECT COUNT(*) FROM positions WHERE symbol='2330'").fetchone()[0]
    assert count == 0


def test_clear_quarantine_symbols_restores_positions_from_fills():
    conn = make_db()
    ensure_position_quarantine_schema(conn)
    conn.execute("DELETE FROM positions")
    conn.execute(
        "INSERT INTO orders VALUES ('o1', 'd1', NULL, '2026-03-06T00:00:00Z', '2330', 'buy', 100, 500.0, 'limit', 'DAY', 'filled', 'v1')"
    )
    conn.execute("INSERT INTO fills VALUES ('o1', 100, 500.0, 10.0, 0.0)")
    conn.execute(
        "INSERT INTO position_quarantine VALUES ('2330', 1, 'broker_reconciliation', 'BROKER_POSITION_MISSING', 'x', 'r1', 1, NULL, '{}')"
    )
    conn.commit()

    result = clear_quarantine_symbols(conn, symbols=["2330"])

    assert result["remaining_active_count"] == 0
    row = conn.execute("SELECT quantity, avg_price FROM positions WHERE symbol='2330'").fetchone()
    assert row["quantity"] == 100
    assert row["avg_price"] == 500.0


def test_get_quarantine_status_returns_items():
    conn = make_db()
    ensure_position_quarantine_schema(conn)
    conn.execute(
        "INSERT INTO position_quarantine VALUES ('2330', 1, 'broker_reconciliation', 'BROKER_POSITION_MISSING', 'x', 'r1', 1, NULL, '{}')"
    )
    conn.commit()

    status = get_quarantine_status(conn)

    assert status["active_count"] == 1
    assert status["items"][0]["symbol"] == "2330"
