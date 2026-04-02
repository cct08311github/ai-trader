"""Tests for report_generator module."""
import tempfile
import os

import pytest

from tools.redteam.finding_scorer import (
    Finding,
    RedTeamReport,
    ScoredFinding,
    ServiceInfo,
    Severity,
)
from tools.redteam.report_generator import generate_report


class TestGenerateReport:
    def _make_report(self) -> RedTeamReport:
        return RedTeamReport(
            findings=[
                ScoredFinding(
                    finding=Finding(
                        title="Hardcoded token in ecosystem.config.js",
                        description="Telegram bot token is hardcoded",
                        category="hardcoded-secret",
                        source_file="ecosystem.config.js",
                        source_line=47,
                        evidence="BOT_TOKEN=8773****",
                        remediation="Use env var",
                    ),
                    cvss_score=9.0,
                    severity=Severity.CRITICAL,
                ),
                ScoredFinding(
                    finding=Finding(
                        title="Missing X-Frame-Options",
                        description="Nginx missing header",
                        category="missing-header",
                    ),
                    cvss_score=4.0,
                    severity=Severity.MEDIUM,
                ),
            ],
            services=[
                ServiceInfo(name="ai-trader-web", pid=1234, status="online"),
            ],
            scan_duration_seconds=2.5,
        )

    def test_contains_executive_summary(self):
        report = self._make_report()
        md = generate_report(report)
        assert "Executive Summary" in md
        assert "2 findings" in md

    def test_contains_critical_count(self):
        report = self._make_report()
        md = generate_report(report)
        assert "Critical:** 1" in md

    def test_contains_finding_details(self):
        report = self._make_report()
        md = generate_report(report)
        assert "Hardcoded token" in md
        assert "ecosystem.config.js:47" in md

    def test_contains_services(self):
        report = self._make_report()
        md = generate_report(report)
        assert "ai-trader-web" in md

    def test_contains_methodology(self):
        report = self._make_report()
        md = generate_report(report)
        assert "Methodology" in md
        assert "CISSP" in md

    def test_overall_risk_critical(self):
        report = self._make_report()
        md = generate_report(report)
        assert "Overall Risk Rating: CRITICAL" in md

    def test_writes_to_file(self):
        report = self._make_report()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            path = f.name

        generate_report(report, output_path=path)
        with open(path) as f:
            content = f.read()
        assert "Executive Summary" in content
        os.unlink(path)

    def test_empty_report(self):
        report = RedTeamReport()
        md = generate_report(report)
        assert "0 findings" in md
        assert "No findings detected" in md
        assert "Overall Risk Rating: LOW" in md

    def test_findings_sorted_by_severity(self):
        report = self._make_report()
        md = generate_report(report)
        # Critical should appear before Medium
        critical_pos = md.index("[CRITICAL]")
        medium_pos = md.index("[MEDIUM]")
        assert critical_pos < medium_pos
