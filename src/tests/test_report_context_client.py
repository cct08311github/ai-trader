from __future__ import annotations

import io
import json
import urllib.request
from unittest.mock import patch

import pytest

from openclaw.report_context_client import fetch_report_context


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_fetch_report_context_sends_auth_and_type():
    captured = {}

    def fake_urlopen(req, timeout=0, context=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        captured["timeout"] = timeout
        captured["context"] = context
        return _FakeResponse({"status": "ok", "report_type": "weekly"})

    with patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        payload = fetch_report_context(
            base_url="https://127.0.0.1:8080/",
            token="abc123",
            report_type="weekly",
            timeout_sec=12,
            verify_tls=False,
        )

    assert payload["status"] == "ok"
    assert payload["report_type"] == "weekly"
    assert captured["url"] == "https://127.0.0.1:8080/api/reports/context?type=weekly"
    assert captured["auth"] == "Bearer abc123"
    assert captured["timeout"] == 12
    assert captured["context"] is not None


def test_fetch_report_context_rejects_non_object_payload():
    with patch.object(urllib.request, "urlopen", return_value=_FakeResponse(["bad"])):
        with pytest.raises(ValueError):
            fetch_report_context(
                base_url="https://127.0.0.1:8080",
                token="abc123",
            )
