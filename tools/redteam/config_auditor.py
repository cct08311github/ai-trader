"""config_auditor.py — Check .env permissions, nginx headers, hardcoded secrets."""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import List

from .finding_scorer import Finding

# Patterns that indicate hardcoded secrets
_SECRET_PATTERNS = [
    (r'(?:BOT_TOKEN|API_KEY|SECRET|PASSWORD|PRIVATE_KEY)\s*[:=]\s*["\']?[A-Za-z0-9_\-:]{20,}', "hardcoded-secret"),
    (r'(?:apiKey|authDomain|messagingSenderId)\s*[:=]\s*["\'][^"\']{10,}["\']', "hardcoded-api-key"),
    (r'ghp_[A-Za-z0-9]{36}', "hardcoded-secret"),  # GitHub PAT
    (r'xoxb-[A-Za-z0-9\-]+', "hardcoded-secret"),  # Slack bot token
]

# Required nginx security headers
_REQUIRED_HEADERS = [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Strict-Transport-Security",
    "Content-Security-Policy",
]


def check_env_permissions(repo_path: str) -> List[Finding]:
    """Check that .env files are not world-readable."""
    findings: List[Finding] = []
    repo = Path(repo_path)

    for env_file in repo.rglob(".env*"):
        if env_file.is_file() and not env_file.name.endswith(".example"):
            try:
                file_stat = os.stat(env_file)
                mode = file_stat.st_mode
                if mode & stat.S_IROTH:
                    findings.append(Finding(
                        title=f".env world-readable: {env_file.name}",
                        description=f"{env_file} is readable by all users (mode: {oct(mode)})",
                        category="insecure-permission",
                        source_file=str(env_file),
                        evidence=f"File mode: {oct(mode)}",
                        remediation=f"Run: chmod 600 {env_file}",
                    ))
            except OSError:
                pass
    return findings


def check_hardcoded_secrets(file_path: str) -> List[Finding]:
    """Scan a single file for hardcoded secrets."""
    findings: List[Finding] = []
    path = Path(file_path)

    if not path.is_file():
        return findings

    try:
        content = path.read_text(errors="ignore")
    except OSError:
        return findings

    for line_no, line in enumerate(content.splitlines(), start=1):
        for pattern, category in _SECRET_PATTERNS:
            if re.search(pattern, line):
                # Mask the actual value in evidence
                masked = re.sub(r'([A-Za-z0-9_\-]{4})[A-Za-z0-9_\-]{16,}', r'\1****', line.strip())
                findings.append(Finding(
                    title=f"Hardcoded secret in {path.name}",
                    description=f"Potential secret found at line {line_no}",
                    category=category,
                    source_file=str(path),
                    source_line=line_no,
                    evidence=f"Line {line_no}: {masked[:120]}",
                    remediation="Move secret to .env file and reference via environment variable",
                ))
                break  # One finding per line
    return findings


def check_nginx_headers(config_dir: str = "/etc/nginx/sites-enabled/") -> List[Finding]:
    """Check nginx configs for missing security headers."""
    findings: List[Finding] = []
    config_path = Path(config_dir)

    if not config_path.exists():
        return findings

    for conf_file in config_path.iterdir():
        if not conf_file.is_file():
            continue
        try:
            content = conf_file.read_text()
        except (OSError, PermissionError):
            continue

        for header in _REQUIRED_HEADERS:
            if header.lower() not in content.lower():
                findings.append(Finding(
                    title=f"Missing header: {header}",
                    description=f"nginx config {conf_file.name} lacks {header}",
                    category="missing-header",
                    source_file=str(conf_file),
                    remediation=f"Add: add_header {header} <value>;",
                ))
    return findings


def audit_config(repo_path: str, nginx_dir: str = "/etc/nginx/sites-enabled/") -> List[Finding]:
    """Run all config audits for a repo."""
    findings: List[Finding] = []
    repo = Path(repo_path)

    # .env permissions
    findings.extend(check_env_permissions(repo_path))

    # Hardcoded secrets in key config files
    for config_name in ["ecosystem.config.js", "ecosystem.config.cjs"]:
        config_file = repo / config_name
        if config_file.exists():
            findings.extend(check_hardcoded_secrets(str(config_file)))

    # Check for firebase config files with hardcoded keys
    for ts_file in repo.rglob("firebase*.ts"):
        findings.extend(check_hardcoded_secrets(str(ts_file)))
    for ts_file in repo.rglob("firebase*.js"):
        findings.extend(check_hardcoded_secrets(str(ts_file)))

    # nginx headers
    findings.extend(check_nginx_headers(nginx_dir))

    return findings
