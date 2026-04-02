"""Tests for finding_scorer module."""
import pytest

from tools.redteam.finding_scorer import (
    Finding,
    RedTeamReport,
    ScoredFinding,
    Severity,
    score_finding,
)


class TestFinding:
    def test_basic_creation(self):
        f = Finding(
            title="Test finding",
            description="A test",
            category="hardcoded-secret",
        )
        assert f.title == "Test finding"
        assert f.source_file is None
        assert f.source_line is None

    def test_full_creation(self):
        f = Finding(
            title="Secret in config",
            description="Found a token",
            category="hardcoded-secret",
            source_file="ecosystem.config.js",
            source_line=47,
            evidence="BOT_TOKEN=****",
            remediation="Use env vars",
        )
        assert f.source_line == 47
        assert f.source_file == "ecosystem.config.js"


class TestScoreFinding:
    def test_hardcoded_secret_is_critical(self):
        f = Finding(title="t", description="d", category="hardcoded-secret")
        scored = score_finding(f)
        assert scored.severity == Severity.CRITICAL
        assert scored.cvss_score == 9.0

    def test_auth_bypass_is_critical(self):
        f = Finding(title="t", description="d", category="auth-bypass")
        scored = score_finding(f)
        assert scored.severity == Severity.CRITICAL
        assert scored.cvss_score == 9.5

    def test_missing_header_is_medium(self):
        f = Finding(title="t", description="d", category="missing-header")
        scored = score_finding(f)
        assert scored.severity == Severity.MEDIUM
        assert scored.cvss_score == 4.0

    def test_unknown_category_defaults_medium(self):
        f = Finding(title="t", description="d", category="unknown-thing")
        scored = score_finding(f)
        assert scored.cvss_score == 5.0
        assert scored.severity == Severity.MEDIUM

    def test_dependency_vuln_low(self):
        f = Finding(title="t", description="d", category="dependency-vuln-low")
        scored = score_finding(f)
        assert scored.severity == Severity.LOW
        assert scored.cvss_score == 3.0

    def test_scored_finding_delegates_properties(self):
        f = Finding(title="My Title", description="d", category="ssrf")
        sf = score_finding(f)
        assert sf.title == "My Title"
        assert sf.category == "ssrf"


class TestRedTeamReport:
    def test_empty_report(self):
        r = RedTeamReport()
        assert r.critical_count == 0
        assert r.high_count == 0
        assert "0 findings" in r.summary

    def test_summary_counts(self):
        findings = [
            ScoredFinding(
                finding=Finding(title="a", description="", category="x"),
                cvss_score=9.5,
                severity=Severity.CRITICAL,
            ),
            ScoredFinding(
                finding=Finding(title="b", description="", category="y"),
                cvss_score=7.5,
                severity=Severity.HIGH,
            ),
            ScoredFinding(
                finding=Finding(title="c", description="", category="z"),
                cvss_score=4.0,
                severity=Severity.MEDIUM,
            ),
        ]
        r = RedTeamReport(findings=findings)
        assert r.critical_count == 1
        assert r.high_count == 1
        assert "3 findings" in r.summary
