"""Tests for eod_analysis.py — stock_screener integration (Task 7)."""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest


def _setup_db(conn: sqlite3.Connection, trade_date: str) -> None:
    """Create required tables and seed minimal data."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT, symbol TEXT, name TEXT, market TEXT,
            open REAL, high REAL, low REAL, close REAL,
            change REAL, volume INTEGER,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT PRIMARY KEY, quantity REAL, avg_price REAL,
            current_price REAL, unrealized_pnl REAL, state TEXT,
            high_water_mark REAL, entry_trading_day TEXT
        );
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            agent TEXT, model TEXT,
            prompt_text TEXT, response_text TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            latency_ms INTEGER, confidence REAL,
            decision_id TEXT, metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS eod_institution_flows (
            trade_date TEXT, symbol TEXT, name TEXT,
            foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_margin_data (
            trade_date TEXT, symbol TEXT,
            margin_balance REAL, short_balance REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS institution_flows (
            trade_date TEXT, symbol TEXT,
            foreign_net REAL, investment_trust_net REAL,
            dealer_net REAL, total_net REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_analysis_reports (
            trade_date TEXT PRIMARY KEY,
            generated_at INTEGER NOT NULL,
            market_summary TEXT NOT NULL,
            technical TEXT NOT NULL,
            strategy TEXT NOT NULL,
            raw_prompt TEXT,
            model_used TEXT NOT NULL DEFAULT 'gemini-2.5-flash'
        );
        CREATE TABLE IF NOT EXISTS system_candidates (
            symbol TEXT NOT NULL, trade_date TEXT NOT NULL,
            label TEXT NOT NULL, score REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'rule_screener',
            reasons TEXT, llm_filtered INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY (symbol, trade_date, label)
        );
    """)
    # Insert at least one eod_prices row so run_eod_analysis doesn't early-return
    conn.execute(
        "INSERT OR IGNORE INTO eod_prices "
        "(trade_date, symbol, name, market, open, high, low, close, change, volume) "
        "VALUES (?, '2330', 'TSMC', 'TWSE', 600.0, 610.0, 595.0, 605.0, 5.0, 100000)",
        (trade_date,),
    )
    conn.commit()


# ── Tests ────────────────────────────────────────────────────────────────────


def test_eod_analysis_calls_screen_candidates(tmp_path, monkeypatch):
    """screen_candidates is called with correct trade_date during EOD analysis."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)  # call_agent_llm handles missing key

    trade_date = "2026-03-05"
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _setup_db(conn, trade_date)

    # Write a watchlist config with manual_watchlist key
    wl_path = tmp_path / "config" / "watchlist.json"
    wl_path.parent.mkdir(parents=True, exist_ok=True)
    wl_path.write_text(json.dumps({"manual_watchlist": ["2330", "2317"]}))

    # Patch _REPO_ROOT so eod_analysis reads our tmp config
    import openclaw.agents.eod_analysis as eod_mod
    monkeypatch.setattr(eod_mod, "_REPO_ROOT", tmp_path)

    # Mock market_data_fetcher
    mock_fetch = MagicMock()
    monkeypatch.setattr(
        "openclaw.market_data_fetcher.run_daily_fetch", mock_fetch, raising=False
    )

    # Track screen_candidates calls
    screen_calls = []

    def fake_screen(conn_, td, *, manual_watchlist, max_candidates=10, llm_refine=True):
        screen_calls.append({
            "trade_date": td,
            "manual_watchlist": manual_watchlist,
            "max_candidates": max_candidates,
        })
        return []

    with patch("openclaw.stock_screener.screen_candidates", fake_screen):
        with patch.object(eod_mod, "_REPO_ROOT", tmp_path):
            result = eod_mod.run_eod_analysis(
                trade_date=trade_date,
                conn=conn,
                db_path=db_path,
            )

    assert result.success is True
    assert len(screen_calls) == 1
    assert screen_calls[0]["trade_date"] == trade_date
    assert screen_calls[0]["manual_watchlist"] == {"2330", "2317"}
    conn.close()


def test_eod_analysis_screener_failure_continues(tmp_path, monkeypatch):
    """If screen_candidates raises, EOD analysis still completes."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    trade_date = "2026-03-05"
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _setup_db(conn, trade_date)

    import openclaw.agents.eod_analysis as eod_mod
    monkeypatch.setattr(eod_mod, "_REPO_ROOT", tmp_path)

    mock_fetch = MagicMock()
    monkeypatch.setattr(
        "openclaw.market_data_fetcher.run_daily_fetch", mock_fetch, raising=False
    )

    def broken_screen(*a, **kw):
        raise RuntimeError("screener exploded")

    with patch("openclaw.stock_screener.screen_candidates", broken_screen):
        result = eod_mod.run_eod_analysis(
            trade_date=trade_date,
            conn=conn,
            db_path=db_path,
        )

    assert result.success is True
    conn.close()


def test_eod_analysis_reads_universe_fallback(tmp_path, monkeypatch):
    """When watchlist has 'universe' key (no manual_watchlist), falls back correctly."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    trade_date = "2026-03-05"
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _setup_db(conn, trade_date)

    # Write config with old-style 'universe' key only
    wl_path = tmp_path / "config" / "watchlist.json"
    wl_path.parent.mkdir(parents=True, exist_ok=True)
    wl_path.write_text(json.dumps({"universe": ["2454", "2881"]}))

    import openclaw.agents.eod_analysis as eod_mod
    monkeypatch.setattr(eod_mod, "_REPO_ROOT", tmp_path)

    mock_fetch = MagicMock()
    monkeypatch.setattr(
        "openclaw.market_data_fetcher.run_daily_fetch", mock_fetch, raising=False
    )

    screen_calls = []

    def fake_screen(conn_, td, *, manual_watchlist, max_candidates=10, llm_refine=True):
        screen_calls.append({"manual_watchlist": manual_watchlist})
        return []

    with patch("openclaw.stock_screener.screen_candidates", fake_screen):
        result = eod_mod.run_eod_analysis(
            trade_date=trade_date,
            conn=conn,
            db_path=db_path,
        )

    assert result.success is True
    assert len(screen_calls) == 1
    # Should fall back to 'universe' key
    assert screen_calls[0]["manual_watchlist"] == {"2454", "2881"}
    conn.close()
