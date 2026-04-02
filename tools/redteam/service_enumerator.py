"""service_enumerator.py — Discover running services via pm2, nginx, tailscale."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List

from .finding_scorer import ServiceInfo


def _run(cmd: List[str], timeout: int = 10) -> str:
    """Run a command and return stdout; empty string on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def enumerate_pm2(pm2_bin: str = "pm2") -> List[ServiceInfo]:
    """List services managed by pm2."""
    raw = _run([pm2_bin, "jlist"])
    if not raw:
        return []

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []

    services: List[ServiceInfo] = []
    for item in items:
        svc = ServiceInfo(
            name=item.get("name", "unknown"),
            pid=item.get("pid"),
            status=item.get("pm2_env", {}).get("status", "unknown"),
            pm2_id=item.get("pm_id"),
            extra={"interpreter": item.get("pm2_env", {}).get("exec_interpreter", "")},
        )
        services.append(svc)
    return services


def enumerate_nginx(config_dir: str = "/etc/nginx/sites-enabled/") -> List[ServiceInfo]:
    """Parse nginx configs to find upstream services."""
    config_path = Path(config_dir)
    if not config_path.exists():
        return []

    services: List[ServiceInfo] = []
    for conf_file in config_path.iterdir():
        if conf_file.is_file():
            try:
                content = conf_file.read_text()
            except PermissionError:
                continue
            # Simple heuristic: extract proxy_pass targets
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("proxy_pass"):
                    url = stripped.split()[-1].rstrip(";")
                    svc = ServiceInfo(
                        name=f"nginx-upstream:{conf_file.name}",
                        status="configured",
                        extra={"proxy_pass": url, "config_file": str(conf_file)},
                    )
                    services.append(svc)
    return services


def enumerate_tailscale() -> List[ServiceInfo]:
    """Check tailscale status for exposed services."""
    raw = _run(["tailscale", "status", "--json"])
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    services: List[ServiceInfo] = []
    self_node = data.get("Self", {})
    if self_node:
        svc = ServiceInfo(
            name=f"tailscale:{self_node.get('HostName', 'unknown')}",
            status="online" if data.get("BackendState") == "Running" else "offline",
            extra={
                "tailscale_ips": self_node.get("TailscaleIPs", []),
                "os": self_node.get("OS", ""),
            },
        )
        services.append(svc)
    return services


def enumerate_all(pm2_bin: str = "pm2", nginx_dir: str = "/etc/nginx/sites-enabled/") -> List[ServiceInfo]:
    """Run all enumerators and return combined results."""
    services: List[ServiceInfo] = []
    services.extend(enumerate_pm2(pm2_bin))
    services.extend(enumerate_nginx(nginx_dir))
    services.extend(enumerate_tailscale())
    return services
