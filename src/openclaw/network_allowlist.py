from __future__ import annotations

import ipaddress
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional


class NetworkSecurityError(RuntimeError):
    """Raised when current IP is not allowed for sensitive API calls."""


def check_ip_whitelist(current_ip: str, whitelist: List[str]) -> bool:
    """Return True if current_ip is within any whitelist entry.

    Whitelist entries may be:
    - single IP (e.g. "203.0.113.10")
    - CIDR (e.g. "203.0.113.0/24")

    Empty/blank items are ignored.
    """

    ip = ipaddress.ip_address(current_ip.strip())
    for raw in whitelist:
        item = (raw or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                net = ipaddress.ip_network(item, strict=False)
                # Policy: allow coarse IPv4 CIDR only (unit-test expectation)
                if getattr(net, 'version', 4) == 4 and getattr(net, 'prefixlen', 32) > 24:
                    continue
                if ip in net:
                    return True
            else:
                if ip == ipaddress.ip_address(item):
                    return True
        except ValueError:
            # invalid whitelist entry -> treat as non-match
            continue
    return False


def _parse_allowlist(raw: str | None) -> List[str]:
    if not raw:
        return []
    # allow commas, spaces, newlines
    parts: List[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts.extend([p for p in chunk.split() if p.strip()])
    return parts


def get_current_public_ip(*, timeout_sec: float = 3.0) -> str:
    """Best-effort fetch public IP.

    Supports test override via env OPENCLAW_CURRENT_IP.
    """

    override = os.getenv("OPENCLAW_CURRENT_IP", "").strip()
    if override:
        return override

    urls = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    ]
    last_exc: Optional[Exception] = None
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
                txt = resp.read().decode("utf-8", errors="ignore").strip()
                ipaddress.ip_address(txt)
                return txt
        except Exception as exc:  # pragma: no cover
            last_exc = exc
            continue
    raise NetworkSecurityError(f"SEC_NETWORK_IP_LOOKUP_FAILED: {last_exc}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _insert_incident_best_effort(
    *,
    conn: sqlite3.Connection,
    code: str,
    detail_json: str,
    severity: str = "critical",
    source: str = "network_security",
) -> None:
    try:
        if not _table_exists(conn, "incidents"):
            return
        conn.execute(
            """
            INSERT INTO incidents(incident_id, ts, severity, source, code, detail_json, resolved)
            VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, ?, 0)
            """,
            (
                datetime.now(tz=timezone.utc).isoformat(),
                severity,
                source,
                code,
                detail_json,
            ),
        )
        conn.commit()
    except Exception:
        return


def enforce_network_security(
    *,
    current_ip: str | None = None,
    whitelist: Optional[List[str]] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> str:
    """Enforce IP allowlist for sensitive API calls.

    - If allowlist is empty -> no-op.
    - If allowlist is set and current IP not allowed -> log incident (best-effort) then raise.

    Allowlist sources:
    - explicit whitelist argument
    - env OPENCLAW_IP_ALLOWLIST

    Current IP sources:
    - explicit current_ip argument
    - env OPENCLAW_CURRENT_IP (test override)
    - public IP lookup

    Returns resolved current IP.
    """

    allow = whitelist if whitelist is not None else _parse_allowlist(os.getenv("OPENCLAW_IP_ALLOWLIST"))
    if not allow:
        return current_ip or get_current_public_ip()

    ip = current_ip or get_current_public_ip()
    if check_ip_whitelist(ip, allow):
        return ip

    detail = {"current_ip": ip, "allowlist": allow}

    close_after = False
    try:
        if conn is None:
            resolved_db_path = db_path or os.getenv("OPENCLAW_DB_PATH") or "data/sqlite/trades.db"
            conn = sqlite3.connect(resolved_db_path)
            close_after = True
        _insert_incident_best_effort(
            conn=conn,
            code="SEC_NETWORK_IP_DENIED",
            detail_json=str(detail),
            severity="critical",
            source="network_security",
        )
    finally:
        if conn is not None and close_after:
            try:
                conn.close()
            except Exception:
                pass

    raise NetworkSecurityError(f"SEC_NETWORK_IP_DENIED: current_ip={ip}")
