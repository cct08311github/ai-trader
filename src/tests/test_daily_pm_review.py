"""Tests for openclaw.daily_pm_review — targeting 100% coverage."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

import openclaw.daily_pm_review as dpr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_file(tmp_path, content: dict) -> str:
    p = tmp_path / "daily_pm_state.json"
    p.write_text(json.dumps(content, ensure_ascii=False))
    return str(p)


def _patch_state_path(monkeypatch, path: str):
    monkeypatch.setattr(dpr, "_STATE_PATH", path)


# ---------------------------------------------------------------------------
# _today()
# ---------------------------------------------------------------------------

def test_today_returns_iso_string():
    result = dpr._today()
    assert result == date.today().isoformat()


# ---------------------------------------------------------------------------
# get_daily_pm_approval()
# ---------------------------------------------------------------------------

def test_get_daily_pm_approval_true_when_today_and_approved(tmp_path, monkeypatch):
    state = {"date": date.today().isoformat(), "approved": True}
    _patch_state_path(monkeypatch, _make_state_file(tmp_path, state))
    assert dpr.get_daily_pm_approval() is True


def test_get_daily_pm_approval_false_when_old_date(tmp_path, monkeypatch):
    state = {"date": "2000-01-01", "approved": True}
    _patch_state_path(monkeypatch, _make_state_file(tmp_path, state))
    assert dpr.get_daily_pm_approval() is False


def test_get_daily_pm_approval_false_when_not_approved(tmp_path, monkeypatch):
    state = {"date": date.today().isoformat(), "approved": False}
    _patch_state_path(monkeypatch, _make_state_file(tmp_path, state))
    assert dpr.get_daily_pm_approval() is False


def test_get_daily_pm_approval_false_on_missing_file(monkeypatch):
    monkeypatch.setattr(dpr, "_STATE_PATH", "/nonexistent/path/state.json")
    assert dpr.get_daily_pm_approval() is False


def test_get_daily_pm_approval_false_on_invalid_json(tmp_path, monkeypatch):
    p = tmp_path / "bad.json"
    p.write_text("NOT JSON")
    monkeypatch.setattr(dpr, "_STATE_PATH", str(p))
    assert dpr.get_daily_pm_approval() is False


# ---------------------------------------------------------------------------
# get_daily_pm_state()
# ---------------------------------------------------------------------------

def test_get_daily_pm_state_returns_full_dict_with_is_today(tmp_path, monkeypatch):
    today = date.today().isoformat()
    state = {"date": today, "approved": True, "confidence": 0.8}
    _patch_state_path(monkeypatch, _make_state_file(tmp_path, state))
    result = dpr.get_daily_pm_state()
    assert result["date"] == today
    assert result["approved"] is True
    assert result["is_today"] is True


def test_get_daily_pm_state_is_today_false_for_old_date(tmp_path, monkeypatch):
    state = {"date": "2000-01-01", "approved": False}
    _patch_state_path(monkeypatch, _make_state_file(tmp_path, state))
    result = dpr.get_daily_pm_state()
    assert result["is_today"] is False


def test_get_daily_pm_state_returns_default_on_error(monkeypatch):
    monkeypatch.setattr(dpr, "_STATE_PATH", "/nonexistent/path/state.json")
    result = dpr.get_daily_pm_state()
    assert result["approved"] is False
    assert result["is_today"] is False
    assert result["date"] is None
    assert result["source"] == "none"
    assert result["reason"] == "尚未執行今日 PM 審核"


# ---------------------------------------------------------------------------
# _save_state()
# ---------------------------------------------------------------------------

def test_save_state_writes_json(tmp_path, monkeypatch):
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = {"date": "2025-01-01", "approved": True}
    dpr._save_state(state)
    with open(path) as f:
        loaded = json.load(f)
    assert loaded["approved"] is True


# ---------------------------------------------------------------------------
# build_daily_context()
# ---------------------------------------------------------------------------

def test_build_daily_context_without_conn():
    ctx = dpr.build_daily_context(conn=None)
    assert ctx["recent_trades"] == []
    assert ctx["recent_pnl"] == []
    assert "date" in ctx


def test_build_daily_context_with_conn_no_trades_table():
    """DB without trades table falls back gracefully."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ctx = dpr.build_daily_context(conn=conn)
    assert ctx["recent_trades"] == []
    assert ctx["recent_pnl"] == []
    conn.close()


def test_build_daily_context_with_trades_data():
    """DB with trades table returns populated context."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE trades (
            symbol TEXT, action TEXT, quantity INTEGER,
            price REAL, pnl REAL, timestamp TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO trades VALUES (?,?,?,?,?,?)",
        ("2330.TW", "buy", 1000, 580.0, 200.0, "2025-01-01T10:00:00"),
    )
    conn.commit()
    ctx = dpr.build_daily_context(conn=conn)
    assert len(ctx["recent_trades"]) == 1
    assert ctx["recent_trades"][0]["symbol"] == "2330.TW"
    assert len(ctx["recent_pnl"]) == 1
    conn.close()


# ---------------------------------------------------------------------------
# run_daily_pm_review()
# ---------------------------------------------------------------------------

def test_run_daily_pm_review_no_llm_call(tmp_path, monkeypatch):
    """When llm_call is None, writes pending state."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = dpr.run_daily_pm_review(context=None, llm_call=None)
    assert state["approved"] is False
    assert state["source"] == "pending"
    assert state["recommended_action"] == "pending_manual"
    # File should be written
    with open(path) as f:
        disk = json.load(f)
    assert disk["source"] == "pending"


