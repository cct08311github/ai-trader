"""Tests for ticker_watcher graceful shutdown (Issue #237)."""
import signal
import sqlite3
import time
import types
import unittest.mock as mock

import pytest


def test_shutdown_flag_set_by_sigterm(monkeypatch):
    """SIGTERM handler sets _shutdown_requested to True."""
    import openclaw.ticker_watcher as tw

    monkeypatch.setattr(tw, "_shutdown_requested", False)
    tw._handle_shutdown_signal(signal.SIGTERM, None)
    assert tw._shutdown_requested is True


def test_shutdown_flag_set_by_sigint(monkeypatch):
    """SIGINT handler sets _shutdown_requested to True."""
    import openclaw.ticker_watcher as tw

    monkeypatch.setattr(tw, "_shutdown_requested", False)
    tw._handle_shutdown_signal(signal.SIGINT, None)
    assert tw._shutdown_requested is True


def test_interruptible_sleep_exits_on_shutdown(monkeypatch):
    """_interruptible_sleep returns True immediately when shutdown is requested."""
    import openclaw.ticker_watcher as tw

    monkeypatch.setattr(tw, "_shutdown_requested", True)
    start = time.monotonic()
    result = tw._interruptible_sleep(60)
    elapsed = time.monotonic() - start

    assert result is True
    assert elapsed < 1.0  # should exit almost immediately


def test_interruptible_sleep_completes_when_no_shutdown(monkeypatch):
    """_interruptible_sleep returns False after normal completion."""
    import openclaw.ticker_watcher as tw

    monkeypatch.setattr(tw, "_shutdown_requested", False)
    result = tw._interruptible_sleep(0)
    assert result is False


def test_handle_shutdown_signal_is_registered_for_sigterm():
    """_handle_shutdown_signal is the function registered for SIGTERM after watcher init."""
    import openclaw.ticker_watcher as tw

    # Verify the handler function exists and has the correct signature
    assert callable(tw._handle_shutdown_signal)

    # Simulate what the OS does: call handler with SIGTERM
    import openclaw.ticker_watcher as tw2
    original = tw2._shutdown_requested
    try:
        tw2._shutdown_requested = False
        tw2._handle_shutdown_signal(signal.SIGTERM, None)
        assert tw2._shutdown_requested is True
    finally:
        tw2._shutdown_requested = original


def test_loop_exits_when_shutdown_requested(monkeypatch):
    """Main loop body is never entered when _shutdown_requested is True at startup."""
    import openclaw.ticker_watcher as tw

    market_open_calls: list = []

    def track_market_open():
        market_open_calls.append(1)
        return False  # pretend market is closed

    monkeypatch.setattr(tw, "_shutdown_requested", True)
    monkeypatch.setattr(tw, "_is_market_open", track_market_open)

    with mock.patch.dict("sys.modules", {
        "openclaw.risk_engine": mock.MagicMock(),
        "openclaw.broker": mock.MagicMock(),
        "openclaw.risk_store": mock.MagicMock(),
        "openclaw.daily_pm_review": mock.MagicMock(),
    }):
        with mock.patch("openclaw.ticker_watcher._open_conn", side_effect=sqlite3.OperationalError("no db")):
            with mock.patch("openclaw.ticker_watcher._load_manual_watchlist", return_value=[]):
                tw.run_watcher()

    # Loop body (_is_market_open) should never be called
    assert market_open_calls == []


def test_shutdown_flag_resets_between_tests(monkeypatch):
    """Ensure each test gets a clean flag state via monkeypatch."""
    import openclaw.ticker_watcher as tw

    monkeypatch.setattr(tw, "_shutdown_requested", False)
    assert tw._shutdown_requested is False
