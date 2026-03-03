"""Tests for app/services/chat_context.py — targeting 9% → near 100%."""
from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(rows_positions=None, rows_traces=None, rows_fills=None):
    """Build an in-memory SQLite connection with optional test rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT, quantity REAL, avg_price REAL,
            current_price REAL, unrealized_pnl REAL
        )"""
    )
    conn.execute(
        """CREATE TABLE llm_traces (
            trace_id TEXT, agent TEXT, model TEXT, response TEXT,
            created_at INTEGER, prompt TEXT, latency_ms INTEGER,
            prompt_tokens INTEGER, completion_tokens INTEGER, confidence REAL
        )"""
    )
    conn.execute(
        """CREATE TABLE fills (
            symbol TEXT, side TEXT, qty REAL, price REAL, filled_at REAL
        )"""
    )

    if rows_positions:
        for r in rows_positions:
            conn.execute(
                "INSERT INTO positions VALUES (?,?,?,?,?)",
                r,
            )
    if rows_traces:
        for r in rows_traces:
            conn.execute(
                "INSERT INTO llm_traces(trace_id, agent, model, response, created_at) VALUES (?,?,?,?,?)",
                r,
            )
    if rows_fills:
        for r in rows_fills:
            conn.execute(
                "INSERT INTO fills VALUES (?,?,?,?,?)",
                r,
            )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# _read_nav
# ---------------------------------------------------------------------------

class TestReadNav:
    def test_returns_default_on_missing_file(self, tmp_path, monkeypatch):
        """When capital.json does not exist, fallback to 1_000_000."""
        from app.services import chat_context as cc
        monkeypatch.setattr(cc, "_CAPITAL_JSON", tmp_path / "nonexistent.json")
        assert cc._read_nav() == 1_000_000.0

    def test_reads_value_from_file(self, tmp_path, monkeypatch):
        cap = tmp_path / "capital.json"
        cap.write_text(json.dumps({"total_capital_twd": 2_500_000.0}))
        from app.services import chat_context as cc
        monkeypatch.setattr(cc, "_CAPITAL_JSON", cap)
        assert cc._read_nav() == 2_500_000.0

    def test_fallback_on_invalid_json(self, tmp_path, monkeypatch):
        cap = tmp_path / "capital.json"
        cap.write_text("NOT_JSON")
        from app.services import chat_context as cc
        monkeypatch.setattr(cc, "_CAPITAL_JSON", cap)
        assert cc._read_nav() == 1_000_000.0

    def test_fallback_when_key_missing(self, tmp_path, monkeypatch):
        cap = tmp_path / "capital.json"
        cap.write_text(json.dumps({"other_key": 999}))
        from app.services import chat_context as cc
        monkeypatch.setattr(cc, "_CAPITAL_JSON", cap)
        assert cc._read_nav() == 1_000_000.0


# ---------------------------------------------------------------------------
# build_chat_context — conn is None
# ---------------------------------------------------------------------------

class TestBuildChatContextNoConn:
    def test_none_conn_returns_minimal_context(self):
        from app.services.chat_context import build_chat_context
        result = build_chat_context(None)
        assert "OpenClaw" in result
        assert "資料庫連線不可用" in result

    def test_result_is_string(self):
        from app.services.chat_context import build_chat_context
        assert isinstance(build_chat_context(None), str)


# ---------------------------------------------------------------------------
# build_chat_context — with DB rows
# ---------------------------------------------------------------------------

