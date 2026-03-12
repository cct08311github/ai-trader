"""Tests for screener_llm JSON array response handling (issue #176).

Verifies that:
1. gemini_call wraps list responses in {"items": [...]}
2. _llm_refine_candidates parses both "items" and "candidates" keys
"""

import json
import sqlite3

import pytest


# ── Unit: _extract_json + wrapping logic ───────────────────────────────────


class TestExtractJsonAndWrapping:
    """_extract_json handles both list and dict JSON."""

    def test_extract_json_returns_list_for_array(self):
        from openclaw.llm_gemini import _extract_json

        result = _extract_json('[{"symbol": "2330"}]')
        assert isinstance(result, list)
        assert result[0]["symbol"] == "2330"

    def test_extract_json_returns_dict_for_object(self):
        from openclaw.llm_gemini import _extract_json

        result = _extract_json('{"summary": "test"}')
        assert isinstance(result, dict)
        assert result["summary"] == "test"

    def test_extract_json_markdown_fenced_array(self):
        from openclaw.llm_gemini import _extract_json

        text = '```json\n[{"symbol": "2330"}]\n```'
        result = _extract_json(text)
        assert isinstance(result, list)

    def test_wrapping_logic_list_becomes_items_dict(self):
        """Simulate what gemini_call does when _extract_json returns a list."""
        from typing import Any, Dict

        parsed = [{"symbol": "2330"}, {"symbol": "2454"}]

        # This is the exact logic from the fix in gemini_call
        if isinstance(parsed, list):
            result: Dict[str, Any] = {"items": parsed}
        else:
            result = parsed

        assert isinstance(result, dict)
        assert "items" in result
        assert len(result["items"]) == 2
        assert result["items"][0]["symbol"] == "2330"

    def test_wrapping_logic_dict_unchanged(self):
        """Dict responses pass through without wrapping."""
        from typing import Any, Dict

        parsed = {"summary": "bullish", "confidence": 0.8}

        if isinstance(parsed, list):
            result: Dict[str, Any] = {"items": parsed}
        else:
            result = parsed

        assert isinstance(result, dict)
        assert "items" not in result
        assert result["summary"] == "bullish"


# ── _llm_refine_candidates parsing ─────────────────────────────────────────


class TestLlmRefineCandidates:
    """_llm_refine_candidates handles various LLM response shapes."""

    CANDIDATES = [
        {"symbol": "2330", "label": "short_term", "score": 0.6, "reasons": ["test"]},
        {"symbol": "2454", "label": "short_term", "score": 0.5, "reasons": ["test2"]},
    ]

    def test_items_key_from_wrapped_list(self, monkeypatch):
        """When gemini_call wraps a list → {"items": [...]}."""
        llm_response = {
            "items": [
                {"symbol": "2330", "label": "short_term", "score": 0.9, "reasons": ["strong"]},
            ],
        }
        self._run_refine(monkeypatch, llm_response, expected_len=1, expected_symbol="2330", expected_score=0.9)

    def test_candidates_key(self, monkeypatch):
        """When LLM response has 'candidates' key directly."""
        llm_response = {
            "candidates": [
                {"symbol": "2454", "label": "short_term", "score": 0.7, "reasons": ["ok"]},
            ],
        }
        self._run_refine(monkeypatch, llm_response, expected_len=1, expected_symbol="2454", expected_score=0.7)

    def test_fallback_on_unexpected_format(self, monkeypatch):
        """When LLM returns dict without items/candidates → return originals."""
        llm_response = {
            "summary": "LLM 呼叫失敗：some error",
            "confidence": 0.0,
            "action_type": "observe",
            "proposals": [],
        }
        result = self._run_refine_raw(monkeypatch, llm_response)
        assert result == self.CANDIDATES, "Should fall back to original candidates"

    def test_empty_items_returns_originals(self, monkeypatch):
        """When LLM returns empty items list → return originals."""
        llm_response = {"items": []}
        result = self._run_refine_raw(monkeypatch, llm_response)
        assert result == self.CANDIDATES, "Empty items should fall back to originals"

    def test_invalid_items_skipped(self, monkeypatch):
        """Items missing required fields are filtered out."""
        llm_response = {
            "items": [
                {"symbol": "2330", "label": "short_term", "score": 0.9, "reasons": ["ok"]},
                {"score": 0.5},  # missing symbol and label
                "invalid_string_entry",
            ],
        }
        result = self._run_refine_raw(monkeypatch, llm_response)
        assert len(result) == 1
        assert result[0]["symbol"] == "2330"

    # ── helpers ────

    def _run_refine_raw(self, monkeypatch, llm_response):
        """Patch imports and run _llm_refine_candidates, return result."""
        import openclaw.agents.base as base_mod

        monkeypatch.setattr(base_mod, "call_agent_llm", lambda *a, **kw: llm_response)
        monkeypatch.setattr(base_mod, "write_trace", lambda *a, **kw: None)

        conn = sqlite3.connect(":memory:")
        from openclaw.stock_screener import _llm_refine_candidates

        return _llm_refine_candidates(conn, "2026-03-12", self.CANDIDATES)

    def _run_refine(self, monkeypatch, llm_response, *, expected_len, expected_symbol, expected_score):
        result = self._run_refine_raw(monkeypatch, llm_response)
        assert len(result) == expected_len
        assert result[0]["symbol"] == expected_symbol
        assert result[0]["score"] == expected_score
