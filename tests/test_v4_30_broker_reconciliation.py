"""Tests for broker_reconciliation module.

Covers:
- Partial fill mismatch detection (broker shows different qty than DB)
- Multi-symbol reconciliation (multiple positions checked)
- Simulation mode handling (broker empty is expected)
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from openclaw.broker_reconciliation import reconcile_broker_state


# ---------------------------------------------------------------------------
# Helper: build minimal in-memory DB
# ---------------------------------------------------------------------------

def _make_db(
    *,
    positions: list[tuple] | None = None,
    orders: list[tuple] | None = None,
) -> sqlite3.Connection:
    """Return an in-memory SQLite DB with the tables reconciliation needs."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            current_price REAL,
            state TEXT,
            avg_price REAL,
            unrealized_pnl REAL,
            high_water_mark REAL,
            entry_trading_day TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            broker_order_id TEXT,
            symbol TEXT,
            side TEXT,
            qty REAL,
            price REAL,
            status TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            ts TEXT,
            severity TEXT,
            source TEXT,
            code TEXT,
            detail_json TEXT,
            resolved INTEGER DEFAULT 0
        )
        """
    )
    if positions:
        conn.executemany(
            "INSERT INTO positions (symbol, quantity, current_price) VALUES (?,?,?)",
            positions,
        )
    if orders:
        conn.executemany(
            "INSERT INTO orders (order_id, broker_order_id, symbol, side, status) VALUES (?,?,?,?,?)",
            orders,
        )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Tests: no mismatch (clean)
# ---------------------------------------------------------------------------

class TestCleanReconciliation:
    def test_no_positions_no_broker_is_ok(self):
        conn = _make_db()
        report = reconcile_broker_state(conn, broker_positions=[])
        assert report["ok"] is True
        assert report["mismatch_count"] == 0

    def test_matching_single_position_is_ok(self):
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        report = reconcile_broker_state(
            conn,
            broker_positions=[{"symbol": "2330", "quantity": 1000, "current_price": 500.0}],
        )
        assert report["ok"] is True
        assert report["mismatch_count"] == 0

    def test_matching_multi_symbol_is_ok(self):
        conn = _make_db(
            positions=[("2330", 1000, 500.0), ("0050", 500, 150.0), ("2317", 200, 80.0)]
        )
        broker_positions = [
            {"symbol": "2330", "quantity": 1000, "current_price": 500.0},
            {"symbol": "0050", "quantity": 500, "current_price": 150.0},
            {"symbol": "2317", "quantity": 200, "current_price": 80.0},
        ]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        assert report["ok"] is True
        assert report["mismatch_count"] == 0


# ---------------------------------------------------------------------------
# Tests: partial fill / quantity mismatch
# ---------------------------------------------------------------------------

class TestQuantityMismatch:
    def test_partial_fill_mismatch_detected(self):
        """Broker shows 600 shares; DB has 1000 → quantity_mismatch."""
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        report = reconcile_broker_state(
            conn,
            broker_positions=[{"symbol": "2330", "quantity": 600, "current_price": 500.0}],
        )
        assert report["ok"] is False
        assert report["mismatch_count"] > 0
        qty_mismatches = report["mismatches"]["quantity_mismatch"]
        assert len(qty_mismatches) == 1
        m = qty_mismatches[0]
        assert m["symbol"] == "2330"
        assert m["local"]["quantity"] == 1000
        assert m["broker"]["quantity"] == 600

    def test_multi_symbol_partial_mismatch(self):
        """Two symbols; one has quantity mismatch, one is correct."""
        conn = _make_db(
            positions=[("2330", 1000, 500.0), ("0050", 500, 150.0)]
        )
        broker_positions = [
            {"symbol": "2330", "quantity": 800, "current_price": 500.0},  # mismatch
            {"symbol": "0050", "quantity": 500, "current_price": 150.0},  # ok
        ]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        assert report["ok"] is False
        qty_mismatches = report["mismatches"]["quantity_mismatch"]
        assert any(m["symbol"] == "2330" for m in qty_mismatches)
        # 0050 should not appear in mismatches
        assert not any(m["symbol"] == "0050" for m in qty_mismatches)

    def test_report_saved_to_db(self):
        """After reconciliation, a report row should exist in reconciliation_reports."""
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        report = reconcile_broker_state(
            conn,
            broker_positions=[{"symbol": "2330", "quantity": 700, "current_price": 500.0}],
        )
        rows = conn.execute("SELECT report_id, mismatch_count FROM reconciliation_reports").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == report["report_id"]
        assert rows[0][1] == report["mismatch_count"]


# ---------------------------------------------------------------------------
# Tests: missing positions
# ---------------------------------------------------------------------------

class TestMissingPositions:
    def test_broker_has_position_not_in_db(self):
        """Broker reports a symbol DB has no record of → missing_local_position."""
        conn = _make_db()
        report = reconcile_broker_state(
            conn,
            broker_positions=[{"symbol": "2330", "quantity": 500, "current_price": 500.0}],
        )
        assert report["ok"] is False
        assert len(report["mismatches"]["missing_local_position"]) == 1
        assert report["mismatches"]["missing_local_position"][0]["symbol"] == "2330"

    def test_db_has_position_not_in_broker(self):
        """DB has a position that broker doesn't report → missing_broker_position."""
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        report = reconcile_broker_state(conn, broker_positions=[])
        assert report["ok"] is False
        missing = report["mismatches"]["missing_broker_position"]
        assert any(m["symbol"] == "2330" for m in missing)


