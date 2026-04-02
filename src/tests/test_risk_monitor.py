"""Tests for agents/risk_monitor.py — Risk Monitoring Loop."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from openclaw.agents.risk_monitor import (
    RiskCheckResult,
    RiskMonitorReport,
    SEVERITY_CRITICAL,
    SEVERITY_EMERGENCY,
    SEVERITY_OK,
    SEVERITY_WARNING,
    _check_cash_level,
    _check_daily_loss,
    _check_drawdown,
    _check_gross_exposure,
    _check_symbol_concentration,
    _ensure_schema,
    _load_policy,
    _should_notify,
    alert_if_needed,
    check_portfolio_risk,
    run_risk_monitor,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db():
    """In-memory DB with minimal schema for risk monitor tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)

    # positions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            qty REAL, avg_cost REAL, current_price REAL,
            unrealized_pnl REAL, last_updated TEXT
        )
    """)
    # daily_pnl_summary
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            pnl_pct REAL, rolling_drawdown REAL,
            rolling_peak_nav REAL, losing_streak_days INTEGER,
            nav_end REAL
        )
    """)
    # daily_nav
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_nav (
            trade_date TEXT PRIMARY KEY,
            nav REAL
        )
    """)
    conn.commit()
    return conn


@pytest.fixture
def policy():
    return {
        "gross_exposure_limit": 1.20,
        "max_symbol_weight": 0.20,
        "daily_loss_pct_threshold": 0.05,
        "drawdown_pct_threshold": 0.15,
        "correlation_max_pair_abs_corr": 0.85,
        "correlation_max_weighted_avg_abs_corr": 0.55,
        "cash_min_pct": 0.05,
        "notification_cooldown_seconds": 3600,
    }


def _make_positions(specs):
    """Helper: list of (symbol, qty, price) -> list of dicts."""
    return [
        {"symbol": s, "qty": q, "current_price": p, "avg_cost": p}
        for s, q, p in specs
    ]


# ── Schema Tests ─────────────────────────────────────────────────────────────

def test_ensure_schema_creates_table(mem_db):
    row = mem_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='risk_monitor_log'"
    ).fetchone()
    assert row is not None


def test_ensure_schema_idempotent(mem_db):
    """Calling _ensure_schema twice should not raise."""
    _ensure_schema(mem_db)
    row = mem_db.execute(
        "SELECT COUNT(*) FROM risk_monitor_log"
    ).fetchone()
    assert row[0] == 0


# ── Gross Exposure Tests ─────────────────────────────────────────────────────

def test_gross_exposure_ok(mem_db, policy):
    positions = _make_positions([("2330", 100, 500)])  # 50000 / NAV
    result = _check_gross_exposure(mem_db, 100000, positions, policy)
    assert result.severity == SEVERITY_OK
    assert result.indicator == "gross_exposure"


def test_gross_exposure_critical(mem_db, policy):
    positions = _make_positions([("2330", 250, 500)])  # 125000 / 100000 = 1.25 >= 1.20
    result = _check_gross_exposure(mem_db, 100000, positions, policy)
    assert result.severity in (SEVERITY_CRITICAL, SEVERITY_EMERGENCY)


def test_gross_exposure_zero_nav(mem_db, policy):
    result = _check_gross_exposure(mem_db, 0, [], policy)
    assert result.severity == SEVERITY_OK


# ── Symbol Concentration Tests ───────────────────────────────────────────────

def test_symbol_concentration_ok(policy):
    positions = _make_positions([("2330", 10, 500), ("2317", 20, 300)])
    # max weight = max(5000, 6000) / 100000 = 0.06 < 0.20
    result = _check_symbol_concentration(100000, positions, policy)
    assert result.severity == SEVERITY_OK


def test_symbol_concentration_critical(policy):
    positions = _make_positions([("2330", 50, 500)])  # 25000 / 100000 = 0.25 >= 0.20
    result = _check_symbol_concentration(100000, positions, policy)
    assert result.severity in (SEVERITY_CRITICAL, SEVERITY_EMERGENCY)


def test_symbol_concentration_empty(policy):
    result = _check_symbol_concentration(100000, [], policy)
    assert result.severity == SEVERITY_OK


# ── Daily Loss Tests ─────────────────────────────────────────────────────────

def test_daily_loss_ok(mem_db, policy):
    mem_db.execute(
        "INSERT INTO daily_pnl_summary VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-04-01", -0.01, 0.02, 100000, 0, 99000),
    )
    mem_db.commit()
    result = _check_daily_loss(mem_db, 100000, policy)
    assert result.severity == SEVERITY_OK


def test_daily_loss_critical(mem_db, policy):
    mem_db.execute(
        "INSERT INTO daily_pnl_summary VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-04-01", -0.06, 0.02, 100000, 0, 94000),
    )
    mem_db.commit()
    result = _check_daily_loss(mem_db, 100000, policy)
    assert result.severity in (SEVERITY_CRITICAL, SEVERITY_EMERGENCY)


def test_daily_loss_no_data(mem_db, policy):
    result = _check_daily_loss(mem_db, 100000, policy)
    assert result.severity == SEVERITY_OK


# ── Drawdown Tests ───────────────────────────────────────────────────────────

def test_drawdown_ok(mem_db, policy):
    mem_db.execute(
        "INSERT INTO daily_pnl_summary VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-04-01", -0.01, 0.05, 100000, 0, 95000),
    )
    mem_db.commit()
    result = _check_drawdown(mem_db, policy)
    assert result.severity == SEVERITY_OK


def test_drawdown_critical(mem_db, policy):
    mem_db.execute(
        "INSERT INTO daily_pnl_summary VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-04-01", -0.01, 0.16, 100000, 5, 84000),
    )
    mem_db.commit()
    result = _check_drawdown(mem_db, policy)
    assert result.severity in (SEVERITY_CRITICAL, SEVERITY_EMERGENCY)


# ── Cash Level Tests ─────────────────────────────────────────────────────────

def test_cash_level_ok(policy):
    result = _check_cash_level(10000, 100000, policy)  # 10% > 5%
    assert result.severity == SEVERITY_OK


def test_cash_level_warning(policy):
    result = _check_cash_level(6000, 100000, policy)  # 6% > 5% but < 7.5%
    assert result.severity == SEVERITY_WARNING


def test_cash_level_critical(policy):
    result = _check_cash_level(3000, 100000, policy)  # 3% < 5%
    assert result.severity == SEVERITY_CRITICAL


def test_cash_level_emergency(policy):
    result = _check_cash_level(1000, 100000, policy)  # 1% < 2.5%
    assert result.severity == SEVERITY_EMERGENCY


def test_cash_level_zero_nav(policy):
    result = _check_cash_level(0, 0, policy)
    assert result.severity == SEVERITY_OK


# ── Notification Dedup Tests ─────────────────────────────────────────────────

def test_should_notify_no_prior(mem_db):
    assert _should_notify(mem_db, "critical", 3600) is True


def test_should_notify_cooldown_active(mem_db):
    mem_db.execute(
        "INSERT INTO risk_monitor_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-id", int(time.time()), 100000, 5000, 0.8, 0.15, -0.01, 0.05,
         "critical", "[]", 1),
    )
    mem_db.commit()
    assert _should_notify(mem_db, "critical", 3600) is False


def test_should_notify_cooldown_expired(mem_db):
    mem_db.execute(
        "INSERT INTO risk_monitor_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-id", int(time.time()) - 7200, 100000, 5000, 0.8, 0.15, -0.01, 0.05,
         "critical", "[]", 1),
    )
    mem_db.commit()
    assert _should_notify(mem_db, "critical", 3600) is True


def test_should_notify_different_breach_type(mem_db):
    mem_db.execute(
        "INSERT INTO risk_monitor_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-id", int(time.time()), 100000, 5000, 0.8, 0.15, -0.01, 0.05,
         "warning", "[]", 1),
    )
    mem_db.commit()
    # "critical" is a different breach type from "warning"
    assert _should_notify(mem_db, "critical", 3600) is True


# ── check_portfolio_risk Integration ─────────────────────────────────────────

def test_check_portfolio_risk_no_data(mem_db):
    report = check_portfolio_risk(mem_db)
    assert isinstance(report, RiskMonitorReport)
    assert len(report.checks) == 6
    assert report.worst_breach == SEVERITY_OK


def test_check_portfolio_risk_with_positions(mem_db):
    # NAV = 100000 from daily_nav
    mem_db.execute("INSERT INTO daily_nav VALUES (?, ?)", ("2026-04-01", 100000))
    mem_db.execute(
        "INSERT INTO positions VALUES (?, ?, ?, ?, ?, ?)",
        ("2330", 100, 500, 550, 5000, "2026-04-01"),
    )
    mem_db.commit()
    report = check_portfolio_risk(mem_db)
    assert report.nav > 0
    assert len(report.checks) == 6


# ── run_risk_monitor Integration ─────────────────────────────────────────────

def test_run_risk_monitor_success(mem_db, monkeypatch):
    monkeypatch.setattr("openclaw.agents.risk_monitor.send_message", lambda *a, **k: True,
                        raising=False)
    result = run_risk_monitor(conn=mem_db)
    assert result.success is True
    assert "Risk monitor" in result.summary

    # Check log was written
    rows = mem_db.execute("SELECT * FROM risk_monitor_log").fetchall()
    assert len(rows) == 1


def test_run_risk_monitor_with_breach(mem_db, monkeypatch):
    """Breach scenario: low cash + drawdown."""
    mem_db.execute("INSERT INTO daily_nav VALUES (?, ?)", ("2026-04-01", 100000))
    mem_db.execute(
        "INSERT INTO daily_pnl_summary VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-04-01", -0.08, 0.20, 120000, 3, 100000),
    )
    mem_db.commit()

    # Mock send_message to avoid real Telegram calls
    sent_messages = []
    monkeypatch.setattr(
        "openclaw.agents.risk_monitor.send_message",
        lambda text, **kw: sent_messages.append(text) or True,
        raising=False,
    )

    result = run_risk_monitor(conn=mem_db)
    assert result.success is True
    assert result.raw["breach_count"] > 0


def test_run_risk_monitor_creates_own_conn(tmp_path, monkeypatch):
    """When no conn passed, creates its own connection and closes it."""
    db_path = str(tmp_path / "test_risk.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            qty REAL, avg_cost REAL, current_price REAL,
            unrealized_pnl REAL, last_updated TEXT
        )
    """)
    conn.commit()
    conn.close()

    result = run_risk_monitor(db_path=db_path)
    assert result.success is True


