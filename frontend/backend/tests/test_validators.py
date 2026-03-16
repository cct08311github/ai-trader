"""Tests for app/validators.py — unit tests and API-level 422 integration tests."""
from __future__ import annotations

import importlib
import json
import sqlite3

import pytest
from fastapi import HTTPException

# ─── Unit tests for validate_symbol ──────────────────────────────────────────

def test_validate_symbol_valid_4digit():
    from app.validators import validate_symbol
    assert validate_symbol("2330") == "2330"


def test_validate_symbol_valid_5digit():
    from app.validators import validate_symbol
    assert validate_symbol("00878") == "00878"


def test_validate_symbol_valid_6digit():
    from app.validators import validate_symbol
    assert validate_symbol("620800") == "620800"


def test_validate_symbol_valid_6208():
    from app.validators import validate_symbol
    assert validate_symbol("6208") == "6208"


def test_validate_symbol_strips_whitespace():
    from app.validators import validate_symbol
    assert validate_symbol("  2330  ") == "2330"


def test_validate_symbol_lowercased_converted():
    # digits don't have case, but mixed alphanumeric should fail
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("abc")
    assert exc_info.value.status_code == 422


def test_validate_symbol_invalid_alpha():
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("abc")
    assert exc_info.value.status_code == 422
    assert "Invalid symbol format" in exc_info.value.detail


def test_validate_symbol_invalid_empty():
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("")
    assert exc_info.value.status_code == 422


def test_validate_symbol_invalid_too_short():
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("12")
    assert exc_info.value.status_code == 422


def test_validate_symbol_invalid_too_long():
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("1234567")
    assert exc_info.value.status_code == 422


def test_validate_symbol_invalid_decimal():
    from app.validators import validate_symbol
    with pytest.raises(HTTPException) as exc_info:
        validate_symbol("23.30")
    assert exc_info.value.status_code == 422


# ─── Unit tests for validate_quantity ────────────────────────────────────────

def test_validate_quantity_valid_1():
    from app.validators import validate_quantity
    assert validate_quantity(1) == 1


def test_validate_quantity_valid_1000():
    from app.validators import validate_quantity
    assert validate_quantity(1000) == 1000


def test_validate_quantity_valid_5000():
    from app.validators import validate_quantity
    assert validate_quantity(5000) == 5000


def test_validate_quantity_invalid_zero():
    from app.validators import validate_quantity
    with pytest.raises(HTTPException) as exc_info:
        validate_quantity(0)
    assert exc_info.value.status_code == 422
    assert "Invalid quantity" in exc_info.value.detail


def test_validate_quantity_invalid_negative():
    from app.validators import validate_quantity
    with pytest.raises(HTTPException) as exc_info:
        validate_quantity(-1)
    assert exc_info.value.status_code == 422


def test_validate_quantity_invalid_string():
    from app.validators import validate_quantity
    with pytest.raises(HTTPException) as exc_info:
        validate_quantity("abc")
    assert exc_info.value.status_code == 422


# ─── API-level 422 integration tests ─────────────────────────────────────────

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _init_full_db(path):
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            broker_order_id TEXT,
            ts_submit TEXT,
            symbol TEXT,
            side TEXT,
            qty REAL,
            price REAL,
            order_type TEXT,
            tif TEXT,
            status TEXT,
            strategy_version TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT,
            order_id TEXT,
            ts_fill TEXT,
            qty REAL,
            price REAL,
            fee REAL,
            tax REAL,
            symbol TEXT,
            side TEXT,
            filled_at REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            avg_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            chip_health_score REAL,
            sector TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            status TEXT,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            confidence REAL,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY,
            ts TEXT,
            symbol TEXT,
            strategy_id TEXT,
            strategy_version TEXT,
            signal_side TEXT,
            signal_score REAL,
            signal_ttl_ms INTEGER,
            llm_ref TEXT,
            reason_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_checks (
            check_id TEXT PRIMARY KEY,
            decision_id TEXT,
            ts TEXT,
            passed INTEGER,
            reject_code TEXT,
            metrics_json TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT NOT NULL,
            market TEXT NOT NULL DEFAULT 'TWSE',
            symbol TEXT NOT NULL,
            name TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            source_url TEXT NOT NULL DEFAULT '',
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (trade_date, market, symbol)
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture()
def full_client(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    _init_full_db(db_path)

    monkeypatch.setenv("DB_PATH", db_path.as_posix())
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", _TOKEN)

    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


# lock endpoint — invalid symbol
@pytest.mark.parametrize("bad_sym", ["abc", "12", "1234567", "23.30"])
def test_lock_invalid_symbol_returns_422(full_client, bad_sym):
    r = full_client.post(f"/api/portfolio/lock/{bad_sym}", headers=_AUTH)
    assert r.status_code == 422, f"Expected 422 for symbol={bad_sym!r}, got {r.status_code}"


# lock endpoint — valid symbol accepted (writes file; tmp_path isolated)
@pytest.mark.parametrize("good_sym", ["2330", "00878", "6208"])
def test_lock_valid_symbol_accepted(full_client, tmp_path, good_sym):
    import json, os
    # Provide a writable locked_symbols.json in tmp_path
    locked_path = tmp_path / "locked_symbols.json"
    locked_path.write_text(json.dumps({"locked": []}))

    import app.api.portfolio as port
    original = port._LOCKED_PATH
    port._LOCKED_PATH = str(locked_path)
    try:
        r = full_client.post(f"/api/portfolio/lock/{good_sym}", headers=_AUTH)
        assert r.status_code == 200, f"Expected 200 for symbol={good_sym!r}, got {r.status_code}: {r.text}"
    finally:
        port._LOCKED_PATH = original


# unlock endpoint — invalid symbol
@pytest.mark.parametrize("bad_sym", ["abc", "12", "1234567", "23.30"])
def test_unlock_invalid_symbol_returns_422(full_client, bad_sym):
    r = full_client.delete(f"/api/portfolio/lock/{bad_sym}", headers=_AUTH)
    assert r.status_code == 422, f"Expected 422 for symbol={bad_sym!r}, got {r.status_code}"


# close-position endpoint — invalid symbol
@pytest.mark.parametrize("bad_sym", ["abc", "12", "1234567", "23.30"])
def test_close_position_invalid_symbol_returns_422(full_client, bad_sym):
    r = full_client.post(f"/api/portfolio/close-position/{bad_sym}", headers=_AUTH)
    assert r.status_code == 422, f"Expected 422 for symbol={bad_sym!r}, got {r.status_code}"
