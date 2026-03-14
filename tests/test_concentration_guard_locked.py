"""Tests for locked_symbols filtering in concentration_guard.check_concentration."""
import sqlite3

import pytest

from openclaw.concentration_guard import check_concentration


def _make_db(positions: list[tuple]) -> sqlite3.Connection:
    """Build an in-memory SQLite DB with the tables concentration_guard needs."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            current_price REAL,
            state TEXT,
            avg_price REAL,
            unrealized_pnl REAL,
            high_water_mark REAL,
            entry_trading_day TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            status TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            proposal_json TEXT,
            created_at INTEGER
        )"""
    )
    conn.executemany(
        "INSERT INTO positions (symbol, quantity, current_price) VALUES (?,?,?)",
        positions,
    )
    conn.commit()
    return conn


class TestLockedSymbolSkipped:
    """LOCKED_SYM at 70% weight — should be skipped when in locked_symbols."""

    def test_locked_symbol_skipped_in_concentration(self):
        # LOCKED_SYM: 700 * 100 = 70,000  (70%)
        # NORMAL_SYM: 300 * 100 = 30,000  (30%)
        conn = _make_db([("LOCKED_SYM", 700, 100), ("NORMAL_SYM", 300, 100)])

        proposals = check_concentration(conn, locked_symbols={"LOCKED_SYM"})

        symbols = [p["symbol"] for p in proposals]
        assert "LOCKED_SYM" not in symbols, (
            "Locked symbol must not generate a sell proposal"
        )

    def test_no_proposal_inserted_for_locked_symbol(self):
        conn = _make_db([("LOCKED_SYM", 700, 100), ("NORMAL_SYM", 300, 100)])

        check_concentration(conn, locked_symbols={"LOCKED_SYM"})

        rows = conn.execute(
            "SELECT proposal_json FROM strategy_proposals"
        ).fetchall()
        for (pj,) in rows:
            import json
            data = json.loads(pj)
            assert data.get("symbol") != "LOCKED_SYM", (
                "No DB proposal should be written for a locked symbol"
            )


class TestNormalSymbolStillGeneratesProposal:
    """NORMAL_SYM at >60% — should still get a proposal even when another symbol is locked."""

    def test_normal_symbol_still_generates_proposal(self):
        # NORMAL_SYM: 700 * 100 = 70,000 (70%)  — exceeds 60% threshold
        # LOCKED_SYM: 300 * 100 = 30,000 (30%)
        conn = _make_db([("NORMAL_SYM", 700, 100), ("LOCKED_SYM", 300, 100)])

        proposals = check_concentration(conn, locked_symbols={"LOCKED_SYM"})

        symbols = [p["symbol"] for p in proposals]
        assert "NORMAL_SYM" in symbols, (
            "Non-locked symbol above threshold must still generate a proposal"
        )
        proposal = next(p for p in proposals if p["symbol"] == "NORMAL_SYM")
        assert proposal["auto_approve"] is True  # 70% > 60%


class TestBackwardCompatibility:
    """Calling without locked_symbols must preserve original behaviour."""

    def test_no_locked_symbols_backward_compatible(self):
        # Without locked_symbols, LOCKED_SYM at 70% SHOULD get an auto-approve proposal
        conn = _make_db([("LOCKED_SYM", 700, 100), ("NORMAL_SYM", 300, 100)])

        proposals = check_concentration(conn)  # no locked_symbols arg

        symbols = [p["symbol"] for p in proposals]
        assert "LOCKED_SYM" in symbols, (
            "Without locked_symbols, high-concentration symbol must generate proposal"
        )
        proposal = next(p for p in proposals if p["symbol"] == "LOCKED_SYM")
        assert proposal["auto_approve"] is True

    def test_none_locked_symbols_backward_compatible(self):
        conn = _make_db([("LOCKED_SYM", 700, 100), ("NORMAL_SYM", 300, 100)])

        proposals = check_concentration(conn, locked_symbols=None)

        symbols = [p["symbol"] for p in proposals]
        assert "LOCKED_SYM" in symbols
