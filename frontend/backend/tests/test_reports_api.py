from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


_AUTH = {"Authorization": "Bearer test-bearer-token"}


def _init_reports_db(path: Path) -> None:
    conn = sqlite3.connect(path.as_posix())
    try:
        conn.executescript(
            """
            CREATE TABLE positions (
                symbol TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                avg_price REAL,
                current_price REAL,
                unrealized_pnl REAL,
                state TEXT,
                high_water_mark REAL,
                entry_trading_day TEXT
            );

            CREATE TABLE eod_prices (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                close REAL
            );

            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                decision_id TEXT,
                broker_order_id TEXT,
                ts_submit TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty INTEGER NOT NULL,
                price REAL,
                order_type TEXT,
                tif TEXT,
                status TEXT NOT NULL,
                strategy_version TEXT
            );

            CREATE TABLE fills (
                fill_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                ts_fill TEXT,
                qty INTEGER NOT NULL,
                price REAL NOT NULL,
                fee REAL,
                tax REAL
            );

            CREATE TABLE eod_institution_flows (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                foreign_net REAL,
                trust_net REAL,
                dealer_net REAL,
                total_net REAL
            );

            CREATE TABLE eod_margin_data (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                margin_balance REAL,
                short_balance REAL
            );

            CREATE TABLE eod_analysis_reports (
                trade_date TEXT PRIMARY KEY,
                generated_at INTEGER,
                market_summary TEXT,
                technical TEXT,
                strategy TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO positions(symbol, quantity, avg_price, current_price, unrealized_pnl, state, high_water_mark, entry_trading_day)
            VALUES ('2330', 100, 600.0, 650.0, 5000.0, 'holding', 660.0, '2026-03-01')
            """
        )
        for idx, close in enumerate([620, 622, 625, 628, 630, 635, 640, 645, 650], start=1):
            conn.execute(
                "INSERT INTO eod_prices(trade_date, symbol, name, close) VALUES (?, '2330', 'TSMC', ?)",
                (f"2026-03-{idx:02d}", close),
            )
        conn.execute(
            """
            INSERT INTO orders(order_id, decision_id, broker_order_id, ts_submit, symbol, side, qty, price, order_type, tif, status, strategy_version)
            VALUES ('o1', 'd1', 'b1', '2026-03-07T09:00:00+08:00', '2330', 'buy', 100, 600.0, 'limit', 'ROD', 'filled', 'v1')
            """
        )
        conn.execute(
            """
            INSERT INTO fills(fill_id, order_id, ts_fill, qty, price, fee, tax)
            VALUES ('f1', 'o1', '2026-03-07T09:01:00+08:00', 100, 600.0, 20.0, 0.0)
            """
        )
        conn.execute(
            """
            INSERT INTO eod_institution_flows(trade_date, symbol, name, foreign_net, trust_net, dealer_net, total_net)
            VALUES ('2026-03-07', '2330', 'TSMC', 1000, 200, -100, 1100)
            """
        )
        conn.execute(
            """
            INSERT INTO eod_margin_data(trade_date, symbol, margin_balance, short_balance)
            VALUES ('2026-03-07', '2330', 12345, 321)
            """
        )
        conn.execute(
            """
            INSERT INTO eod_analysis_reports(trade_date, generated_at, market_summary, technical, strategy)
            VALUES ('2026-03-07', 1700000000000, '{"market":"steady"}', '{"2330":"bullish"}', '{"playbook":"hold"}')
            """
        )
        conn.commit()
    finally:
        conn.close()


def _make_client(tmp_path, monkeypatch: object, *, create_portfolio_json: bool = True) -> TestClient:
    db_path = tmp_path / "reports.db"
    portfolio_json = tmp_path / "portfolio.json"
    if create_portfolio_json:
        portfolio_json.write_text(
            json.dumps(
                {
                    "holdings": [
                        {"symbol": "2330", "quantity": 50, "avg_price": 610.0},
                        {"symbol": "2317", "quantity": 20, "avg_price": 120.0},
                    ]
                }
            ),
            encoding="utf-8",
        )
    _init_reports_db(db_path)

    monkeypatch.setenv("DB_PATH", db_path.as_posix())
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    monkeypatch.setenv("PORTFOLIO_JSON_PATH", portfolio_json.as_posix())

    import app.core.config as config

    importlib.reload(config)
    import app.db as db

    importlib.reload(db)
    import app.api.reports as reports

    importlib.reload(reports)
    import app.main as main

    importlib.reload(main)
    return TestClient(main.app)