# ---------------------------------------------------------------------------
# Tests: multi-symbol reconciliation
# ---------------------------------------------------------------------------

class TestMultiSymbolReconciliation:
    def test_all_three_mismatches_detected(self):
        """Three symbols: qty mismatch, missing local, missing broker."""
        conn = _make_db(
            positions=[
                ("2330", 1000, 500.0),  # will have qty mismatch
                ("0050", 300, 150.0),   # will be missing from broker
            ]
        )
        broker_positions = [
            {"symbol": "2330", "quantity": 500, "current_price": 500.0},  # qty mismatch
            {"symbol": "2317", "quantity": 200, "current_price": 80.0},   # missing local
        ]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        assert report["ok"] is False
        assert report["mismatch_count"] >= 3
        assert len(report["mismatches"]["quantity_mismatch"]) >= 1
        assert len(report["mismatches"]["missing_local_position"]) >= 1
        assert len(report["mismatches"]["missing_broker_position"]) >= 1

    def test_mismatch_count_matches_sum_of_categories(self):
        """mismatch_count should equal sum of all mismatch category lengths."""
        conn = _make_db(
            positions=[("2330", 1000, 500.0), ("0050", 200, 150.0)]
        )
        broker_positions = [
            {"symbol": "2330", "quantity": 999, "current_price": 500.0},
        ]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        total = sum(len(v) for v in report["mismatches"].values())
        assert report["mismatch_count"] == total


# ---------------------------------------------------------------------------
# Tests: simulation mode handling
# ---------------------------------------------------------------------------

class TestSimulationMode:
    def test_simulation_mode_broker_empty_suppresses_incident(self):
        """When resolved_simulation=True and broker is empty, no incident should be created."""
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        broker_context = {"resolved_simulation": True, "requested_simulation": True}
        report = reconcile_broker_state(
            conn,
            broker_positions=[],
            broker_context=broker_context,
        )
        # Mismatch should be detected (broker empty while local has position)
        assert report["mismatch_count"] > 0
        # Diagnostics should flag MODE_OR_ACCOUNT_MISMATCH_SUSPECTED
        assert "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in report["diagnostics"]["diagnosis_codes"]
        # resolved_simulation should be True
        assert report["diagnostics"]["resolved_simulation"] is True
        # No incident should be inserted (simulation_expected suppresses it)
        incident_rows = conn.execute(
            "SELECT * FROM incidents WHERE source='broker_reconciliation'"
        ).fetchall()
        assert len(incident_rows) == 0

    def test_non_simulation_mode_mismatch_creates_incident(self):
        """Real mode with missing broker position should log an incident."""
        conn = _make_db(positions=[("2330", 1000, 500.0)])
        broker_context = {"resolved_simulation": False}
        report = reconcile_broker_state(
            conn,
            broker_positions=[],
            broker_context=broker_context,
        )
        assert report["mismatch_count"] > 0
        # An incident should have been inserted
        incident_rows = conn.execute(
            "SELECT code FROM incidents WHERE source='broker_reconciliation'"
        ).fetchall()
        assert len(incident_rows) >= 1
        assert incident_rows[0][0] == "RECONCILIATION_MISMATCH"

    def test_simulation_broker_empty_no_positions_is_ok(self):
        """Simulation with no local positions and empty broker snapshot is clean."""
        conn = _make_db()
        broker_context = {"resolved_simulation": True}
        report = reconcile_broker_state(
            conn,
            broker_positions=[],
            broker_context=broker_context,
        )
        assert report["ok"] is True
        assert report["mismatch_count"] == 0

    def test_diagnostics_broker_accounts_sorted(self):
        """broker_accounts in diagnostics should be sorted."""
        conn = _make_db()
        broker_context = {"broker_accounts": ["C", "A", "B"]}
        report = reconcile_broker_state(conn, broker_positions=[], broker_context=broker_context)
        accounts = report["diagnostics"]["broker_accounts"]
        assert accounts == sorted(accounts)


# ---------------------------------------------------------------------------
# Tests: open order reconciliation
# ---------------------------------------------------------------------------

class TestOpenOrderReconciliation:
    def test_local_order_missing_from_broker_flagged(self):
        """A submitted local order whose broker_order_id is not in broker snapshot → missing_broker_order."""
        conn = _make_db(
            orders=[("ord-001", "BRK-999", "2330", "buy", "submitted")]
        )
        # broker_open_orders does not include BRK-999
        report = reconcile_broker_state(
            conn,
            broker_positions=[],
            broker_open_orders=[{"broker_order_id": "BRK-111"}],
        )
        missing_orders = report["mismatches"]["missing_broker_order"]
        assert any(m["broker_order_id"] == "BRK-999" for m in missing_orders)

    def test_order_with_no_broker_order_id_not_flagged(self):
        """A local order without a broker_order_id should not be flagged as missing."""
        conn = _make_db(
            orders=[("ord-002", "", "0050", "buy", "submitted")]
        )
        report = reconcile_broker_state(conn, broker_positions=[], broker_open_orders=[])
        missing_orders = report["mismatches"]["missing_broker_order"]
        assert len(missing_orders) == 0
