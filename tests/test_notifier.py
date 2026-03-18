"""Tests for multi-channel notifier (Issue #287).

Covers:
- notify(): Telegram success → no fallback, returns True
- notify(): Telegram failure → tries Email, Email success → returns True
- notify(): Both fail → writes incident, returns False
- notify(): Both fail, no conn → no crash, returns False
- notify(): Telegram failure + Email not configured → incident written
- flush_pending(): retries pending incidents
- _send_email(): skips when env vars missing
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import openclaw.notifier as notifier_mod
from openclaw.notifier import notify, flush_pending


# ──────────────────────────────────────────────
# DB helper
# ──────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            ts          TEXT,
            severity    TEXT,
            source      TEXT,
            code        TEXT,
            detail_json TEXT,
            resolved    INTEGER DEFAULT 0
        )"""
    )
    conn.commit()
    return conn


# ──────────────────────────────────────────────
# notify() — channel routing
# ──────────────────────────────────────────────

class TestNotify:
    def test_telegram_success_returns_true_no_email(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: True)
        email_called = []
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: email_called.append(text) or True)
        result = notify("hello")
        assert result is True
        assert email_called == []

    def test_telegram_failure_tries_email_success(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: False)
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: True)
        result = notify("hello")
        assert result is True

    def test_both_fail_returns_false(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: False)
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: False)
        result = notify("hello")
        assert result is False

    def test_both_fail_writes_incident(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: False)
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: False)
        conn = _make_db()
        notify("alert!", conn=conn)
        row = conn.execute(
            "SELECT code, detail_json, resolved FROM incidents WHERE code='NOTIFY_FAILURE'"
        ).fetchone()
        assert row is not None
        assert row[2] == 0   # unresolved
        detail = json.loads(row[1])
        assert "telegram" in detail["channels_tried"]
        assert "email" in detail["channels_tried"]
        assert "alert!" in detail["message"]

    def test_both_fail_no_conn_no_crash(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: False)
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: False)
        # Should not raise even without DB connection
        result = notify("alert!", conn=None)
        assert result is False

    def test_telegram_success_resolves_incidents(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: True)
        conn = _make_db()
        # Pre-insert an unresolved incident
        conn.execute(
            """INSERT INTO incidents (incident_id, ts, severity, source, code, detail_json, resolved)
               VALUES ('abc', datetime('now'), 'warn', 'notifier', 'NOTIFY_FAILURE', '{}', 0)"""
        )
        conn.commit()
        notify("recovered", conn=conn)
        row = conn.execute("SELECT resolved FROM incidents WHERE incident_id='abc'").fetchone()
        assert row[0] == 1   # now resolved

    def test_telegram_exception_treated_as_failure(self, monkeypatch):
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: (_ for _ in ()).throw(RuntimeError("timeout")))
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: True)
        result = notify("hello")
        assert result is True   # email fallback succeeded


# ──────────────────────────────────────────────
# flush_pending()
# ──────────────────────────────────────────────

class TestFlushPending:
    def _insert_pending(self, conn: sqlite3.Connection, msg: str, incident_id: str = "pid1") -> None:
        conn.execute(
            """INSERT INTO incidents (incident_id, ts, severity, source, code, detail_json, resolved)
               VALUES (?, datetime('now'), 'warn', 'notifier', 'NOTIFY_FAILURE', ?, 0)""",
            (incident_id, json.dumps({"message": msg, "channels_tried": ["telegram", "email"]})),
        )
        conn.commit()

    def test_no_pending_returns_zero(self, monkeypatch):
        conn = _make_db()
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: True)
        assert flush_pending(conn) == 0

    def test_retries_and_resolves_on_success(self, monkeypatch):
        conn = _make_db()
        self._insert_pending(conn, "original alert")
        sent = []
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: sent.append(text) or True)
        result = flush_pending(conn)
        assert result == 1
        assert any("補發" in m for m in sent)
        row = conn.execute("SELECT resolved FROM incidents WHERE incident_id='pid1'").fetchone()
        assert row[0] == 1

    def test_does_not_resolve_on_continued_failure(self, monkeypatch):
        conn = _make_db()
        self._insert_pending(conn, "still failing")
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: False)
        monkeypatch.setattr(notifier_mod, "_send_email", lambda text: False)
        result = flush_pending(conn)
        assert result == 0
        row = conn.execute("SELECT resolved FROM incidents WHERE incident_id='pid1'").fetchone()
        assert row[0] == 0   # still unresolved

    def test_multiple_pending_all_resolved(self, monkeypatch):
        conn = _make_db()
        for i in range(3):
            self._insert_pending(conn, f"msg{i}", f"pid{i}")
        monkeypatch.setattr(notifier_mod, "_tg_send", lambda text: True)
        result = flush_pending(conn)
        assert result == 3

    def test_missing_incidents_table_no_crash(self, monkeypatch):
        conn = sqlite3.connect(":memory:")   # no table
        result = flush_pending(conn)
        assert result == 0


# ──────────────────────────────────────────────
# _send_email() env var guard
# ──────────────────────────────────────────────

class TestSendEmailEnvGuard:
    def test_returns_false_when_no_recipient(self, monkeypatch):
        monkeypatch.delenv("NOTIFY_EMAIL_TO", raising=False)
        from openclaw.notifier import _send_email
        assert _send_email("test") is False

    def test_returns_false_when_incomplete_config(self, monkeypatch):
        monkeypatch.setenv("NOTIFY_EMAIL_TO", "test@example.com")
        monkeypatch.delenv("NOTIFY_EMAIL_FROM", raising=False)
        monkeypatch.delenv("NOTIFY_EMAIL_USER", raising=False)
        from openclaw.notifier import _send_email
        assert _send_email("test") is False