def test_run_daily_pm_review_no_context(tmp_path, monkeypatch):
    """When context is None (but llm_call provided), writes pending state."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    def dummy_llm(model, prompt):
        return {}

    state = dpr.run_daily_pm_review(context=None, llm_call=dummy_llm)
    assert state["source"] == "pending"


def test_run_daily_pm_review_bearish_action(tmp_path, monkeypatch):
    """LLM recommends bearish action → approved=False."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "some upside",
        "bear_case": "major risk",
        "neutral_case": "uncertain",
        "consensus_points": ["vol high"],
        "divergence_points": ["trend unclear"],
        "recommended_action": "觀望等待確認",
        "confidence": 0.9,
        "adjudication": "保守操作",
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat(), "recent_trades": [], "recent_pnl": []}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state["approved"] is False
    assert state["source"] == "llm"


def test_run_daily_pm_review_bullish_action(tmp_path, monkeypatch):
    """LLM recommends bullish action → approved=True."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "strong momentum",
        "bear_case": "minor risk",
        "neutral_case": "ok",
        "consensus_points": [],
        "divergence_points": [],
        "recommended_action": "積極買進",
        "confidence": 0.85,
        "adjudication": "加碼進場",
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat(), "recent_trades": [], "recent_pnl": []}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state["approved"] is True
    assert state["source"] == "llm"


def test_run_daily_pm_review_neutral_high_confidence_approved(tmp_path, monkeypatch):
    """Neutral action + confidence >= 0.65 → approved=True."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "ok",
        "bear_case": "ok",
        "neutral_case": "balanced",
        "consensus_points": [],
        "divergence_points": [],
        "recommended_action": "moderate approach",  # no bear/bull keyword
        "confidence": 0.70,
        "adjudication": "balanced",
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat(), "recent_trades": [], "recent_pnl": []}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state["approved"] is True
    assert state["source"] == "llm"


def test_run_daily_pm_review_neutral_low_confidence_rejected(tmp_path, monkeypatch):
    """Neutral action + confidence < 0.65 → approved=False."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "ok",
        "bear_case": "ok",
        "neutral_case": "balanced",
        "consensus_points": [],
        "divergence_points": [],
        "recommended_action": "moderate approach",
        "confidence": 0.50,
        "adjudication": None,
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat(), "recent_trades": [], "recent_pnl": []}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state["approved"] is False
    assert state["source"] == "llm"


def test_run_daily_pm_review_includes_trace_fields(tmp_path, monkeypatch):
    """Verify trace fields (_prompt, _raw_response, etc.) are in returned state."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "x",
        "bear_case": "y",
        "neutral_case": "z",
        "consensus_points": [],
        "divergence_points": [],
        "recommended_action": "buy",
        "confidence": 0.8,
        "_prompt": "test-prompt",
        "_raw_response": "raw",
        "_latency_ms": 123,
        "_model": "gpt-4",
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat()}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state.get("_prompt") == "test-prompt"
    assert state.get("_raw_response") == "raw"
    assert state.get("_latency_ms") == 123
    assert state.get("_model") == "gpt-4"
    # Trace fields must NOT be persisted to disk
    with open(path) as f:
        disk = json.load(f)
    assert "_prompt" not in disk


def test_run_daily_pm_review_adjudication_used_as_reason(tmp_path, monkeypatch):
    """When adjudication is set, it is used as the reason field."""
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)

    llm_response: Dict[str, Any] = {
        "bull_case": "x",
        "bear_case": "y",
        "neutral_case": "z",
        "consensus_points": [],
        "divergence_points": [],
        "recommended_action": "buy",
        "confidence": 0.8,
        "adjudication": "PM 最終裁決",
    }

    def mock_llm(model, prompt):
        return llm_response

    context = {"date": date.today().isoformat()}
    state = dpr.run_daily_pm_review(context=context, llm_call=mock_llm)
    assert state["reason"] == "PM 最終裁決"


# ---------------------------------------------------------------------------
# manual_override()
# ---------------------------------------------------------------------------

def test_manual_override_approved(tmp_path, monkeypatch):
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = dpr.manual_override(approved=True, reason="Human says go")
    assert state["approved"] is True
    assert state["reason"] == "Human says go"
    assert state["source"] == "manual"
    assert state["confidence"] == 1.0
    assert state["recommended_action"] == "manual_override"
    with open(path) as f:
        disk = json.load(f)
    assert disk["approved"] is True


def test_manual_override_rejected(tmp_path, monkeypatch):
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = dpr.manual_override(approved=False, reason="Black swan")
    assert state["approved"] is False
    assert state["reason"] == "Black swan"


def test_manual_override_default_reason_approved(tmp_path, monkeypatch):
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = dpr.manual_override(approved=True)
    assert state["reason"] == "人工授權交易"


def test_manual_override_default_reason_rejected(tmp_path, monkeypatch):
    path = str(tmp_path / "pm_state.json")
    monkeypatch.setattr(dpr, "_STATE_PATH", path)
    state = dpr.manual_override(approved=False)
    assert state["reason"] == "人工封鎖交易"
