"""auth_bypass.py — Test no-token / expired-token / empty-bearer scenarios."""
from __future__ import annotations

import json
from typing import List

import urllib.request
import urllib.error
from urllib.parse import urlparse

from ..finding_scorer import Finding


def _is_localhost(url: str) -> bool:
    """Check if URL targets localhost using proper URL parsing."""
    parsed = urlparse(url)
    return parsed.hostname in ("localhost", "127.0.0.1", "::1")

# Endpoints commonly requiring auth
_AUTH_ENDPOINTS = [
    "/api/portfolio",
    "/api/trades",
    "/api/config",
    "/api/agents",
    "/api/admin",
    "/api/user/profile",
]

_BYPASS_CASES = [
    ("no-token", {}),
    ("empty-bearer", {"Authorization": "Bearer "}),
    ("null-bearer", {"Authorization": "Bearer null"}),
    ("expired-token", {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjB9.invalid"}),
]


def scan_auth_bypass(
    base_url: str,
    max_requests: int = 10,
    timeout: int = 5,
) -> List[Finding]:
    """Test authentication bypass on API endpoints (localhost only)."""
    if not _is_localhost(base_url):
        return []

    findings: List[Finding] = []
    request_count = 0

    for endpoint in _AUTH_ENDPOINTS:
        for case_name, headers in _BYPASS_CASES:
            if request_count >= max_requests:
                return findings

            url = f"{base_url}{endpoint}"
            request_count += 1

            try:
                req = urllib.request.Request(url, method="GET")
                req.add_header("User-Agent", "RedTeam-Scanner/1.0 (security-audit)")
                for k, v in headers.items():
                    req.add_header(k, v)

                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read(4096).decode("utf-8", errors="ignore")
                    status = resp.status

                    # 2xx without auth = finding
                    if 200 <= status < 300:
                        # Check if we actually got data (not a generic "ok" page)
                        is_data = False
                        try:
                            parsed = json.loads(body)
                            is_data = bool(parsed) and not parsed.get("error")
                        except (json.JSONDecodeError, AttributeError):
                            is_data = len(body) > 50

                        if is_data:
                            # Summarise response structure, not actual values (avoid leaking sensitive data)
                            try:
                                parsed_summary = json.loads(body)
                                body_summary = f"JSON keys: {list(parsed_summary.keys())[:5]}"
                            except (json.JSONDecodeError, AttributeError):
                                body_summary = f"text, {len(body)} bytes"

                            findings.append(Finding(
                                title=f"Auth bypass: {endpoint} ({case_name})",
                                description=f"Endpoint returned data without valid authentication",
                                category="auth-bypass",
                                evidence=f"URL: {url}, Case: {case_name}, Status: {status}, Response: {body_summary}",
                                remediation="Enforce authentication middleware on all API endpoints",
                            ))
            except urllib.error.HTTPError as e:
                # 401/403 is expected — endpoint is properly protected
                if e.code not in (401, 403):
                    pass
            except (urllib.error.URLError, OSError, TimeoutError):
                pass

    return findings
