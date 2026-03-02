"""Tests for llm_gemini.py — targeting 100% coverage."""
from __future__ import annotations

import json
import types
from unittest.mock import MagicMock, patch

import pytest

from openclaw.llm_gemini import _extract_json, gemini_call


# ── _extract_json ─────────────────────────────────────────────────────────────

def test_extract_json_direct_parse():
    """Direct JSON string parses without any cleanup."""
    result = _extract_json('{"decision": "buy", "confidence": 0.9}')
    assert result["decision"] == "buy"
    assert result["confidence"] == 0.9


def test_extract_json_markdown_code_fence():
    """JSON inside ```json ... ``` is extracted correctly."""
    text = '```json\n{"decision": "sell", "confidence": 0.6}\n```'
    result = _extract_json(text)
    assert result["decision"] == "sell"


def test_extract_json_code_fence_without_lang():
    """JSON inside ``` ... ``` (no 'json' tag) is extracted correctly."""
    text = '```\n{"decision": "hold"}\n```'
    result = _extract_json(text)
    assert result["decision"] == "hold"


def test_extract_json_embedded_in_prose():
    """JSON object embedded in prose text is found by regex."""
    text = 'Here is the result: {"decision": "buy", "reason": "strong momentum"} end'
    result = _extract_json(text)
    assert result["decision"] == "buy"


def test_extract_json_raises_on_unparseable():
    """Non-JSON text raises ValueError."""
    with pytest.raises(ValueError, match="Cannot parse JSON"):
        _extract_json("This is just plain text with no JSON anywhere.")


def test_extract_json_embedded_object_invalid_raises():
    """Lines 48-49: regex finds {…} but its content is invalid JSON → falls through to ValueError."""
    # "{ invalid }" is matched by the regex but fails json.loads
    with pytest.raises(ValueError, match="Cannot parse JSON"):
        _extract_json("The result is { invalid: no quotes } here.")


def test_extract_json_invalid_fence_falls_through_to_embedded():
    """Bad JSON in fence falls through to embedded-object search."""
    text = "```json\nnot valid json\n```\n{\"fallback\": true}"
    result = _extract_json(text)
    assert result["fallback"] is True


# ── gemini_call ───────────────────────────────────────────────────────────────

def _make_google_modules(response_text: str) -> dict:
    """Build proper mock google/google.generativeai modules returning response_text."""
    mock_response = MagicMock()
    mock_response.text = response_text
    mock_model = MagicMock()
    mock_model.generate_content.return_value = mock_response

    # Use a real module type so attribute access works correctly
    genai_mod = types.ModuleType("google.generativeai")
    genai_mod.configure = MagicMock()
    genai_mod.GenerativeModel = MagicMock(return_value=mock_model)

    google_mod = types.ModuleType("google")
    google_mod.generativeai = genai_mod

    return {"google": google_mod, "google.generativeai": genai_mod}


def test_gemini_call_happy_path(monkeypatch):
    """gemini_call returns parsed JSON with metadata attached."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-abc")
    mods = _make_google_modules('{"decision": "buy", "confidence": 0.85}')

    with patch.dict("sys.modules", mods):
        result = gemini_call("gemini-2.0-flash", "Test prompt")

    assert result["decision"] == "buy"
    assert result["confidence"] == 0.85
    assert result["_prompt"] == "Test prompt"
    assert result["_raw_response"] == '{"decision": "buy", "confidence": 0.85}'
    assert result["_model"] == "gemini-2.0-flash"
    assert isinstance(result["_latency_ms"], int)


def test_gemini_call_raises_when_no_api_key(monkeypatch):
    """gemini_call raises RuntimeError if GEMINI_API_KEY is not set.
    The import of google.generativeai happens before the key check, so we still mock it.
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    mods = _make_google_modules("{}")
    with patch.dict("sys.modules", mods):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
            gemini_call("gemini-2.0-flash", "Test prompt")


def test_gemini_call_raises_on_invalid_response(monkeypatch):
    """gemini_call raises ValueError if LLM returns non-JSON text."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-xyz")
    mods = _make_google_modules("This is not JSON at all.")

    with patch.dict("sys.modules", mods):
        with pytest.raises(ValueError, match="Cannot parse JSON"):
            gemini_call("gemini-2.0-flash", "Prompt")


def test_gemini_call_with_markdown_response(monkeypatch):
    """gemini_call handles markdown-wrapped JSON from Gemini."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-md")
    mods = _make_google_modules('```json\n{"decision": "hold"}\n```')

    with patch.dict("sys.modules", mods):
        result = gemini_call("gemini-2.0-flash", "Prompt")

    assert result["decision"] == "hold"
    assert "_latency_ms" in result
