"""Tests for Phase 5 — dual-trigger Volatility Gate.

Closes #480
"""
import sqlite3
import json
import time
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("""
        CREATE TABLE eod_prices (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            close REAL,
            high REAL DEFAULT 0,
            low REAL DEFAULT 0,
            open REAL DEFAULT 0,
            volume REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    c.execute("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL DEFAULT 0,
            avg_price REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0
        )
    """)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# _is_buy_direction
# ---------------------------------------------------------------------------

class TestIsBuyDirection:
    def _fn(self, direction):
        from openclaw.guards.volatility_guard import _is_buy_direction
        return _is_buy_direction(direction)

    def test_buy_detected(self):
        assert self._fn("buy") is True
        assert self._fn("Buy") is True
        assert self._fn("bullish") is True
        assert self._fn("offensive") is True
        assert self._fn("加碼") is True
        assert self._fn("買入") is True

    def test_sell_not_detected(self):
        assert self._fn("sell") is False
        assert self._fn("defensive") is False
        assert self._fn("reduce") is False
        assert self._fn("bearish") is False


# ---------------------------------------------------------------------------
# _get_taiex_daily_change
# ---------------------------------------------------------------------------

class TestGetTaiexDailyChange:
    def test_returns_none_when_no_data(self, conn):
        from openclaw.guards.volatility_guard import _get_taiex_daily_change
        assert _get_taiex_daily_change(conn) is None

    def test_returns_none_when_only_one_row(self, conn):
        from openclaw.guards.volatility_guard import _get_taiex_daily_change
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 20000)")
        conn.commit()
        assert _get_taiex_daily_change(conn) is None

    def test_calculates_decline(self, conn):
        from openclaw.guards.volatility_guard import _get_taiex_daily_change
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19400)")
        conn.commit()
        result = _get_taiex_daily_change(conn)
        assert result == pytest.approx(-0.03, abs=0.001)

    def test_calculates_advance(self, conn):
        from openclaw.guards.volatility_guard import _get_taiex_daily_change
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 20400)")
        conn.commit()
        result = _get_taiex_daily_change(conn)
        assert result == pytest.approx(0.02, abs=0.001)


# ---------------------------------------------------------------------------
# _get_avg_unrealized_pnl
# ---------------------------------------------------------------------------

class TestGetAvgUnrealizedPnl:
    def test_returns_none_with_no_positions(self, conn):
        from openclaw.guards.volatility_guard import _get_avg_unrealized_pnl
        assert _get_avg_unrealized_pnl(conn) is None

    def test_calculates_avg_pnl(self, conn):
        from openclaw.guards.volatility_guard import _get_avg_unrealized_pnl
        # symbol1: (500 - 400) / 400 = +25%
        conn.execute("INSERT INTO positions VALUES ('2330', 1000, 400, 500, 100000)")
        # symbol2: (380 - 400) / 400 = -5%
        conn.execute("INSERT INTO positions VALUES ('2317', 1000, 400, 380, -20000)")
        conn.commit()
        result = _get_avg_unrealized_pnl(conn)
        assert result == pytest.approx(0.10, abs=0.001)  # avg of +25% and -5% = +10%

    def test_ignores_zero_quantity_positions(self, conn):
        from openclaw.guards.volatility_guard import _get_avg_unrealized_pnl
        conn.execute("INSERT INTO positions VALUES ('2330', 0, 400, 500, 0)")
        conn.commit()
        assert _get_avg_unrealized_pnl(conn) is None


# ---------------------------------------------------------------------------
# VolatilityGate.evaluate
# ---------------------------------------------------------------------------

class TestVolatilityGate:
    def _make_ctx(self, conn, direction):
        from openclaw.guards.base import GuardContext
        return GuardContext(
            conn=conn,
            system_state=None,
            order_candidate=None,
            pm_context={"direction": direction},
        )

    def test_passes_when_market_normal(self, conn):
        from openclaw.guards.volatility_guard import VolatilityGate
        # No data → both indicators return None → gate passes
        gate = VolatilityGate()
        result = gate.evaluate(self._make_ctx(conn, "buy"))
        assert result.passed is True

    def test_taiex_leading_indicator_blocks_buy(self, conn):
        from openclaw.guards.volatility_guard import VolatilityGate
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19400)")
        conn.commit()
        gate = VolatilityGate()
        result = gate.evaluate(self._make_ctx(conn, "buy"))
        assert result.passed is False
        assert result.reject_code == "VOLATILITY_GATE_TAIEX"
        assert "先行指標" in result.reason

    def test_pnl_lagging_indicator_blocks_buy(self, conn):
        from openclaw.guards.volatility_guard import VolatilityGate
        conn.execute("INSERT INTO positions VALUES ('2330', 1000, 500, 450, -50000)")
        conn.commit()
        gate = VolatilityGate()
        result = gate.evaluate(self._make_ctx(conn, "bullish"))
        assert result.passed is False
        assert result.reject_code == "VOLATILITY_GATE_PNL"
        assert "落後指標" in result.reason

    def test_does_not_block_sell_direction_even_when_triggered(self, conn):
        """Sell/defensive direction must always pass through."""
        from openclaw.guards.volatility_guard import VolatilityGate
        # Trigger TAIEX drop
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19400)")
        conn.commit()
        gate = VolatilityGate()
        for sell_dir in ("sell", "defensive", "reduce", "bearish"):
            result = gate.evaluate(self._make_ctx(conn, sell_dir))
            assert result.passed is True, f"Should pass for direction={sell_dir!r}"

    def test_does_not_block_buy_when_taiex_decline_within_threshold(self, conn):
        from openclaw.guards.volatility_guard import VolatilityGate
        # -1% decline, threshold is -2%
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19800)")
        conn.commit()
        gate = VolatilityGate()
        result = gate.evaluate(self._make_ctx(conn, "buy"))
        assert result.passed is True


