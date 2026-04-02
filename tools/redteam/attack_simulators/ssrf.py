"""ssrf.py — Test internal IP injection (SSRF) with safe payloads."""
from __future__ import annotations

from typing import List
from urllib.parse import quote

import urllib.request
import urllib.error

from ..finding_scorer import Finding

# Internal IP payloads to test for SSRF
_SSRF_PAYLOADS = [
    "http://169.254.169.254/latest/meta-data/",   # AWS metadata
    "http://169.254.169.254/metadata/instance",     # Azure metadata
    "http://metadata.google.internal/",             # GCP metadata
    "http://127.0.0.1:22",                          # local SSH
    "http://0.0.0.0:22",
    "http://[::1]:22",
    "http://localhost:6379",                         # Redis
]

# Endpoints that might accept URL parameters
_URL_PARAMS = ["url", "target", "redirect", "next", "callback", "webhook"]


def scan_ssrf(
    base_url: str,
    max_requests: int = 10,
    timeout: int = 5,
) -> List[Finding]:
    """Test SSRF by injecting internal IPs into URL parameters (localhost only)."""
    if not base_url.startswith(("http://localhost", "http://127.0.0.1")):
        return []

    findings: List[Finding] = []
    request_count = 0

    for param in _URL_PARAMS:
        for payload in _SSRF_PAYLOADS:
            if request_count >= max_requests:
                return findings

            url = f"{base_url}?{param}={quote(payload, safe='')}"
            request_count += 1

            try:
                req = urllib.request.Request(url, method="GET")
                req.add_header("User-Agent", "RedTeam-Scanner/1.0 (security-audit)")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read(4096).decode("utf-8", errors="ignore")
                    status = resp.status

                    # Signs of successful SSRF
                    ssrf_indicators = [
                        "ami-id",           # AWS metadata
                        "instance-id",
                        "meta-data",
                        "SSH-",             # SSH banner
                        "REDIS",            # Redis
                        "+PONG",
                    ]

                    if any(indicator.lower() in body.lower() for indicator in ssrf_indicators):
                        findings.append(Finding(
                            title=f"SSRF via ?{param}=",
                            description=f"Server followed internal URL: {payload}",
                            category="ssrf",
                            evidence=f"URL: {url}, Status: {status}, Body: {body[:100]}",
                            remediation=(
                                "Validate and sanitize URL parameters; "
                                "block requests to internal IPs and cloud metadata endpoints"
                            ),
                        ))
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
                pass

    return findings
