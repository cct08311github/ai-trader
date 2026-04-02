"""Tests for attack simulator modules."""
from unittest.mock import patch, MagicMock
import urllib.error

import pytest

from tools.redteam.attack_simulators.path_traversal import scan_path_traversal
from tools.redteam.attack_simulators.auth_bypass import scan_auth_bypass
from tools.redteam.attack_simulators.ssrf import scan_ssrf


class TestPathTraversal:
    def test_rejects_non_localhost(self):
        findings = scan_path_traversal("http://example.com")
        assert findings == []

    @patch("tools.redteam.attack_simulators.path_traversal.urllib.request.urlopen")
    def test_detects_traversal(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"root:x:0:0:root:/root:/bin/bash\n"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        findings = scan_path_traversal("http://localhost:3000", max_requests=2)
        assert len(findings) >= 1
        assert findings[0].category == "path-traversal"

    @patch("tools.redteam.attack_simulators.path_traversal.urllib.request.urlopen")
    def test_no_finding_on_safe_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"<html>Not Found</html>"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        findings = scan_path_traversal("http://localhost:3000", max_requests=2)
        assert findings == []

    @patch("tools.redteam.attack_simulators.path_traversal.urllib.request.urlopen")
    def test_respects_max_requests(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        scan_path_traversal("http://localhost:3000", max_requests=3)
        assert mock_urlopen.call_count <= 3


class TestAuthBypass:
    def test_rejects_non_localhost(self):
        findings = scan_auth_bypass("http://example.com")
        assert findings == []

    @patch("tools.redteam.attack_simulators.auth_bypass.urllib.request.urlopen")
    def test_detects_bypass(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"data": [{"id": 1}]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        findings = scan_auth_bypass("http://localhost:8000", max_requests=2)
        assert len(findings) >= 1
        assert findings[0].category == "auth-bypass"

    @patch("tools.redteam.attack_simulators.auth_bypass.urllib.request.urlopen")
    def test_no_finding_on_401(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://localhost:8000/api/portfolio",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

        findings = scan_auth_bypass("http://localhost:8000", max_requests=2)
        assert findings == []


class TestSsrf:
    def test_rejects_non_localhost(self):
        findings = scan_ssrf("http://example.com")
        assert findings == []

    @patch("tools.redteam.attack_simulators.ssrf.urllib.request.urlopen")
    def test_detects_ssrf(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"ami-id": "ami-12345", "instance-id": "i-abc"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        findings = scan_ssrf("http://localhost:3000", max_requests=2)
        assert len(findings) >= 1
        assert findings[0].category == "ssrf"

    @patch("tools.redteam.attack_simulators.ssrf.urllib.request.urlopen")
    def test_respects_max_requests(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("refused")
        scan_ssrf("http://localhost:3000", max_requests=5)
        assert mock_urlopen.call_count <= 5
