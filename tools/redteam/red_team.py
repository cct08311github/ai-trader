"""red_team.py — Main controller, orchestrates the security scan."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

from .config_auditor import audit_config
from .dependency_auditor import audit_all as audit_deps
from .finding_scorer import Finding, RedTeamReport, score_finding
from .report_generator import generate_report
from .service_enumerator import enumerate_all, ALLOWED_PM2_BINS, ALLOWED_NGINX_DIRS

# Attack simulators
from .attack_simulators.auth_bypass import scan_auth_bypass
from .attack_simulators.path_traversal import scan_path_traversal
from .attack_simulators.ssrf import scan_ssrf

from urllib.parse import urlparse

_DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"


def _is_localhost(url: str) -> bool:
    """Check if URL targets localhost using proper URL parsing."""
    parsed = urlparse(url)
    return parsed.hostname in ("localhost", "127.0.0.1", "::1")


def load_config(config_path: Optional[str] = None) -> dict:
    """Load scan configuration from YAML."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def run_scan(config_path: Optional[str] = None) -> RedTeamReport:
    """Execute the full red team scan and return a report."""
    config = load_config(config_path)
    scan_cfg = config.get("scan", {})
    max_req = scan_cfg.get("max_requests_per_endpoint", 10)
    timeout = scan_cfg.get("timeout_seconds", 5)

    report = RedTeamReport()
    start = time.time()

    # 1. Service enumeration
    pm2_bin = config.get("pm2_binary", "pm2")
    nginx_dir = config.get("nginx_config_path", "/etc/nginx/sites-enabled/")
    report.services = enumerate_all(pm2_bin=pm2_bin, nginx_dir=nginx_dir)

    # 2. Dependency audit
    repo_paths = config.get("repo_paths", {})
    dep_findings = audit_deps(repo_paths)

    # 3. Config audit
    config_findings: list[Finding] = []
    for _name, path in repo_paths.items():
        config_findings.extend(audit_config(path, nginx_dir))

    # 4. Attack simulations (localhost only)
    attack_findings: list[Finding] = []
    targets = config.get("targets", [])
    for target in targets:
        url = target.get("url", "")
        if not _is_localhost(url):
            continue

        attack_findings.extend(scan_path_traversal(url, max_requests=max_req, timeout=timeout))
        attack_findings.extend(scan_auth_bypass(url, max_requests=max_req, timeout=timeout))
        attack_findings.extend(scan_ssrf(url, max_requests=max_req, timeout=timeout))

    # 5. Score all findings
    all_findings = dep_findings + config_findings + attack_findings
    report.findings = [score_finding(f) for f in all_findings]
    report.scan_duration_seconds = time.time() - start

    return report


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Security Red Team Simulator for ai-trader"
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config.yaml (default: tools/redteam/config.yaml)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output path for Markdown report",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print summary line",
    )
    args = parser.parse_args(argv)

    report = run_scan(args.config)

    if args.quiet:
        print(report.summary)
    else:
        md = generate_report(report, output_path=args.output)
        if not args.output:
            print(md)
        else:
            print(f"Report written to {args.output}")
            print(report.summary)

    # Exit with non-zero if critical findings exist
    return 1 if report.critical_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
