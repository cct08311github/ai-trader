"""finding_scorer.py — CVSS-like scoring and data models for red team findings."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


@dataclass
class Finding:
    """A single security finding before scoring."""

    title: str
    description: str
    category: str  # e.g. "hardcoded-secret", "missing-header", "auth-bypass"
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    evidence: str = ""
    remediation: str = ""


@dataclass
class ScoredFinding:
    """A Finding with CVSS-like score and severity."""

    finding: Finding
    cvss_score: float = 0.0
    severity: Severity = Severity.INFO

    @property
    def title(self) -> str:
        return self.finding.title

    @property
    def category(self) -> str:
        return self.finding.category


@dataclass
class ServiceInfo:
    """Information about a discovered service."""

    name: str
    pid: Optional[int] = None
    port: Optional[int] = None
    status: str = "unknown"
    pm2_id: Optional[int] = None
    extra: dict = field(default_factory=dict)


@dataclass
class RedTeamReport:
    """Aggregated report from all scanners."""

    findings: List[ScoredFinding] = field(default_factory=list)
    services: List[ServiceInfo] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    scanner_version: str = "1.0.0"

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == Severity.HIGH)

    @property
    def summary(self) -> str:
        total = len(self.findings)
        return (
            f"{total} findings: "
            f"{self.critical_count} Critical, {self.high_count} High, "
            f"{sum(1 for f in self.findings if f.severity == Severity.MEDIUM)} Medium, "
            f"{sum(1 for f in self.findings if f.severity == Severity.LOW)} Low, "
            f"{sum(1 for f in self.findings if f.severity == Severity.INFO)} Info"
        )


# ---------------------------------------------------------------------------
# Scoring logic
# ---------------------------------------------------------------------------

_CATEGORY_BASE_SCORES: dict[str, float] = {
    "hardcoded-secret": 9.0,
    "hardcoded-api-key": 8.5,
    "auth-bypass": 9.5,
    "path-traversal": 8.0,
    "ssrf": 8.5,
    "missing-header": 4.0,
    "insecure-permission": 6.0,
    "dependency-vuln-critical": 9.0,
    "dependency-vuln-high": 7.5,
    "dependency-vuln-medium": 5.0,
    "dependency-vuln-low": 3.0,
}


def score_finding(finding: Finding) -> ScoredFinding:
    """Assign a CVSS-like score and severity to a Finding."""
    base = _CATEGORY_BASE_SCORES.get(finding.category, 5.0)

    # Clamp to [0, 10]
    score = max(0.0, min(10.0, base))

    if score >= 9.0:
        severity = Severity.CRITICAL
    elif score >= 7.0:
        severity = Severity.HIGH
    elif score >= 4.0:
        severity = Severity.MEDIUM
    elif score >= 1.0:
        severity = Severity.LOW
    else:
        severity = Severity.INFO

    return ScoredFinding(finding=finding, cvss_score=score, severity=severity)
