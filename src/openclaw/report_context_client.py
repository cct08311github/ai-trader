from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any, Literal


ReportType = Literal["morning", "evening", "weekly"]


def fetch_report_context(
    *,
    base_url: str,
    token: str,
    report_type: ReportType = "morning",
    timeout_sec: float = 30.0,
    verify_tls: bool = True,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"type": report_type})
    url = f"{base_url.rstrip('/')}/api/reports/context?{query}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    context = None if verify_tls else ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout_sec, context=context) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("report context payload must be a JSON object")
    return payload