# ── alert_if_needed Tests ────────────────────────────────────────────────────

def test_alert_ok_no_send(mem_db, monkeypatch):
    """OK severity should not trigger any notification."""
    report = RiskMonitorReport(
        checks=[RiskCheckResult("test", 0.1, 0.5, SEVERITY_OK)],
        worst_breach=SEVERITY_OK,
        nav=100000,
        timestamp=int(time.time()),
    )
    result = alert_if_needed(report, mem_db)
    assert result is False


def test_alert_warning_sends(mem_db, monkeypatch):
    sent = []
    monkeypatch.setattr(
        "openclaw.tg_notify.send_message",
        lambda text, **kw: sent.append(text) or True,
    )
    report = RiskMonitorReport(
        checks=[RiskCheckResult("cash_level", 0.03, 0.05, SEVERITY_WARNING)],
        worst_breach=SEVERITY_WARNING,
        nav=100000,
        timestamp=int(time.time()),
        cash=3000,
    )
    result = alert_if_needed(report, mem_db)
    assert result is True
    assert len(sent) == 1
    assert "WARNING" in sent[0]


def test_alert_emergency_sets_reduce_only(mem_db, tmp_path, monkeypatch):
    """EMERGENCY should write reduce_only_mode to system_state.json."""
    # Point _REPO_ROOT to tmp_path for isolation
    monkeypatch.setattr("openclaw.agents.risk_monitor._REPO_ROOT", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "system_state.json").write_text("{}")

    monkeypatch.setattr(
        "openclaw.tg_notify.send_message",
        lambda text, **kw: True,
    )

    report = RiskMonitorReport(
        checks=[RiskCheckResult("gross_exposure", 1.5, 1.2, SEVERITY_EMERGENCY)],
        worst_breach=SEVERITY_EMERGENCY,
        nav=100000,
        timestamp=int(time.time()),
        gross_exposure=1.5,
    )
    alert_if_needed(report, mem_db)

    state = json.loads((config_dir / "system_state.json").read_text())
    assert state["reduce_only_mode"] is True
    assert state["reduce_only_reason"] == "risk_monitor_emergency"




