"""Tests for Phase 4 — adaptive dedup lookback + confidence-weighted execution qty.

Closes #480
"""
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# _adaptive_lookback_hours
# ---------------------------------------------------------------------------

class TestAdaptiveLookbackHours:
    @pytest.fixture
    def conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("""
            CREATE TABLE eod_prices (
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL DEFAULT 0,
                PRIMARY KEY (symbol, trade_date)
            )
        """)
        c.execute("""
            CREATE TABLE positions (
                symbol TEXT PRIMARY KEY,
                quantity REAL DEFAULT 0
            )
        """)
        yield c
        c.close()

    def test_no_positions_returns_default(self, conn):
        from openclaw.agents.strategy_committee import _adaptive_lookback_hours
        assert _adaptive_lookback_hours(conn) == 12

    def test_low_volatility_returns_12h(self, conn):
        from openclaw.agents.strategy_committee import _adaptive_lookback_hours
        conn.execute("INSERT INTO positions VALUES ('2330', 1000)")
        # avg_range = (500-497)/498 ≈ 0.006 — well below 2%
        conn.execute(
            "INSERT INTO eod_prices (symbol, trade_date, high, low, close) "
            "VALUES ('2330', date('now', '-1 days'), 500, 497, 498)"
        )
        conn.commit()
        assert _adaptive_lookback_hours(conn) == 12

    def test_moderate_volatility_returns_8h(self, conn):
        from openclaw.agents.strategy_committee import _adaptive_lookback_hours
        conn.execute("INSERT INTO positions VALUES ('2330', 1000)")
        # avg_range = (510-490)/500 = 0.04 — wait, close=500, range=20/500=0.04 > 3%
        # Let me use a range of ~2.5%: high=512, low=488, close=500 → range=24/500=0.048
        # Hmm, that's > 3%. Need 2-3%: high=510, low=498, close=500 → 12/500 = 0.024
        conn.execute(
            "INSERT INTO eod_prices (symbol, trade_date, high, low, close) "
            "VALUES ('2330', date('now', '-1 days'), 510, 498, 500)"
        )
        conn.commit()
        assert _adaptive_lookback_hours(conn) == 8

    def test_high_volatility_returns_4h(self, conn):
        from openclaw.agents.strategy_committee import _adaptive_lookback_hours
        conn.execute("INSERT INTO positions VALUES ('2330', 1000)")
        # avg_range = (520-480)/500 = 0.08 > 3%
        conn.execute(
            "INSERT INTO eod_prices (symbol, trade_date, high, low, close) "
            "VALUES ('2330', date('now', '-1 days'), 520, 480, 500)"
        )
        conn.commit()
        assert _adaptive_lookback_hours(conn) == 4

    def test_missing_eod_table_returns_default(self):
        """When eod_prices table doesn't exist, returns default 12h (no crash)."""
        from openclaw.agents.strategy_committee import _adaptive_lookback_hours
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE positions (symbol TEXT, quantity REAL)")
        c.execute("INSERT INTO positions VALUES ('2330', 1000)")
        c.commit()
        assert _adaptive_lookback_hours(c) == 12
        c.close()


# ---------------------------------------------------------------------------
# _confidence_weighted_qty
# ---------------------------------------------------------------------------

