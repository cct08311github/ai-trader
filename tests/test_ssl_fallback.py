"""Tests for EOD ingest SSL fallback behaviour (Issue #270).

Verifies that _fetch_text:
1. Tries TLS-verified connection first (certifi CA bundle).
2. Falls back to CERT_NONE on ssl.SSLError and emits a security warning.
3. Does not fall back on non-SSL errors (e.g. URLError, network timeout).
"""
from __future__ import annotations

import ssl
import urllib.error
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(body: bytes = b"ok") -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMakeSslCtx:
    def test_verify_true_returns_cert_required(self):
        from openclaw.eod_ingest import _make_ssl_ctx
        ctx = _make_ssl_ctx(verify=True)
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_verify_false_returns_cert_none(self):
        from openclaw.eod_ingest import _make_ssl_ctx
        ctx = _make_ssl_ctx(verify=False)
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_verify_false_disables_hostname_check(self):
        from openclaw.eod_ingest import _make_ssl_ctx
        ctx = _make_ssl_ctx(verify=False)
        assert ctx.check_hostname is False


class TestFetchTextSslFallback:
    """_fetch_text should attempt verified SSL first, fall back on SSLError."""

    def test_success_on_first_attempt_no_fallback(self):
        """Happy path: verified SSL works — urlopen called once."""
        from openclaw.eod_ingest import _fetch_text

        mock_resp = _make_mock_response(b"hello world")
        with patch("openclaw.eod_ingest.urlopen", return_value=mock_resp) as mock_urlopen:
            result = _fetch_text("https://example.com/data")

        assert result == "hello world"
        assert mock_urlopen.call_count == 1
        # First call must use a verified context (CERT_REQUIRED)
        ctx_used = mock_urlopen.call_args_list[0][1]["context"]
        assert ctx_used.verify_mode == ssl.CERT_REQUIRED

    def test_ssl_error_triggers_fallback(self):
        """On SSLError, second attempt uses CERT_NONE."""
        from openclaw.eod_ingest import _fetch_text

        ssl_error = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
        mock_resp = _make_mock_response(b"twse data")

        call_count = [0]

        def side_effect(req, context, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ssl_error
            return mock_resp

        with patch("openclaw.eod_ingest.urlopen", side_effect=side_effect) as mock_urlopen:
            result = _fetch_text("https://openapi.twse.com.tw/v1/test")

        assert result == "twse data"
        assert mock_urlopen.call_count == 2
        # Second call must use CERT_NONE fallback
        ctx_fallback = mock_urlopen.call_args_list[1][1]["context"]
        assert ctx_fallback.verify_mode == ssl.CERT_NONE

    def test_ssl_error_fallback_emits_security_warning(self, caplog):
        """Security warning must be logged when falling back to CERT_NONE."""
        import logging
        from openclaw.eod_ingest import _fetch_text

        ssl_error = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
        mock_resp = _make_mock_response(b"data")

        call_count = [0]

        def side_effect(req, context, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ssl_error
            return mock_resp

        with patch("openclaw.eod_ingest.urlopen", side_effect=side_effect):
            with caplog.at_level(logging.WARNING, logger="openclaw.eod_ingest"):
                _fetch_text("https://openapi.twse.com.tw/v1/test")

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("SECURITY" in m or "CERT_NONE" in m or "SSL" in m for m in warning_messages), (
            f"Expected a security warning in logs, got: {warning_messages}"
        )

    def test_non_ssl_error_not_caught(self):
        """Non-SSL errors (e.g. URLError) propagate without fallback."""
        from openclaw.eod_ingest import _fetch_text

        network_err = urllib.error.URLError("Connection refused")

        with patch("openclaw.eod_ingest.urlopen", side_effect=network_err):
            with pytest.raises(urllib.error.URLError):
                _fetch_text("https://openapi.twse.com.tw/v1/test")

    def test_encoding_applied_on_fallback(self):
        """Encoding parameter is respected even on the fallback path."""
        from openclaw.eod_ingest import _fetch_text

        payload = "代號,名稱\n2330,台積電".encode("cp950")
        ssl_error = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
        mock_resp = _make_mock_response(payload)

        call_count = [0]

        def side_effect(req, context, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ssl_error
            return mock_resp

        with patch("openclaw.eod_ingest.urlopen", side_effect=side_effect):
            result = _fetch_text("https://www.tpex.org.tw/test", encoding="cp950")

        assert "台積電" in result
        assert "2330" in result
