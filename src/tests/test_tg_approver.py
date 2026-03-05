"""Tests for tg_approver.py."""
from __future__ import annotations

import json
import sqlite3
import types
import uuid
from unittest.mock import MagicMock, patch

import pytest

from openclaw.tg_approver import (
    _fmt_symbol,
    _symbol_name,
    _wm_get,
    _wm_set,
    notify_pending_proposals,
    poll_approval_callbacks,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT NOT NULL,
            market TEXT NOT NULL DEFAULT 'TWSE',
            symbol TEXT NOT NULL,
            name TEXT,
            close REAL,
            source_url TEXT NOT NULL DEFAULT '',
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (trade_date, market, symbol)
        );
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id   TEXT PRIMARY KEY,
            generated_by  TEXT,
            target_rule   TEXT NOT NULL,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence    REAL DEFAULT 0,
            requires_human_approval INTEGER DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'pending',
            proposal_json TEXT,
            created_at    INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS working_memory (
            wm_id        TEXT PRIMARY KEY,
            session_date TEXT NOT NULL,
            scope        TEXT NOT NULL,
            key          TEXT NOT NULL,
            value_json   TEXT NOT NULL,
            importance   REAL NOT NULL DEFAULT 0.5,
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        );
    """)
    return conn


@pytest.fixture
def conn():
    c = _make_conn()
    yield c
    c.close()


@pytest.fixture
def conn_with_data(conn):
    """Conn pre-loaded with eod_prices + 2 pending proposals."""
    conn.execute(
        "INSERT INTO eod_prices(trade_date, symbol, name, close, market) VALUES(?,?,?,?,?)",
        ("2026-03-05", "3008", "大立光", 2500.0, "TWSE"),
    )
    pid1 = str(uuid.uuid4())
    pid2 = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO strategy_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid1, "concentration_guard", "POSITION_REBALANCE", None, None,
         json.dumps({"symbol": "3008", "action": "sell", "quantity": 10,
                     "target_price": 2450.0, "reduce_pct": 0.2}),
         "超過 40% 集中度上限", 0.85, 1, "pending", "{}", 1772700000000),
    )
    conn.execute(
        "INSERT INTO strategy_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid2, "system_health", "SECTOR_FOCUS", None, None,
         json.dumps({"sector": "電子", "bias": "overweight"}),
         "電子板塊強勢", 0.7, 1, "pending", "{}", 1772701000000),
    )
    conn.commit()
    return conn, pid1, pid2


# ── _symbol_name / _fmt_symbol ────────────────────────────────────────────────

def test_symbol_name_found(conn):
    conn.execute("INSERT INTO eod_prices VALUES(?,?,?,?,?,?,?)",
                 ("2026-03-05", "TWSE", "2330", "台積電", 900.0, "", "now"))
    conn.commit()
    assert _symbol_name(conn, "2330") == "台積電"


def test_symbol_name_not_found(conn):
    assert _symbol_name(conn, "9999") == "9999"


def test_fmt_symbol_with_name(conn):
    conn.execute("INSERT INTO eod_prices VALUES(?,?,?,?,?,?,?)",
                 ("2026-03-05", "TWSE", "3008", "大立光", 2500.0, "", "now"))
    conn.commit()
    assert _fmt_symbol(conn, "3008") == "3008 大立光"


def test_fmt_symbol_no_name(conn):
    assert _fmt_symbol(conn, "9999") == "9999"


def test_fmt_symbol_empty(conn):
    assert _fmt_symbol(conn, "") == ""


# ── _wm_get / _wm_set ─────────────────────────────────────────────────────────

def test_wm_get_missing(conn):
    assert _wm_get(conn, "nonexistent") is None


def test_wm_set_and_get(conn):
    _wm_set(conn, "test_key", [1, 2, 3])
    assert _wm_get(conn, "test_key") == [1, 2, 3]


def test_wm_set_upsert(conn):
    _wm_set(conn, "my_key", {"v": 1})
    _wm_set(conn, "my_key", {"v": 2})
    assert _wm_get(conn, "my_key") == {"v": 2}


# ── notify_pending_proposals ──────────────────────────────────────────────────

def test_notify_no_token(conn_with_data, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    c, pid1, pid2 = conn_with_data
    assert notify_pending_proposals(c) == 0


def test_notify_sends_for_new_proposals(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, pid2 = conn_with_data

    with patch("openclaw.tg_notify.send_message_with_buttons", return_value=True) as mock_send:
        n = notify_pending_proposals(c)

    assert n == 2
    assert mock_send.call_count == 2


def test_notify_skips_already_notified(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, pid2 = conn_with_data

    # Pre-populate notified IDs
    _wm_set(c, "notified_ids", [pid1, pid2])

    with patch("openclaw.tg_notify.send_message_with_buttons", return_value=True) as mock_send:
        n = notify_pending_proposals(c)

    assert n == 0
    assert mock_send.call_count == 0


def test_notify_saves_notified_ids(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, pid2 = conn_with_data

    with patch("openclaw.tg_notify.send_message_with_buttons", return_value=True):
        notify_pending_proposals(c)

    saved = _wm_get(c, "notified_ids")
    assert set(saved) == {pid1, pid2}


def test_notify_message_includes_symbol_name(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, pid2 = conn_with_data

    call_texts = []

    def fake_send(text, buttons, chat_id=None):
        call_texts.append(text)
        return True

    with patch("openclaw.tg_notify.send_message_with_buttons", side_effect=fake_send):
        notify_pending_proposals(c)

    # One of the messages should include "3008 大立光" (POSITION_REBALANCE)
    assert any("3008 大立光" in t for t in call_texts)


def test_notify_skips_strategy_direction(conn, monkeypatch):
    """STRATEGY_DIRECTION proposals should NOT be notified."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    conn.execute(
        "INSERT INTO strategy_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), "agents", "STRATEGY_DIRECTION", None, None,
         json.dumps({"direction": "bullish"}), "reason", 0.8, 0, "pending", "{}", 1772700000000),
    )
    conn.commit()

    with patch("openclaw.tg_notify.send_message_with_buttons", return_value=True) as mock_send:
        n = notify_pending_proposals(conn)

    assert n == 0
    assert mock_send.call_count == 0


