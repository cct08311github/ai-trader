"""Tests for LLM stability improvements (#391).

Covers:
- Default temperature is 0.1
- Temperature is passed to API payload
- Latency warning logged when exceeding threshold
- _extract_json handles various formats
"""
from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from openclaw.llm_minimax import _extract_json


class TestExtractJson:
    def test_plain_json(self):
        assert _extract_json('{"key": "value"}') == {"key": "value"}

    def test_markdown_fenced(self):
        text = '```json\n{"key": "value"}\n```'
        assert _extract_json(text) == {"key": "value"}

    def test_embedded_in_text(self):
        text = 'Here is the result: {"key": "value"} done.'
        assert _extract_json(text) == {"key": "value"}

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            _extract_json("not json at all")

    def test_array_response(self):
        text = '[{"a": 1}, {"a": 2}]'
        # Arrays are valid JSON but _extract_json expects dict
        # It should still work via the regex fallback
        result = _extract_json(text)
        assert isinstance(result, list)


class TestMinimaxCallConfig:
    def test_default_temperature_is_01(self):
        import inspect
        from openclaw.llm_minimax import minimax_call
        sig = inspect.signature(minimax_call)
        assert sig.parameters["temperature"].default == 0.1

    @patch("openclaw.llm_minimax.requests.post")
    @patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"})
    def test_temperature_passed_to_payload(self, mock_post):
        from openclaw.llm_minimax import minimax_call

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"result": "ok"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        minimax_call("test-model", "test prompt", temperature=0.05)

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["temperature"] == 0.05

    @patch("openclaw.llm_minimax.requests.post")
    @patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"})
    def test_latency_warning_logged(self, mock_post, caplog, monkeypatch):
        from openclaw.llm_minimax import minimax_call
        import openclaw.llm_minimax as mod

        old_warn = mod._LATENCY_WARN_MS
        mod._LATENCY_WARN_MS = 1000  # 1 second threshold

        # Simulate 5-second latency via time.time returning increasing values
        _call_count = 0
        _times = [100.0, 105.0]  # 5s apart
        def _fake_time():
            nonlocal _call_count
            idx = min(_call_count, len(_times) - 1)
            _call_count += 1
            return _times[idx]
        monkeypatch.setattr(mod.time, "time", _fake_time)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"result": "ok"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        try:
            with caplog.at_level(logging.WARNING, logger="openclaw.llm_minimax"):
                minimax_call("test-model", "test prompt")
            assert any("LLM call slow" in r.message for r in caplog.records)
        finally:
            mod._LATENCY_WARN_MS = old_warn

    @patch("openclaw.llm_minimax.requests.post")
    @patch.dict("os.environ", {"MINIMAX_API_KEY": "test-key"})
    def test_result_includes_temperature(self, mock_post):
        from openclaw.llm_minimax import minimax_call

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"result": "ok"}'}}],
            "usage": {},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = minimax_call("test-model", "test", temperature=0.1)
        assert result["_temperature"] == 0.1
