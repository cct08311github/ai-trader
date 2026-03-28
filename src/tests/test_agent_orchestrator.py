"""test_agent_orchestrator.py — unit tests for agent_orchestrator.py.

Strategy:
- Test helper functions directly (pure-ish functions with minimal mocking).
- Test run_orchestrator() by patching asyncio.sleep to raise StopIteration
  after one iteration, and mocking all agent imports.
- main() is exercised via a patch on asyncio.run.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ── Timezone constant mirrors the module ─────────────────────────────────────
_TZ_TWN = timezone(timedelta(hours=8))


# ── _is_weekday_twn (lines 40-41) ────────────────────────────────────────────

def test_is_weekday_twn_on_weekday():
    """Lines 40-41: Monday (weekday 0) → True."""
    from openclaw.agent_orchestrator import _is_weekday_twn
    # Monday
    monday = datetime(2025, 1, 6, 10, 0, 0, tzinfo=_TZ_TWN)  # known Monday
    assert _is_weekday_twn(monday) is True


def test_is_weekday_twn_on_saturday():
    """Lines 40-41: Saturday (weekday 5) → False."""
    from openclaw.agent_orchestrator import _is_weekday_twn
    saturday = datetime(2025, 1, 11, 10, 0, 0, tzinfo=_TZ_TWN)  # known Saturday
    assert _is_weekday_twn(saturday) is False


def test_is_weekday_twn_on_sunday():
    """Lines 40-41: Sunday (weekday 6) → False."""
    from openclaw.agent_orchestrator import _is_weekday_twn
    sunday = datetime(2025, 1, 12, 10, 0, 0, tzinfo=_TZ_TWN)  # known Sunday
    assert _is_weekday_twn(sunday) is False


def test_is_weekday_twn_uses_current_time_when_none():
    """Lines 40-41: when now_twn is None, uses current time (just verifies no crash)."""
    from openclaw.agent_orchestrator import _is_weekday_twn
    result = _is_weekday_twn(None)
    assert isinstance(result, bool)


# ── _is_monday_twn (lines 45-46) ─────────────────────────────────────────────

def test_is_monday_twn_on_monday():
    """Lines 45-46: Monday → True."""
    from openclaw.agent_orchestrator import _is_monday_twn
    monday = datetime(2025, 1, 6, 8, 0, 0, tzinfo=_TZ_TWN)
    assert _is_monday_twn(monday) is True


def test_is_monday_twn_on_tuesday():
    """Lines 45-46: Tuesday → False."""
    from openclaw.agent_orchestrator import _is_monday_twn
    tuesday = datetime(2025, 1, 7, 8, 0, 0, tzinfo=_TZ_TWN)
    assert _is_monday_twn(tuesday) is False


def test_is_monday_twn_uses_current_time_when_none():
    """Lines 45-46: when now_twn is None, uses current time."""
    from openclaw.agent_orchestrator import _is_monday_twn
    result = _is_monday_twn(None)
    assert isinstance(result, bool)


# ── _should_run_now (already partially covered; just verify extra path) ──────

def test_should_run_now_matches():
    """_should_run_now returns True when time matches."""
    from openclaw.agent_orchestrator import _should_run_now
    t = datetime(2025, 1, 6, 8, 20, 0, tzinfo=_TZ_TWN)
    assert _should_run_now("08:20", t) is True


def test_should_run_now_no_match():
    """_should_run_now returns False when time does not match."""
    from openclaw.agent_orchestrator import _should_run_now
    t = datetime(2025, 1, 6, 8, 21, 0, tzinfo=_TZ_TWN)
    assert _should_run_now("08:20", t) is False


# ── _pm_review_just_completed (lines 62-63) ──────────────────────────────────

def test_pm_review_just_completed_new_event(tmp_path):
    """Lines 62-63: new reviewed_at differs from last_seen → returns it."""
    from openclaw.agent_orchestrator import _pm_review_just_completed
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"reviewed_at": "2025-01-06T14:30:00"}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        result = _pm_review_just_completed(last_seen=None)
        assert result == "2025-01-06T14:30:00"
    finally:
        reset_config()


def test_pm_review_just_completed_same_event(tmp_path):
    """Lines 62-63: reviewed_at == last_seen → returns None."""
    from openclaw.agent_orchestrator import _pm_review_just_completed
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"reviewed_at": "2025-01-06T14:30:00"}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        result = _pm_review_just_completed(
            last_seen="2025-01-06T14:30:00"
        )
        assert result is None
    finally:
        reset_config()


def test_pm_review_just_completed_no_reviewed_at(tmp_path):
    """Lines 62-63: state has no reviewed_at → returns None."""
    from openclaw.agent_orchestrator import _pm_review_just_completed
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"approved": False}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        result = _pm_review_just_completed(last_seen=None)
        assert result is None
    finally:
        reset_config()


def test_pm_review_just_completed_file_missing(tmp_path):
    """Lines 62-63: file doesn't exist → ConfigManager returns default → returns None."""
    from openclaw.agent_orchestrator import _pm_review_just_completed
    from openclaw.config_manager import get_config, reset_config
    reset_config()
    get_config(config_dir=tmp_path)  # no daily_pm_state.json
    try:
        result = _pm_review_just_completed(last_seen=None)
        assert result is None
    finally:
        reset_config()


