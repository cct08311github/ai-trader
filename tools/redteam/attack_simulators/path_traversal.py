"""path_traversal.py — Test directory traversal with safe payloads."""
from __future__ import annotations

from typing import List
from urllib.parse import quote

import urllib.request
import urllib.error

from ..finding_scorer import Finding

# Safe payloads — only attempt to read known-safe files
_TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..%2F..%2F..%2Fetc%2Fpasswd",
    "....//....//....//etc/passwd",
    "%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "..\\..\\..\\etc\\passwd",
]

# Common endpoints that might accept file parameters
_FILE_PARAMS = ["file", "path", "page", "template", "include", "doc"]


def scan_path_traversal(
    base_url: str,
    max_requests: int = 10,
    timeout: int = 5,
) -> List[Finding]:
    """Send path traversal payloads to a target (localhost only)."""
    if not base_url.startswith(("http://localhost", "http://127.0.0.1")):
        return []

    findings: List[Finding] = []
    request_count = 0

    for param in _FILE_PARAMS:
        for payload in _TRAVERSAL_PAYLOADS:
            if request_count >= max_requests:
                return findings

            url = f"{base_url}?{param}={quote(payload, safe='')}"
            request_count += 1

            try:
                req = urllib.request.Request(url, method="GET")
                req.add_header("User-Agent", "RedTeam-Scanner/1.0 (security-audit)")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read(4096).decode("utf-8", errors="ignore")
                    if "root:" in body or "/bin/bash" in body or "/bin/sh" in body:
                        findings.append(Finding(
                            title=f"Path traversal via ?{param}=",
                            description=f"Server returned sensitive file content for payload: {payload}",
                            category="path-traversal",
                            evidence=f"URL: {url}, Status: {resp.status}, Body snippet: {body[:100]}",
                            remediation="Sanitize file path inputs; use allowlist for accessible files",
                        ))
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
                pass

    return findings