def test_should_notify_emergency_always(mem_db):
    """EMERGENCY must always notify regardless of cooldown."""
    mem_db.execute(
        "INSERT INTO risk_monitor_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-id", int(time.time()), 100000, 5000, 0.8, 0.15, -0.01, 0.05,
         "emergency", "[]", 1),
    )
    mem_db.commit()
    # Even with a recent emergency notification, should still notify
    assert _should_notify(mem_db, "emergency", 3600) is True


def test_alert_emergency_telegram_fail_still_returns_true(mem_db, tmp_path, monkeypatch):
    """HIGH-3: If Telegram fails on EMERGENCY, still return True for DB logging."""
    monkeypatch.setattr("openclaw.agents.risk_monitor._REPO_ROOT", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "system_state.json").write_text("{}")

    def tg_fail(text, **kw):
        raise ConnectionError("Telegram down")

    monkeypatch.setattr(
        "openclaw.tg_notify.send_message",
        tg_fail,
    )

    report = RiskMonitorReport(
        checks=[RiskCheckResult("gross_exposure", 1.5, 1.2, "emergency")],
        worst_breach="emergency",
        nav=100000,
        timestamp=int(time.time()),
        gross_exposure=1.5,
    )
    result = alert_if_needed(report, mem_db)
    # Should return True even though Telegram failed — reduce_only was activated
    assert result is True

    # Verify reduce_only was still set
    import json
    state = json.loads((config_dir / "system_state.json").read_text())
    assert state["reduce_only_mode"] is True