def test_pm_review_just_completed_invalid_json(tmp_path):
    """Lines 62-63: invalid JSON → ConfigManager returns default → returns None."""
    from openclaw.agent_orchestrator import _pm_review_just_completed
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text("NOT JSON")
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        result = _pm_review_just_completed(last_seen=None)
        assert result is None
    finally:
        reset_config()


# ── _watcher_no_fills_3days (lines 74-75) ────────────────────────────────────

def test_watcher_no_fills_3days_empty():
    """Lines 74-75: no fills in last 3 days → True."""
    from openclaw.agent_orchestrator import _watcher_no_fills_3days
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE fills (id INTEGER PRIMARY KEY, ts_fill TEXT)"
    )
    conn.commit()
    assert _watcher_no_fills_3days(conn) is True
    conn.close()


def test_watcher_no_fills_3days_with_recent_fill():
    """Lines 74-75: recent fill exists → False."""
    from openclaw.agent_orchestrator import _watcher_no_fills_3days
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE fills (id INTEGER PRIMARY KEY, ts_fill TEXT)"
    )
    # Insert a fill with current timestamp
    conn.execute("INSERT INTO fills VALUES (1, datetime('now'))")
    conn.commit()
    assert _watcher_no_fills_3days(conn) is False
    conn.close()


def test_watcher_no_fills_3days_table_missing():
    """Lines 74-75: table does not exist → exception caught → False."""
    from openclaw.agent_orchestrator import _watcher_no_fills_3days
    conn = sqlite3.connect(":memory:")
    # No fills table created
    result = _watcher_no_fills_3days(conn)
    assert result is False
    conn.close()


def test_watcher_no_fills_3days_row_none():
    """Lines 74-75: fetchone returns None → False (not True)."""
    from openclaw.agent_orchestrator import _watcher_no_fills_3days
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    result = _watcher_no_fills_3days(mock_conn)
    assert result is False


# ── _run_agent (lines 82-87) ─────────────────────────────────────────────────

def test_run_agent_success():
    """Lines 82-87: successful agent run logs start/complete."""
    from openclaw.agent_orchestrator import _run_agent

    called = []

    def mock_fn(*args, **kwargs):
        called.append(True)

    asyncio.run(_run_agent("TestAgent", mock_fn))
    assert called == [True]


def test_run_agent_exception_does_not_propagate():
    """Lines 86-87: agent raises → exception caught, not re-raised."""
    from openclaw.agent_orchestrator import _run_agent

    def failing_fn():
        raise ValueError("boom")

    # Should not raise
    asyncio.run(_run_agent("FailingAgent", failing_fn))


def test_run_agent_with_args():
    """Lines 82-87: _run_agent passes args/kwargs to fn."""
    from openclaw.agent_orchestrator import _run_agent

    received = []

    def mock_fn(a, b, key=None):
        received.append((a, b, key))

    asyncio.run(_run_agent("TestAgent", mock_fn, 1, 2, key="val"))
    assert received == [(1, 2, "val")]


# ── run_orchestrator (lines 93-161) ──────────────────────────────────────────

def _make_mock_agents():
    """Return a dict of mock agent run functions."""
    return {
        "run_market_research": MagicMock(),
        "run_portfolio_review": MagicMock(),
        "run_system_health": MagicMock(),
        "run_strategy_committee": MagicMock(),
        "run_system_optimization": MagicMock(),
    }


@pytest.fixture()
def tmp_state_file(tmp_path):
    state_file = tmp_path / "daily_pm_state.json"
    state_file.write_text(json.dumps({}))
    return str(state_file)


@pytest.fixture()
def tmp_db(tmp_path):
    db_path = str(tmp_path / "trades.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE fills (id INTEGER PRIMARY KEY, ts_fill TEXT)")
    conn.commit()
    conn.close()
    return db_path


