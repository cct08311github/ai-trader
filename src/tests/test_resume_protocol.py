"""Tests for src/openclaw/resume_protocol.py"""

import json
import sqlite3
import importlib
import datetime
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_conn():
    """Return an in-memory SQLite connection that already has the
    position_snapshots table created."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE position_snapshots (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            system_state_json TEXT NOT NULL,
            positions_json    TEXT NOT NULL,
            available_cash    REAL,
            reason            TEXT
        )
    """)
    return conn


@pytest.fixture(autouse=True)
def patch_db_dir(tmp_path, monkeypatch):
    """Keep db_router pointing at a temp dir to avoid touching real disk DBs."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
    import openclaw.db_router as dbr
    importlib.reload(dbr)


def _make_tracker_with_mem_conn(mem_conn):
    """Return a ResumeProtocolTracker whose get_connection calls use mem_conn."""
    from openclaw.resume_protocol import ResumeProtocolTracker
    tracker = ResumeProtocolTracker()

    # Patch get_connection inside resume_protocol to return our in-memory conn.
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mem_conn)
    cm.__exit__ = MagicMock(return_value=False)

    with patch("openclaw.resume_protocol.get_connection", return_value=cm):
        yield tracker, cm


# ---------------------------------------------------------------------------
# ResumeProtocolTracker.snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_returns_true_on_first_call(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            result = tracker.snapshot({"mode": "ok"}, [], 100_000.0)

        assert result is True

    def test_snapshot_writes_to_db(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            tracker.snapshot({"mode": "ok"}, [{"symbol": "2330"}], 50_000.0, reason="startup")

        row = mem_conn.execute("SELECT * FROM position_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert json.loads(row["system_state_json"]) == {"mode": "ok"}
        assert json.loads(row["positions_json"]) == [{"symbol": "2330"}]
        assert row["available_cash"] == 50_000.0
        assert row["reason"] == "startup"

    def test_periodic_snapshot_skipped_within_interval(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker(check_interval_sec=300)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            # First call sets _last_snapshot_time
            r1 = tracker.snapshot({"mode": "ok"}, [], 100_000.0, reason="periodic")
            # Second call within the same 5-minute window should be skipped
            r2 = tracker.snapshot({"mode": "ok"}, [], 100_000.0, reason="periodic")

        assert r1 is True
        assert r2 is False  # skipped

    def test_periodic_snapshot_allowed_after_interval(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker(check_interval_sec=1)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        # Manually set _last_snapshot_time far in the past
        tracker._last_snapshot_time = datetime.datetime.utcnow() - datetime.timedelta(seconds=10)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            result = tracker.snapshot({"mode": "ok"}, [], 100_000.0, reason="periodic")

        assert result is True

    def test_non_periodic_reason_always_writes(self, mem_conn):
        """Snapshots with reason != 'periodic' bypass the interval check."""
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker(check_interval_sec=300)
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            r1 = tracker.snapshot({"mode": "ok"}, [], 100_000.0, reason="startup")
            r2 = tracker.snapshot({"mode": "ok"}, [], 100_000.0, reason="shutdown")

        assert r1 is True
        assert r2 is True

    def test_snapshot_returns_false_on_db_error(self):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker()
        with patch("openclaw.resume_protocol.get_connection", side_effect=Exception("DB error")):
            result = tracker.snapshot({"mode": "ok"}, [], 100_000.0)

        assert result is False


# ---------------------------------------------------------------------------
# ResumeProtocolTracker.load_latest_snapshot
# ---------------------------------------------------------------------------

class TestLoadLatestSnapshot:
    def test_returns_none_when_no_snapshots(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            result = tracker.load_latest_snapshot()

        assert result is None

    def test_returns_latest_snapshot(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        # Insert a row directly
        mem_conn.execute(
            "INSERT INTO position_snapshots (system_state_json, positions_json, available_cash, reason) "
            "VALUES (?, ?, ?, ?)",
            ('{"mode":"halted"}', '[{"symbol":"2330","qty":1000}]', 75_000.0, "manual"),
        )

        tracker = ResumeProtocolTracker()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            result = tracker.load_latest_snapshot()

        assert result is not None
        assert result["system_state"] == {"mode": "halted"}
        assert result["positions"] == [{"symbol": "2330", "qty": 1000}]
        assert result["available_cash"] == 75_000.0
        assert result["reason"] == "manual"
        assert "timestamp" in result

    def test_returns_most_recent_of_multiple_snapshots(self, mem_conn):
        from openclaw.resume_protocol import ResumeProtocolTracker

        # Use explicit, distinct timestamps so the ORDER BY DESC is deterministic.
        rows = [
            ("2024-01-01 10:00:00", "first"),
            ("2024-01-01 11:00:00", "second"),
            ("2024-01-01 12:00:00", "third"),
        ]
        for ts, reason in rows:
            mem_conn.execute(
                "INSERT INTO position_snapshots (timestamp, system_state_json, positions_json, available_cash, reason) "
                "VALUES (?, ?, ?, ?, ?)",
                (ts, '{}', '[]', 0.0, reason),
            )

        tracker = ResumeProtocolTracker()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=mem_conn)
        cm.__exit__ = MagicMock(return_value=False)

        with patch("openclaw.resume_protocol.get_connection", return_value=cm):
            result = tracker.load_latest_snapshot()

        # "third" has the latest timestamp and should be returned (ORDER BY timestamp DESC)
        assert result["reason"] == "third"

    def test_returns_none_on_db_error(self):
        from openclaw.resume_protocol import ResumeProtocolTracker

        tracker = ResumeProtocolTracker()
        with patch("openclaw.resume_protocol.get_connection", side_effect=Exception("fail")):
            result = tracker.load_latest_snapshot()

        assert result is None


# ---------------------------------------------------------------------------
# system_self_check
# ---------------------------------------------------------------------------

class TestSystemSelfCheck:
    def test_clean_start_when_no_snapshot(self):
        from openclaw.resume_protocol import system_self_check

        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = None

            result = system_self_check()

        assert result["status"] == "clean"

    def test_ok_when_last_state_is_normal(self):
        from openclaw.resume_protocol import system_self_check

        fake_snap = {
            "timestamp": "2024-01-01 12:00:00",
            "system_state": {"mode": "active"},
            "positions": [{"symbol": "2330"}],
            "available_cash": 100_000.0,
            "reason": "periodic",
        }
        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = fake_snap

            result = system_self_check()

        assert result["status"] == "ok"
        assert result["details"] == fake_snap

    def test_needs_resume_when_halted(self):
        from openclaw.resume_protocol import system_self_check

        fake_snap = {
            "timestamp": "2024-01-01 10:00:00",
            "system_state": {"mode": "halt"},
            "positions": [],
            "available_cash": 0.0,
            "reason": "emergency",
        }
        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = fake_snap

            result = system_self_check()

        assert result["status"] == "needs_resume"
        assert result["details"] == fake_snap

    def test_needs_resume_when_suspended(self):
        from openclaw.resume_protocol import system_self_check

        fake_snap = {
            "timestamp": "2024-01-01 09:00:00",
            "system_state": {"mode": "suspended"},
            "positions": [],
            "available_cash": 0.0,
            "reason": "auto-suspend",
        }
        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = fake_snap

            result = system_self_check()

        assert result["status"] == "needs_resume"


# ---------------------------------------------------------------------------
# run_resume_flow
# ---------------------------------------------------------------------------

class TestRunResumeFlow:
    def test_returns_false_when_no_snapshot(self):
        from openclaw.resume_protocol import run_resume_flow

        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = None

            result = run_resume_flow()

        assert result is False

    def test_returns_true_when_snapshot_exists(self):
        from openclaw.resume_protocol import run_resume_flow

        fake_snap = {
            "timestamp": "2024-01-01 08:00:00",
            "system_state": {"mode": "active"},
            "positions": [{"symbol": "2330"}, {"symbol": "2454"}],
            "available_cash": 200_000.0,
            "reason": "periodic",
        }
        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = fake_snap

            result = run_resume_flow()

        assert result is True

    def test_force_flag_accepted(self):
        """run_resume_flow accepts a force kwarg without raising."""
        from openclaw.resume_protocol import run_resume_flow

        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = None

            result = run_resume_flow(force=True)

        assert result is False

    def test_logs_position_count(self, caplog):
        """Ensure the function logs position info (smoke test for logging path)."""
        import logging
        from openclaw.resume_protocol import run_resume_flow

        fake_snap = {
            "timestamp": "2024-01-01 08:00:00",
            "system_state": {"mode": "ok"},
            "positions": [{"symbol": "2330"}, {"symbol": "2454"}, {"symbol": "6505"}],
            "available_cash": 300_000.0,
            "reason": "startup",
        }
        with patch("openclaw.resume_protocol.ResumeProtocolTracker") as MockTracker:
            instance = MockTracker.return_value
            instance.load_latest_snapshot.return_value = fake_snap

            with caplog.at_level(logging.INFO, logger="resume_protocol"):
                result = run_resume_flow()

        assert result is True
        # Some log message about positions should appear
        assert any("3" in msg for msg in caplog.messages)
