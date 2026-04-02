"""report_generator.py — Generate CISSP-standard pentest report in Markdown."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .finding_scorer import RedTeamReport, ScoredFinding, Severity


def _severity_icon(severity: Severity) -> str:
    icons = {
        Severity.CRITICAL: "[CRITICAL]",
        Severity.HIGH: "[HIGH]",
        Severity.MEDIUM: "[MEDIUM]",
        Severity.LOW: "[LOW]",
        Severity.INFO: "[INFO]",
    }
    return icons.get(severity, "[?]")


def _finding_section(idx: int, sf: ScoredFinding) -> str:
    f = sf.finding
    lines = [
        f"### {idx}. {_severity_icon(sf.severity)} {f.title}",
        "",
        f"- **CVSS Score:** {sf.cvss_score:.1f}",
        f"- **Severity:** {sf.severity.value}",
        f"- **Category:** {f.category}",
    ]
    if f.source_file:
        loc = f.source_file
        if f.source_line:
            loc += f":{f.source_line}"
        lines.append(f"- **Location:** `{loc}`")
    lines.extend([
        "",
        f"**Description:** {f.description}",
        "",
    ])
    if f.evidence:
        lines.extend([
            "**Evidence:**",
            f"```",
            f.evidence,
            f"```",
            "",
        ])
    if f.remediation:
        lines.extend([
            f"**Remediation:** {f.remediation}",
            "",
        ])
    lines.append("---")
    return "\n".join(lines)


def generate_report(
    report: RedTeamReport,
    repo_name: str = "ai-trader",
    output_path: Optional[str] = None,
) -> str:
    """Generate a CISSP-standard penetration test report in Markdown."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections = [
        f"# Security Red Team Assessment Report",
        "",
        f"**Target:** {repo_name}",
        f"**Date:** {now}",
        f"**Scanner Version:** {report.scanner_version}",
        f"**Scan Duration:** {report.scan_duration_seconds:.1f}s",
        "",
        "---",
        "",
        "## 1. Executive Summary",
        "",
        f"This automated security assessment identified **{len(report.findings)} findings** across the {repo_name} infrastructure.",
        "",
        f"- **Critical:** {report.critical_count}",
        f"- **High:** {report.high_count}",
        f"- **Medium:** {sum(1 for f in report.findings if f.severity == Severity.MEDIUM)}",
        f"- **Low:** {sum(1 for f in report.findings if f.severity == Severity.LOW)}",
        f"- **Informational:** {sum(1 for f in report.findings if f.severity == Severity.INFO)}",
        "",
    ]

    if report.critical_count > 0:
        sections.append(
            "**Immediate action required:** Critical findings must be remediated before next deployment."
        )
        sections.append("")

    # Risk rating
    if report.critical_count > 0:
        risk = "CRITICAL"
    elif report.high_count > 0:
        risk = "HIGH"
    elif any(f.severity == Severity.MEDIUM for f in report.findings):
        risk = "MEDIUM"
    else:
        risk = "LOW"
    sections.extend([
        f"**Overall Risk Rating: {risk}**",
        "",
        "---",
        "",
        "## 2. Scope",
        "",
        "| Item | Detail |",
        "|------|--------|",
        f"| Target System | {repo_name} |",
        f"| Services Enumerated | {len(report.services)} |",
        "| Scan Type | Automated (safe payloads, localhost only) |",
        f"| Max Requests/Endpoint | 10 |",
        "",
    ])

    # Services
    if report.services:
        sections.extend([
            "---",
            "",
            "## 3. Discovered Services",
            "",
            "| Name | Status | PID | Details |",
            "|------|--------|-----|---------|",
        ])
        for svc in report.services:
            pid = str(svc.pid) if svc.pid else "-"
            extra_str = ", ".join(f"{k}={v}" for k, v in svc.extra.items()) if svc.extra else "-"
            sections.append(f"| {svc.name} | {svc.status} | {pid} | {extra_str} |")
        sections.append("")

    # Findings
    sections.extend([
        "---",
        "",
        "## 4. Detailed Findings",
        "",
    ])

    # Sort by severity (Critical first)
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
        Severity.INFO: 4,
    }
    sorted_findings = sorted(report.findings, key=lambda f: severity_order.get(f.severity, 5))

    if not sorted_findings:
        sections.append("No findings detected.")
    else:
        for idx, sf in enumerate(sorted_findings, start=1):
            sections.append(_finding_section(idx, sf))
            sections.append("")

    # Recommendations
    sections.extend([
        "---",
        "",
        "## 5. Recommendations",
        "",
        "1. **Secrets Management:** Move all hardcoded secrets to environment variables or a vault service",
        "2. **Dependency Updates:** Remediate all critical/high dependency vulnerabilities",
        "3. **Authentication:** Ensure all API endpoints require valid authentication tokens",
        "4. **Input Validation:** Sanitize file paths and URL parameters to prevent traversal/SSRF",
        "5. **HTTP Headers:** Add security headers (HSTS, CSP, X-Frame-Options) to all web responses",
        "6. **File Permissions:** Ensure .env files are not world-readable (chmod 600)",
        "",
        "---",
        "",
        "## 6. Methodology",
        "",
        "This assessment followed a CISSP-aligned penetration testing methodology:",
        "",
        "1. **Reconnaissance:** Service enumeration via pm2, nginx, tailscale",
        "2. **Vulnerability Assessment:** Dependency auditing (npm/pip), configuration review",
        "3. **Exploitation Simulation:** Safe payload testing for path traversal, auth bypass, SSRF",
        "4. **Reporting:** CVSS-based scoring with actionable remediation guidance",
        "",
        "All testing was conducted on localhost with safe, non-destructive payloads.",
        "",
        "---",
        "",
        f"*Report generated by Red Team Simulator v{report.scanner_version}*",
    ])

    content = "\n".join(sections)

    if output_path:
        with open(output_path, "w") as f:
            f.write(content)

    return content