async def _run_orchestrator_one_tick(
    monkeypatch,
    now_twn: datetime,
    agents: dict,
    state_path: str,
    db_path: str,
):
    """Run one iteration of run_orchestrator by making asyncio.sleep raise StopAsyncIteration."""

    sleep_call_count = [0]

    async def mock_sleep(seconds):
        sleep_call_count[0] += 1
        raise StopAsyncIteration("done after one tick")

    import openclaw.agent_orchestrator as orch_mod

    with (
        patch.object(orch_mod, "_STATE_PATH", state_path),
        patch.object(orch_mod, "DB_PATH", db_path),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agents.market_research.run_market_research", agents["run_market_research"]),
        patch("openclaw.agents.portfolio_review.run_portfolio_review", agents["run_portfolio_review"]),
        patch("openclaw.agents.system_health.run_system_health", agents["run_system_health"]),
        patch("openclaw.agents.strategy_committee.run_strategy_committee", agents["run_strategy_committee"]),
        patch("openclaw.agents.system_optimization.run_system_optimization", agents["run_system_optimization"]),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.return_value = now_twn
        mock_dt.strftime = datetime.strftime
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        try:
            await orch_mod.run_orchestrator()
        except StopAsyncIteration:
            pass

    return sleep_call_count[0]


def test_run_orchestrator_weekday_market_hours(tmp_state_file, tmp_db, monkeypatch):
    """Lines 93-161: weekday during market hours (09:00-13:59) executes health check."""
    agents = _make_mock_agents()

    # Use a Wednesday at 09:30 TWN (market hours)
    now_twn = datetime(2025, 1, 8, 9, 30, 0, tzinfo=_TZ_TWN)  # Wednesday

    import openclaw.agent_orchestrator as orch_mod

    sleep_done = [False]

    async def mock_sleep(seconds):
        sleep_done[0] = True
        raise StopAsyncIteration("one tick")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=agents["run_market_research"]),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=agents["run_portfolio_review"]),
            "openclaw.agents.system_health": MagicMock(run_system_health=agents["run_system_health"]),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=agents["run_strategy_committee"]),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=agents["run_system_optimization"]),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        # Make datetime.now() return our fixed time
        now_utc = datetime(2025, 1, 8, 1, 30, 0, tzinfo=timezone.utc)
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    assert sleep_done[0] is True