# ── poll_approval_callbacks ───────────────────────────────────────────────────

def _make_callback_update(update_id: int, cb_id: str, data: str) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": cb_id,
            "data": data,
            "from": {"id": 123, "first_name": "Boss"},
            "message": {"chat": {"id": 1017252031}},
        },
    }


def test_poll_no_token(conn, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert poll_approval_callbacks(conn) == 0


def test_poll_approve_updates_status(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, _ = conn_with_data

    updates_resp = {"ok": True, "result": [
        _make_callback_update(100, "cb1", f"approve:{pid1}"),
    ]}

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("openclaw.tg_notify.send_message", return_value=True):
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(updates_resp).encode()
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp_mock

        n = poll_approval_callbacks(c)

    assert n == 1
    row = c.execute("SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid1,)).fetchone()
    assert row["status"] == "approved"


def test_poll_reject_updates_status(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, _, pid2 = conn_with_data

    updates_resp = {"ok": True, "result": [
        _make_callback_update(200, "cb2", f"reject:{pid2}"),
    ]}

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("openclaw.tg_notify.send_message", return_value=True):
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(updates_resp).encode()
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp_mock

        n = poll_approval_callbacks(c)

    assert n == 1
    row = c.execute("SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid2,)).fetchone()
    assert row["status"] == "rejected"


def test_poll_advances_offset(conn_with_data, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    c, pid1, _ = conn_with_data

    updates_resp = {"ok": True, "result": [
        _make_callback_update(300, "cb3", f"approve:{pid1}"),
    ]}

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("openclaw.tg_notify.send_message", return_value=True):
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(updates_resp).encode()
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp_mock

        poll_approval_callbacks(c)

    assert _wm_get(c, "update_offset") == 301


def test_poll_empty_updates(conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    updates_resp = {"ok": True, "result": []}

    with patch("urllib.request.urlopen") as mock_urlopen:
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(updates_resp).encode()
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp_mock

        n = poll_approval_callbacks(conn)

    assert n == 0


def test_poll_network_error(conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        n = poll_approval_callbacks(conn)

    assert n == 0


def test_poll_unknown_proposal_id(conn, monkeypatch):
    """Callback referencing non-existent proposal returns 0 processed."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    fake_id = str(uuid.uuid4())
    updates_resp = {"ok": True, "result": [
        _make_callback_update(400, "cb4", f"approve:{fake_id}"),
    ]}

    with patch("urllib.request.urlopen") as mock_urlopen, \
         patch("openclaw.tg_approver._answer_callback"):
        resp_mock = MagicMock()
        resp_mock.read.return_value = json.dumps(updates_resp).encode()
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp_mock

        n = poll_approval_callbacks(conn)

    assert n == 0