class TestConfidenceWeightedQty:
    def _fn(self, base_qty, confidence):
        from openclaw.proposal_executor import _confidence_weighted_qty
        return _confidence_weighted_qty(base_qty, confidence)

    def test_high_confidence_full_qty(self):
        assert self._fn(5000, 0.85) == 5000
        assert self._fn(5000, 0.90) == 5000
        assert self._fn(5000, 1.00) == 5000

    def test_medium_confidence_75pct(self):
        assert self._fn(4000, 0.70) == 3000
        assert self._fn(4000, 0.80) == 3000

    def test_low_confidence_50pct(self):
        assert self._fn(4000, 0.60) == 2000
        assert self._fn(4000, 0.55) == 2000
        assert self._fn(4000, 0.40) == 2000

    def test_minimum_1000_shares(self):
        """Result is always at least 1000 shares."""
        # base_qty=1000, conf=0.60 → 500, but min=1000
        assert self._fn(1000, 0.60) == 1000

    def test_never_exceeds_base_qty(self):
        """Result must not exceed base_qty."""
        assert self._fn(3000, 0.85) == 3000

    def test_boundary_conf_0_70_exact(self):
        assert self._fn(4000, 0.70) == 3000  # 75%

    def test_boundary_conf_0_85_exact(self):
        assert self._fn(4000, 0.85) == 4000  # 100%


# ---------------------------------------------------------------------------
# Integration: concentration proposals skip weighting
# ---------------------------------------------------------------------------

class TestConcentrationSkipsWeighting:
    @pytest.fixture
    def conn(self):
        c = sqlite3.connect(":memory:")
        c.execute("""
            CREATE TABLE strategy_proposals (
                proposal_id TEXT PRIMARY KEY,
                generated_by TEXT,
                target_rule TEXT,
                rule_category TEXT,
                status TEXT DEFAULT 'approved',
                proposal_json TEXT DEFAULT '{}',
                created_at INTEGER,
                decided_at INTEGER,
                expires_at INTEGER
            )
        """)
        c.execute("""
            CREATE TABLE positions (
                symbol TEXT PRIMARY KEY,
                quantity REAL DEFAULT 0,
                current_price REAL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE execution_journal (
                execution_key TEXT PRIMARY KEY,
                proposal_id TEXT,
                target_rule TEXT,
                symbol TEXT,
                qty INTEGER,
                price REAL,
                state TEXT DEFAULT 'prepared',
                attempt_count INTEGER DEFAULT 1,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)
        yield c
        c.close()

    def test_concentration_weight_gte_40pct_uses_full_qty(self, conn):
        """Proposals with current_weight >= 0.40 must NOT be downscaled."""
        import json, time
        conn.execute("INSERT INTO positions VALUES ('2330', 10000, 500.0)")
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                status, proposal_json, created_at)
               VALUES ('p1', 'concentration_guard', 'POSITION_REBALANCE', 'concentration',
                       'approved', ?, ?)""",
            (
                json.dumps({
                    "symbol": "2330",
                    "reduce_pct": 0.20,
                    "current_weight": 0.45,  # ≥ 0.40 → full qty
                    "confidence": 0.55,       # low confidence, but should NOT scale
                }),
                int(time.time() * 1000),
            ),
        )
        conn.commit()

        from openclaw.proposal_executor import execute_pending_proposals
        intents, _ = execute_pending_proposals(conn)
        assert len(intents) == 1
        # base_qty = int(10000 * 0.20) = 2000; should NOT be scaled by confidence
        assert intents[0].qty == 2000

    def test_normal_proposal_low_confidence_scaled(self, conn):
        """Proposals with current_weight < 0.40 ARE subject to confidence scaling."""
        import json, time
        conn.execute("INSERT INTO positions VALUES ('2330', 10000, 500.0)")
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                status, proposal_json, created_at)
               VALUES ('p2', 'agent', 'POSITION_REBALANCE', 'rebalance',
                       'approved', ?, ?)""",
            (
                json.dumps({
                    "symbol": "2330",
                    "reduce_pct": 0.20,
                    "current_weight": 0.25,  # < 0.40 → scaling applies
                    "confidence": 0.60,       # 50% factor
                }),
                int(time.time() * 1000),
            ),
        )
        conn.commit()

        from openclaw.proposal_executor import execute_pending_proposals
        intents, _ = execute_pending_proposals(conn)
        assert len(intents) == 1
        # base_qty = int(10000 * 0.20) = 2000; scaled to 50% = 1000
        assert intents[0].qty == 1000