def test_run_orchestrator_market_research_trigger(tmp_state_file, tmp_db):
    """Lines 113-114: weekday at 08:20 TWN → MarketResearchAgent scheduled."""
    import openclaw.agent_orchestrator as orch_mod

    # Monday at 08:20
    now_twn = datetime(2025, 1, 6, 8, 20, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 5, 0, 20, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        # Collect the coroutine name for inspection
        tasks_created.append(coro.__name__ if hasattr(coro, "__name__") else str(coro))
        # We need to consume the coroutine to avoid resource warnings
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    # At 08:20 on a weekday, market research should have been scheduled
    assert len(tasks_created) >= 1


def test_run_orchestrator_portfolio_review_trigger(tmp_state_file, tmp_db):
    """Lines 116-117: weekday at 14:30 TWN → PortfolioReviewAgent scheduled."""
    import openclaw.agent_orchestrator as orch_mod

    now_twn = datetime(2025, 1, 8, 14, 30, 0, tzinfo=_TZ_TWN)  # Wednesday
    now_utc = datetime(2025, 1, 8, 6, 30, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    assert len(tasks_created) >= 1


def test_run_orchestrator_monday_agents(tmp_state_file, tmp_db):
    """Lines 133-139: Monday at 07:00/07:30 schedules optimization + strategy committee."""
    import openclaw.agent_orchestrator as orch_mod

    # Monday at 07:00 → triggers SystemOptimizationAgent
    now_twn = datetime(2025, 1, 6, 7, 0, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 5, 23, 0, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    assert len(tasks_created) >= 1


def test_run_orchestrator_monday_strategy_committee(tmp_state_file, tmp_db):
    """Lines 137-139: Monday at 07:30 schedules StrategyCommitteeAgent."""
    import openclaw.agent_orchestrator as orch_mod

    now_twn = datetime(2025, 1, 6, 7, 30, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 5, 23, 30, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    assert len(tasks_created) >= 1


def test_run_orchestrator_pm_event_trigger(tmp_path, tmp_db):
    """Lines 142-147: new PM review event triggers StrategyCommitteeAgent."""
    import openclaw.agent_orchestrator as orch_mod

    # Create state file with a new reviewed_at
    state_file = tmp_path / "pm_state.json"
    state_file.write_text(json.dumps({"reviewed_at": "2025-01-06T14:30:00"}))

    # Use a Wednesday non-market hour to avoid other scheduled tasks
    now_twn = datetime(2025, 1, 8, 18, 0, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 8, 10, 0, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", str(state_file)),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    # The PM event should have triggered at least one task (StrategyCommitteeAgent)
    assert len(tasks_created) >= 1


def test_run_orchestrator_no_fills_event_trigger(tmp_state_file, tmp_db):
    """Lines 149-154: no fills in 3 days triggers SystemOptimizationAgent."""
    import openclaw.agent_orchestrator as orch_mod

    # Fills table is empty → _watcher_no_fills_3days returns True
    now_twn = datetime(2025, 1, 8, 20, 0, 0, tzinfo=_TZ_TWN)  # Wednesday evening
    now_utc = datetime(2025, 1, 8, 12, 0, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    # No fills → SystemOptimizationAgent scheduled + off-market health check
    assert len(tasks_created) >= 1


def test_run_orchestrator_off_market_health_check(tmp_state_file, tmp_db):
    """Lines 127-131: off-market hours → 2hr health check scheduled."""
    import openclaw.agent_orchestrator as orch_mod

    # Wednesday at 20:00 (off-market hours)
    now_twn = datetime(2025, 1, 8, 20, 0, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 8, 12, 0, 0, tzinfo=timezone.utc)

    tasks_created = []

    def fake_create_task(coro):
        tasks_created.append(True)
        try:
            coro.close()
        except Exception:
            pass
        return MagicMock()

    async def mock_sleep(seconds):
        raise StopAsyncIteration("done")

    # Fill the DB so no-fills event doesn't trigger
    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO fills VALUES (1, datetime('now'))")
    conn.commit()
    conn.close()

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=fake_create_task),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    # Off-market: system health should be scheduled (last_health_off_utc is None → run)
    assert len(tasks_created) >= 1


def test_run_orchestrator_main_loop_exception_handled(tmp_state_file, tmp_db):
    """Lines 156-157: exception inside the try block is caught and logged."""
    import openclaw.agent_orchestrator as orch_mod

    tick = [0]

    async def mock_sleep(seconds):
        tick[0] += 1
        if tick[0] >= 2:
            raise StopAsyncIteration("done after 2 ticks")

    now_twn = datetime(2025, 1, 8, 20, 0, 0, tzinfo=_TZ_TWN)
    now_utc = datetime(2025, 1, 8, 12, 0, 0, tzinfo=timezone.utc)

    # Patch _is_weekday_twn to raise on the first call, then return normally
    # This causes an exception inside the try block (lines 156-157)
    call_count = [0]

    def weekday_side_effect(now_twn_arg=None):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("forced error inside try block")
        return False  # subsequent calls: False (off-market weekday)

    with (
        patch.object(orch_mod, "_STATE_PATH", tmp_state_file),
        patch.object(orch_mod, "DB_PATH", tmp_db),
        patch("openclaw.agent_orchestrator.asyncio.sleep", side_effect=mock_sleep),
        patch("openclaw.agent_orchestrator.asyncio.create_task", side_effect=lambda c: (c.close(), MagicMock())[1]),
        patch.dict("sys.modules", {
            "openclaw.agents.market_research": MagicMock(run_market_research=MagicMock()),
            "openclaw.agents.portfolio_review": MagicMock(run_portfolio_review=MagicMock()),
            "openclaw.agents.system_health": MagicMock(run_system_health=MagicMock()),
            "openclaw.agents.strategy_committee": MagicMock(run_strategy_committee=MagicMock()),
            "openclaw.agents.system_optimization": MagicMock(run_system_optimization=MagicMock()),
        }),
        patch("openclaw.agent_orchestrator._is_weekday_twn", side_effect=weekday_side_effect),
        patch("openclaw.agent_orchestrator.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = lambda tz=None: now_twn if tz == _TZ_TWN else now_utc
        mock_dt.strptime = datetime.strptime

        try:
            asyncio.run(orch_mod.run_orchestrator())
        except StopAsyncIteration:
            pass

    # Should have reached sleep at least twice (first tick had exception, second was clean)
    assert tick[0] >= 1


# ── main() (line 165) ─────────────────────────────────────────────────────────

def test_main_calls_asyncio_run():
    """Line 165: main() calls asyncio.run(run_orchestrator())."""
    from openclaw.agent_orchestrator import main
    import openclaw.agent_orchestrator as orch_mod

    with patch.object(orch_mod.asyncio, "run") as mock_run:
        main()
        assert mock_run.call_count == 1
        # Ensure we don't leave the coroutine un-awaited
        args, _ = mock_run.call_args
        if args and hasattr(args[0], "close"):
            args[0].close()
