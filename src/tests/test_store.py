import sqlite3

from openclaw.audit_store import insert_incident, insert_risk_check
from openclaw.risk_store import LimitQuery, load_limits


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE risk_limits (
          limit_id TEXT PRIMARY KEY,
          scope TEXT NOT NULL,
          symbol TEXT,
          strategy_id TEXT,
          rule_name TEXT NOT NULL,
          rule_value REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE decisions (
          decision_id TEXT PRIMARY KEY
        );
        CREATE TABLE risk_checks (
          check_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          ts TEXT NOT NULL,
          passed INTEGER NOT NULL,
          reject_code TEXT,
          metrics_json TEXT NOT NULL
        );
        CREATE TABLE incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute("INSERT INTO decisions(decision_id) VALUES ('d1')")
    conn.executemany(
        """
        INSERT INTO risk_limits(limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, '2026-02-27T00:00:00Z')
        """,
        [
            ("g1", "global", None, None, "max_orders_per_min", 3.0),
            ("s1", "symbol", "2330", None, "max_orders_per_min", 2.0),
            ("st1", "strategy", None, "breakout", "max_orders_per_min", 1.0),
            ("g2", "global", None, None, "max_daily_loss_pct", 0.05),
        ],
    )
    conn.commit()
    return conn


def test_load_limits_precedence_global_symbol_strategy():
    conn = _conn()
    limits = load_limits(conn, LimitQuery(symbol="2330", strategy_id="breakout"))
    assert limits["max_orders_per_min"] == 1.0
    assert limits["max_daily_loss_pct"] == 0.05


def test_insert_risk_check():
    conn = _conn()
    rid = insert_risk_check(
        conn,
        decision_id="d1",
        ts="2026-02-27T08:00:00Z",
        passed=False,
        reject_code="RISK_ORDER_RATE_LIMIT",
        metrics={"orders_last_60s": 4},
    )
    row = conn.execute("SELECT passed, reject_code FROM risk_checks WHERE check_id = ?", (rid,)).fetchone()
    assert row is not None
    assert row[0] == 0
    assert row[1] == "RISK_ORDER_RATE_LIMIT"


def test_insert_incident():
    conn = _conn()
    iid = insert_incident(
        conn,
        ts="2026-02-27T08:01:00Z",
        severity="critical",
        source="risk",
        code="RISK_DAILY_LOSS_LIMIT",
        detail={"note": "locked"},
    )
    row = conn.execute("SELECT severity, code, resolved FROM incidents WHERE incident_id = ?", (iid,)).fetchone()
    assert row is not None
    assert row[0] == "critical"
    assert row[1] == "RISK_DAILY_LOSS_LIMIT"
    assert row[2] == 0