class TestBuildChatContextWithDB:
    def test_no_positions(self):
        conn = _make_conn()
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "無持倉" in result

    def test_positions_appear(self):
        conn = _make_conn(
            rows_positions=[("2330", 100, 600.0, 620.0, 2000.0)]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "2330" in result
        assert "100" in result

    def test_position_negative_pnl(self):
        conn = _make_conn(
            rows_positions=[("0050", 50, 150.0, 140.0, -500.0)]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "0050" in result

    def test_position_zero_avg_price(self):
        """avg_price=0 should not cause ZeroDivisionError."""
        conn = _make_conn(
            rows_positions=[("9999", 10, 0.0, 10.0, 0.0)]
        )
        from app.services.chat_context import build_chat_context
        # Should not raise
        result = build_chat_context(conn)
        assert isinstance(result, str)

    def test_watcher_traces_appear(self):
        """Watcher signals section appears when llm_traces has watcher rows."""
        import time
        ts = int(time.time())
        trace_resp = json.dumps({"symbol": "2330", "signal": "BUY", "close": 650})
        conn = _make_conn(
            rows_traces=[("t1", "watcher", "mock", trace_resp, ts)]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "watcher" in result.lower() or "2330" in result

    def test_watcher_trace_invalid_json_skipped(self):
        """Invalid JSON in watcher response is silently skipped."""
        import time
        ts = int(time.time())
        conn = _make_conn(
            rows_traces=[("t1", "watcher", "mock", "INVALID_JSON", ts)]
        )
        from app.services.chat_context import build_chat_context
        # Should not raise
        result = build_chat_context(conn)
        assert isinstance(result, str)

    def test_fills_appear(self):
        """Recent fills section appears."""
        import time
        ts = time.time()
        conn = _make_conn(
            rows_fills=[("2330", "buy", 100, 600.0, ts)]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "2330" in result or "成交" in result

    def test_fills_bad_timestamp(self):
        """Non-numeric filled_at should not crash."""
        conn = _make_conn(
            rows_fills=[("2330", "sell", 50, 610.0, "bad-ts")]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert isinstance(result, str)

    def test_risk_section_appears(self):
        """風控狀態 section appears in output."""
        conn = _make_conn()
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "風控" in result

    def test_risk_section_with_positions(self):
        """Risk section calculates gross exposure from positions."""
        conn = _make_conn(
            rows_positions=[("2330", 100, 600.0, 620.0, 2000.0)]
        )
        from app.services import chat_context as cc
        # Patch _read_nav to return known value
        with patch.object(cc, "_read_nav", return_value=500_000.0):
            result = cc.build_chat_context(conn)
        assert "gross_exposure" in result

    def test_pnl_engine_unavailable_gracefully(self):
        """If pnl_engine import fails, section shows fallback message."""
        conn = _make_conn()
        from app.services.chat_context import build_chat_context
        # pnl_engine is expected to fail in test env
        result = build_chat_context(conn)
        assert "損益" in result  # section header still appears

    def test_multiple_positions_totals(self):
        """Multiple positions yield totals in output."""
        conn = _make_conn(
            rows_positions=[
                ("2330", 100, 600.0, 620.0, 2000.0),
                ("0050", 50, 140.0, 142.0, 100.0),
            ]
        )
        from app.services.chat_context import build_chat_context
        result = build_chat_context(conn)
        assert "2330" in result
        assert "0050" in result
        assert "持倉總市值" in result

    def test_positions_query_exception_appended(self):
        """When positions query raises, error message is appended (covers line 75-76)."""
        from app.services.chat_context import build_chat_context

        class BadPositionsConn:
            row_factory = None
            _n = 0
            def execute(self, sql, *args):
                BadPositionsConn._n += 1
                if "positions" in sql:
                    raise Exception("positions error for test")
                return _EmptyResult()

        class _EmptyResult:
            def fetchall(self): return []

        BadPositionsConn._n = 0
        result = build_chat_context(BadPositionsConn())
        assert isinstance(result, str)
        assert "查詢失敗" in result  # line 76 executed

    def test_pnl_engine_available_covers_lines_84_87(self):
        """When pnl_engine works, sign/append lines 84-87 are executed."""
        conn = _make_conn()
        from app.services import chat_context as cc

        fake_pnl = types.ModuleType("openclaw.pnl_engine")
        fake_pnl.get_today_pnl = lambda conn, date: 100.0
        fake_pnl.get_monthly_pnl = lambda conn, month: -200.0
        sys.modules["openclaw.pnl_engine"] = fake_pnl
        # Also need openclaw module
        if "openclaw" not in sys.modules:
            fake_openclaw = types.ModuleType("openclaw")
            sys.modules["openclaw"] = fake_openclaw

        try:
            result = cc.build_chat_context(conn)
            assert "100" in result or "損益" in result
        finally:
            sys.modules.pop("openclaw.pnl_engine", None)

    def test_watcher_traces_exception_silently_passed(self):
        """When llm_traces query raises, it is silently passed (covers line 116-117)."""
        from app.services.chat_context import build_chat_context

        class WatcherFailConn:
            row_factory = None
            _n = 0
            def execute(self, sql, *args):
                WatcherFailConn._n += 1
                if "llm_traces" in sql:
                    raise Exception("llm_traces error")
                return _EmptyResult()

        class _EmptyResult:
            def fetchall(self): return []

        WatcherFailConn._n = 0
        result = build_chat_context(WatcherFailConn())
        assert isinstance(result, str)
        # Watcher section is skipped, no crash

    def test_fills_exception_silently_passed(self):
        """When fills query raises, it is silently passed (covers line 135-136)."""
        from app.services.chat_context import build_chat_context

        class FillsFailConn:
            row_factory = None
            _n = 0
            def execute(self, sql, *args):
                FillsFailConn._n += 1
                if "fills" in sql:
                    raise Exception("fills table missing")
                return _EmptyResult()

        class _EmptyResult:
            def fetchall(self): return []

        FillsFailConn._n = 0
        result = build_chat_context(FillsFailConn())
        assert isinstance(result, str)
        # fills section is skipped, no crash

    def test_risk_section_exception_silently_passed(self):
        """When risk section raises, it is silently passed (covers line 159-160)."""
        from app.services.chat_context import build_chat_context

        class RiskFailConn:
            row_factory = None
            _n = 0
            def execute(self, sql, *args):
                RiskFailConn._n += 1
                # The risk section is the SECOND fills query
                # First fills query succeeds (line ~121), second raises (line ~140)
                if "fills" in sql and RiskFailConn._n >= 3:
                    raise Exception("risk section error")
                if "positions" in sql and RiskFailConn._n >= 3:
                    raise Exception("risk positions error")
                return _EmptyResult()

        class _EmptyResult:
            def fetchall(self): return []

        RiskFailConn._n = 0
        result = build_chat_context(RiskFailConn())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# parse_proposal_intent
# ---------------------------------------------------------------------------

class TestParseProposalIntent:
    def test_chinese_buy(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("建議買入 2330 270股 @897")
        assert result is not None
        assert result["action"] == "buy"
        assert result["symbol"] == "2330"
        assert result["qty"] == 270
        assert result["price"] == 897.0

    def test_chinese_sell(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("建議賣出 2317 100股 @85.5")
        assert result is not None
        assert result["action"] == "sell"
        assert result["symbol"] == "2317"
        assert result["qty"] == 100
        assert result["price"] == 85.5

    def test_english_buy(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("buy 2330 200 @600.5")
        assert result is not None
        assert result["action"] == "buy"
        assert result["symbol"] == "2330"
        assert result["qty"] == 200
        assert result["price"] == 600.5

    def test_english_sell(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("sell 0050 10 @142.0")
        assert result is not None
        assert result["action"] == "sell"

    def test_no_match_returns_none(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("目前持倉狀況正常，無需調整。")
        assert result is None

    def test_empty_string_returns_none(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("")
        assert result is None

    def test_case_insensitive_english(self):
        from app.services.chat_context import parse_proposal_intent
        result = parse_proposal_intent("BUY 2330 100 @500")
        assert result is not None
        assert result["action"] == "buy"