def test_reports_context_returns_structured_payload(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch) as client:
        r = client.get("/api/reports/context?type=morning", headers=_AUTH)

    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert payload["report_type"] == "morning"
    assert payload["real_holdings"]["holdings"][0]["symbol"] == "2330"
    assert payload["simulated_positions"]["positions"][0]["symbol"] == "2330"
    assert payload["institution_chips"]["2330"]["total_net"] == 1100
    assert payload["technical_indicators"]["2330"]["latest_close"] == 650.0
    assert payload["recent_trades"][0]["symbol"] == "2330"
    assert payload["eod_analysis"]["trade_date"] == "2026-03-07"


def test_reports_context_tolerates_missing_optional_sources(tmp_path, monkeypatch):
    with _make_client(tmp_path, monkeypatch, create_portfolio_json=False) as client:
        r = client.get("/api/reports/context?type=weekly", headers=_AUTH)

    assert r.status_code == 200
    payload = r.json()
    assert payload["report_type"] == "weekly"
    assert payload["real_holdings"]["holdings"] == []
    assert payload["simulated_positions"]["positions"][0]["symbol"] == "2330"


def test_reports_context_invalid_type_rejected(tmp_path, monkeypatch):
    """Query param type must be morning/evening/weekly — invalid value is rejected."""
    with _make_client(tmp_path, monkeypatch) as client:
        r = client.get("/api/reports/context?type=invalid", headers=_AUTH)
    assert r.status_code >= 400


def test_reports_context_requires_auth(tmp_path, monkeypatch):
    """Missing Authorization header → 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        r = client.get("/api/reports/context")
    assert r.status_code == 401


def test_reports_context_no_chips_tables(tmp_path, monkeypatch):
    """Works when eod_institution_flows / eod_margin_data tables are absent."""
    db_path = tmp_path / "reports_nochips.db"
    conn = sqlite3.connect(db_path.as_posix())
    try:
        conn.executescript(
            """
            CREATE TABLE positions (symbol TEXT PRIMARY KEY, quantity INTEGER NOT NULL,
                avg_price REAL, current_price REAL, unrealized_pnl REAL,
                state TEXT, high_water_mark REAL, entry_trading_day TEXT);
            CREATE TABLE eod_prices (trade_date TEXT NOT NULL, symbol TEXT NOT NULL,
                name TEXT, close REAL);
            CREATE TABLE orders (order_id TEXT PRIMARY KEY, decision_id TEXT,
                broker_order_id TEXT, ts_submit TEXT NOT NULL, symbol TEXT NOT NULL,
                side TEXT NOT NULL, qty INTEGER NOT NULL, price REAL,
                order_type TEXT, tif TEXT, status TEXT NOT NULL, strategy_version TEXT);
            CREATE TABLE fills (fill_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                ts_fill TEXT, qty INTEGER NOT NULL, price REAL NOT NULL, fee REAL, tax REAL);
            """
        )
        conn.execute(
            "INSERT INTO positions VALUES ('2330', 50, 600.0, 650.0, 2500.0, 'holding', 660.0, '2026-03-01')"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setenv("DB_PATH", db_path.as_posix())
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    monkeypatch.setenv("PORTFOLIO_JSON_PATH", (tmp_path / "missing.json").as_posix())

    import app.core.config as config
    importlib.reload(config)
    import app.db as db_mod
    importlib.reload(db_mod)
    import app.api.reports as reports
    importlib.reload(reports)
    import app.main as main
    importlib.reload(main)

    with TestClient(main.app) as client:
        r = client.get("/api/reports/context?type=morning", headers=_AUTH)

    assert r.status_code == 200
    payload = r.json()
    assert payload["institution_chips"] == {}
    assert payload["eod_analysis"] is None
    assert payload["simulated_positions"]["positions"][0]["symbol"] == "2330"


def test_reports_context_db_error_returns_500(tmp_path, monkeypatch):
    """DB connection failure → 500."""
    # Create a valid DB first so app starts, then break get_conn
    db_path = tmp_path / "reports_err.db"
    _init_reports_db(db_path)

    monkeypatch.setenv("DB_PATH", db_path.as_posix())
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    monkeypatch.setenv("PORTFOLIO_JSON_PATH", (tmp_path / "missing.json").as_posix())

    import app.core.config as config
    importlib.reload(config)
    import app.db as db_mod
    importlib.reload(db_mod)
    import app.api.reports as reports_mod
    importlib.reload(reports_mod)
    import app.main as main
    importlib.reload(main)

    from contextlib import contextmanager

    @contextmanager
    def broken_conn():
        raise RuntimeError("simulated DB failure")
        yield  # noqa: unreachable

    monkeypatch.setattr(db_mod, "get_conn", broken_conn)

    with TestClient(main.app) as client:
        r = client.get("/api/reports/context?type=morning", headers=_AUTH)

    assert r.status_code == 500
