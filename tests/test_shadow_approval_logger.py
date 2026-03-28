"""Tests for shadow_approval_logger — Phase 0 shadow mode infrastructure."""
import sqlite3
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    # Minimal tables needed
    c.execute("""
        CREATE TABLE eod_prices (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            close REAL,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# _should_require_human_new_logic
# ---------------------------------------------------------------------------

class TestShouldRequireHumanNewLogic:
    def _fn(self, *args, **kwargs):
        from openclaw.shadow_approval_logger import _should_require_human_new_logic
        return _should_require_human_new_logic(*args, **kwargs)

    def test_sell_above_floor_auto_approved(self):
        # sell direction, conf >= 0.50 → auto
        assert self._fn({}, 0.55, "sell") == 0

    def test_sell_at_floor_auto_approved(self):
        assert self._fn({}, 0.50, "reduce") == 0

    def test_sell_below_floor_requires_human(self):
        assert self._fn({}, 0.45, "sell") == 1

    def test_buy_above_buy_floor_auto_approved(self):
        # buy, conf >= 0.65 → auto
        assert self._fn({}, 0.70, "buy") == 0

    def test_buy_at_buy_floor_auto_approved(self):
        assert self._fn({}, 0.65, "increase") == 0

    def test_buy_below_buy_floor_requires_human(self):
        assert self._fn({}, 0.60, "buy") == 1

    def test_sell_above_sell_floor_but_below_buy_floor_auto(self):
        # conf=0.60 — above sell floor (0.50), below buy floor (0.65)
        # → sell: auto, buy: human
        assert self._fn({}, 0.60, "sell") == 0
        assert self._fn({}, 0.60, "buy") == 1

    def test_arbiter_reject_buy_requires_human(self):
        # Even with high conf, if arbiter rejects + buy direction → human
        assert self._fn({"stance": "reject"}, 0.80, "buy") == 1

    def test_arbiter_strong_bearish_buy_requires_human(self):
        assert self._fn({"stance": "strong_bearish"}, 0.75, "increase") == 1

    def test_arbiter_reject_sell_still_auto(self):
        # Arbiter rejects but direction is sell → auto (sell has priority)
        assert self._fn({"stance": "reject"}, 0.80, "sell") == 0

    def test_no_direction_requires_human(self):
        # direction="" → unknown/neutral → always require human
        assert self._fn({}, 0.55, "") == 1
        assert self._fn({}, 0.95, "") == 1


# ---------------------------------------------------------------------------
# log_shadow_decision
# ---------------------------------------------------------------------------

class TestLogShadowDecision:
    def test_basic_log(self, conn):
        from openclaw.shadow_approval_logger import log_shadow_decision
        log_shadow_decision(
            conn,
            proposal_id="prop_abc123",
            symbol="2330",
            direction="sell",
            confidence=0.72,
            would_approve=True,
            current_requires_human=1,
        )
        row = conn.execute(
            "SELECT * FROM shadow_decisions WHERE proposal_id = 'prop_abc123'"
        ).fetchone()
        assert row is not None
        assert row[1] == "2330"   # symbol
        assert row[2] == "sell"   # direction
        assert abs(row[3] - 0.72) < 0.001  # confidence
        assert row[4] == 1   # would_approve
        assert row[5] == 1   # current_requires_human

    def test_idempotent_upsert(self, conn):
        from openclaw.shadow_approval_logger import log_shadow_decision
        for _ in range(3):
            log_shadow_decision(conn, "prop_dup", "1303", "buy", 0.7, True, 1)
        count = conn.execute(
            "SELECT COUNT(*) FROM shadow_decisions WHERE proposal_id='prop_dup'"
        ).fetchone()[0]
        assert count == 1

    def test_does_not_raise_on_exception(self, conn):
        """log_shadow_decision should not propagate DB errors."""
        from openclaw.shadow_approval_logger import log_shadow_decision
        # Close conn to force an error
        bad_conn = sqlite3.connect(":memory:")
        bad_conn.close()
        # Should not raise
        log_shadow_decision(bad_conn, "x", "y", "z", 0.5, True, 1)


# ---------------------------------------------------------------------------
# shadow_mode_report
# ---------------------------------------------------------------------------

class TestShadowModeReport:
    def _seed(self, conn, rows):
        from openclaw.shadow_approval_logger import _ensure_table
        _ensure_table(conn)
        for r in rows:
            conn.execute(
                """INSERT INTO shadow_decisions
                   (proposal_id, symbol, direction, confidence, would_approve,
                    current_requires_human, logged_at, pnl_t5, pnl_t20)
                   VALUES (?, ?, ?, ?, ?, ?, 1000000, ?, ?)""",
                r,
            )
        conn.commit()

    def test_empty_report(self, conn):
        from openclaw.shadow_approval_logger import shadow_mode_report
        r = shadow_mode_report(conn)
        assert r["total"] == 0
        assert r["ready_to_go_live"] is False

    def test_win_rate_calculation(self, conn):
        from openclaw.shadow_approval_logger import shadow_mode_report
        # 6 would-approve decisions, 4 wins at T+5, 3 wins at T+20
        rows = [
            ("p1", "2330", "sell", 0.7, 1, 1, 0.02, 0.05),
            ("p2", "2330", "sell", 0.7, 1, 1, 0.01, 0.03),
            ("p3", "2330", "sell", 0.6, 1, 1, 0.03, 0.02),
            ("p4", "2330", "sell", 0.6, 1, 1, -0.01, -0.01),
            ("p5", "2330", "sell", 0.55, 1, 1, 0.02, -0.02),
            ("p6", "2330", "sell", 0.55, 1, 1, -0.02, -0.03),
        ]
        self._seed(conn, rows)
        r = shadow_mode_report(conn)
        assert r["total"] == 6
        assert r["would_approve_count"] == 6
        assert r["t5_win_rate"] == pytest.approx(4 / 6, abs=0.01)

    def test_not_ready_below_threshold(self, conn):
        from openclaw.shadow_approval_logger import shadow_mode_report
        # 5 cases, only 2 wins → 0.40 win rate < 0.55
        rows = [
            (f"p{i}", "1303", "buy", 0.7, 1, 0, 0.01 if i < 2 else -0.01, -0.01)
            for i in range(5)
        ]
        self._seed(conn, rows)
        r = shadow_mode_report(conn)
        assert r["ready_to_go_live"] is False

    def test_ready_above_threshold(self, conn):
        from openclaw.shadow_approval_logger import shadow_mode_report
        # 6 wins out of 8 = 0.75 ≥ 0.55 at T+5, positive T+20
        rows = [
            (f"p{i}", "2330", "sell", 0.7, 1, 1, 0.02 if i < 6 else -0.01, 0.01)
            for i in range(8)
        ]
        self._seed(conn, rows)
        r = shadow_mode_report(conn)
        assert r["t5_win_rate"] >= 0.55
        assert r["t20_avg_pnl"] >= 0.0
        assert r["ready_to_go_live"] is True


# ---------------------------------------------------------------------------
# backfill_shadow_decisions_eod
# ---------------------------------------------------------------------------

class TestBackfillShadowDecisions:
    def test_backfill_t5(self, conn):
        from openclaw.shadow_approval_logger import (
            _ensure_table, backfill_shadow_decisions_eod,
        )
        _ensure_table(conn)
        # Insert a shadow decision logged 10 days ago
        import time
        old_ms = int(time.time() * 1000) - 10 * 86_400_000
        conn.execute(
            """INSERT INTO shadow_decisions
               (proposal_id, symbol, direction, confidence, would_approve,
                current_requires_human, logged_at)
               VALUES ('prop_old', '2330', 'sell', 0.7, 1, 1, ?)""",
            (old_ms,),
        )
        # Insert eod_prices for the symbol
        from datetime import datetime, timezone, timedelta
        log_date = datetime.fromtimestamp(old_ms / 1000, tz=timezone.utc)
        for delta in range(0, 25):
            d = (log_date + timedelta(days=delta)).strftime("%Y-%m-%d")
            conn.execute(
                "INSERT INTO eod_prices (symbol, trade_date, close) VALUES (?, ?, ?)",
                ("2330", d, 100.0 + delta),
            )
        conn.commit()

        updated = backfill_shadow_decisions_eod(conn)
        assert updated >= 1

        row = conn.execute(
            "SELECT price_t5 FROM shadow_decisions WHERE proposal_id='prop_old'"
        ).fetchone()
        assert row[0] is not None
        assert row[0] > 100.0  # T+5 price should be > entry