def test_alert_message_no_absolute_values(mem_db, tmp_path, monkeypatch):
    """MEDIUM: Telegram message should show percentages, not absolute NAV/Cash."""
    monkeypatch.setattr("openclaw.agents.risk_monitor._REPO_ROOT", tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "system_state.json").write_text("{}")

    sent = []
    monkeypatch.setattr(
        "openclaw.tg_notify.send_message",
        lambda text, **kw: sent.append(text) or True,
    )

    report = RiskMonitorReport(
        checks=[RiskCheckResult("cash_level", 0.03, 0.05, "warning")],
        worst_breach="warning",
        nav=100000,
        timestamp=int(time.time()),
        cash=3000,
    )
    alert_if_needed(report, mem_db)

    assert len(sent) == 1
    msg = sent[0]
    # Should NOT contain absolute NAV or Cash values
    assert "100,000" not in msg
    assert "3,000" not in msg
    # Should contain percentage
    assert "Cash比例:" in msg


# ── Policy Loading Tests ─────────────────────────────────────────────────────

def test_load_policy_defaults():
    policy = _load_policy("/nonexistent/path.json")
    assert policy["gross_exposure_limit"] == 1.20
    assert policy["cash_min_pct"] == 0.05


def test_load_policy_from_file(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"gross_exposure_limit": 1.50, "cash_min_pct": 0.10}))
    policy = _load_policy(str(p))
    assert policy["gross_exposure_limit"] == 1.50
    assert policy["cash_min_pct"] == 0.10
    # Defaults still present
    assert policy["max_symbol_weight"] == 0.20
