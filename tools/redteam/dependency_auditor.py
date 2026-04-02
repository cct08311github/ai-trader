"""dependency_auditor.py — Run npm audit / pip audit per repo, unified Finding format."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List

from .finding_scorer import Finding


def _run_json(cmd: List[str], cwd: str, timeout: int = 60) -> dict:
    """Run a command expecting JSON output; return parsed dict or empty."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        # npm audit returns non-zero when vulns found — still valid JSON
        output = result.stdout.strip()
        if output:
            return json.loads(output)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return {}


def audit_npm(repo_path: str) -> List[Finding]:
    """Run `npm audit --json` and convert to Finding list."""
    pkg_json = Path(repo_path) / "package.json"
    if not pkg_json.exists():
        return []

    data = _run_json(["npm", "audit", "--json"], cwd=repo_path)
    if not data:
        return []

    findings: List[Finding] = []
    vulnerabilities = data.get("vulnerabilities", {})
    for pkg_name, vuln_info in vulnerabilities.items():
        severity = vuln_info.get("severity", "info")
        category = f"dependency-vuln-{severity}"
        finding = Finding(
            title=f"npm: {pkg_name} ({severity})",
            description=vuln_info.get("title", f"Vulnerability in {pkg_name}"),
            category=category,
            source_file="package.json",
            evidence=f"Range: {vuln_info.get('range', 'unknown')}",
            remediation=f"Run: npm audit fix or upgrade {pkg_name}",
        )
        findings.append(finding)
    return findings


# Map pip-audit severity aliases to normalised categories (like npm)
_PIP_SEVERITY_MAP = {
    "critical": "critical",
    "high": "high",
    "moderate": "medium",
    "medium": "medium",
    "low": "low",
    "info": "info",
    "unknown": "medium",
}


def audit_pip(repo_path: str) -> List[Finding]:
    """Run `pip audit --format=json` and convert to Finding list."""
    requirements = Path(repo_path) / "requirements.txt"
    pyproject = Path(repo_path) / "pyproject.toml"
    if not requirements.exists() and not pyproject.exists():
        return []

    data = _run_json(["pip", "audit", "--format=json"], cwd=repo_path)
    if not data:
        return []

    findings: List[Finding] = []
    for vuln in data.get("vulnerabilities", []):
        pkg = vuln.get("name", "unknown")
        vuln_id = vuln.get("id", "")
        desc = vuln.get("description", "")
        fix_ver = vuln.get("fix_versions", [])

        raw_severity = vuln.get("aliases", [{}])[0] if vuln.get("aliases") else ""
        # pip-audit may report severity in different fields depending on version
        sev_str = (
            vuln.get("severity")
            or vuln.get("fix_versions_severity", "")
            or "unknown"
        ).lower()
        normalised_sev = _PIP_SEVERITY_MAP.get(sev_str, "medium")

        finding = Finding(
            title=f"pip: {pkg} ({vuln_id})",
            description=desc[:200] if desc else f"Vulnerability in {pkg}",
            category=f"dependency-vuln-{normalised_sev}",
            source_file="requirements.txt",
            evidence=f"Installed: {vuln.get('version', '?')}, ID: {vuln_id}",
            remediation=f"Upgrade to: {', '.join(fix_ver)}" if fix_ver else "Check advisory",
        )
        findings.append(finding)
    return findings


def audit_all(repo_paths: dict[str, str]) -> List[Finding]:
    """Run all dependency audits across configured repos."""
    findings: List[Finding] = []
    for _name, path in repo_paths.items():
        findings.extend(audit_npm(path))
        findings.extend(audit_pip(path))
    return findings