# ---------------------------------------------------------------------------
# Integration: auto_review blocks buy-direction proposal when gate triggered
# ---------------------------------------------------------------------------

class TestVolatilityGateIntegration:
    @pytest.fixture
    def full_conn(self):
        c = sqlite3.connect(":memory:")
        for stmt in [
            """CREATE TABLE strategy_proposals (
               proposal_id TEXT PRIMARY KEY,
               generated_by TEXT, target_rule TEXT, rule_category TEXT,
               status TEXT DEFAULT 'pending',
               proposal_json TEXT DEFAULT '{}',
               created_at INTEGER, decided_at INTEGER, expires_at INTEGER,
               supporting_evidence TEXT, confidence REAL,
               requires_human_approval INTEGER DEFAULT 1,
               proposed_value TEXT, current_value TEXT)""",
            """CREATE TABLE positions (
               symbol TEXT PRIMARY KEY,
               quantity REAL DEFAULT 0, avg_price REAL DEFAULT 0,
               current_price REAL DEFAULT 0, unrealized_pnl REAL DEFAULT 0)""",
            """CREATE TABLE eod_prices (
               symbol TEXT, trade_date TEXT, close REAL,
               high REAL DEFAULT 0, low REAL DEFAULT 0,
               open REAL DEFAULT 0, volume REAL DEFAULT 0,
               PRIMARY KEY (symbol, trade_date))""",
            "CREATE TABLE incidents (incident_id TEXT PRIMARY KEY, ts TEXT, severity TEXT, source TEXT, code TEXT, detail_json TEXT, resolved INTEGER DEFAULT 0)",
        ]:
            c.execute(stmt)
        yield c
        c.close()

    def test_buy_direction_blocked_by_taiex_drop(self, full_conn):
        """When TAIEX drops >2%, buy-direction STRATEGY_DIRECTION is auto-rejected."""
        # Simulate TAIEX drop
        full_conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        full_conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19400)")
        full_conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                status, proposal_json, created_at)
               VALUES ('sd_buy', 'strategy_committee', 'STRATEGY_DIRECTION', 'strategy',
                       'pending', ?, ?)""",
            (
                json.dumps({
                    "direction": "buy",
                    "proposed_value": "加碼",
                    "committee_context": {"arbiter": {"direction": "buy"}},
                    "confidence": 0.75,
                }),
                int(time.time() * 1000),
            ),
        )
        full_conn.commit()

        with patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(full_conn)

        assert reviewed == 1
        row = full_conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='sd_buy'"
        ).fetchone()
        assert row[0] == "rejected"

    def test_sell_direction_not_affected_by_taiex_drop(self, full_conn):
        """Sell-direction proposals pass through even when TAIEX drops."""
        full_conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-26', 20000)")
        full_conn.execute("INSERT INTO eod_prices (symbol, trade_date, close) VALUES ('Y9999', '2026-03-27', 19400)")
        full_conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                status, proposal_json, created_at)
               VALUES ('sd_sell', 'strategy_committee', 'STRATEGY_DIRECTION', 'strategy',
                       'pending', ?, ?)""",
            (
                json.dumps({
                    "direction": "defensive",
                    "proposed_value": "減少多頭",
                    "committee_context": {"arbiter": {"direction": "defensive"}},
                    "confidence": 0.70,
                }),
                int(time.time() * 1000),
            ),
        )
        full_conn.commit()

        with patch("openclaw.proposal_reviewer._strategy_direction_review",
                   return_value={"decision": "approve", "confidence": 0.70, "reason": "ok"}), \
             patch("openclaw.tg_notify.send_message"):
            from openclaw.proposal_reviewer import auto_review_pending_proposals
            reviewed = auto_review_pending_proposals(full_conn)

        assert reviewed == 1
        row = full_conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='sd_sell'"
        ).fetchone()
        assert row[0] == "approved"
