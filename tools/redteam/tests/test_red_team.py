"""Tests for red_team main controller."""
import tempfile
import os
from unittest.mock import patch

import pytest

from tools.redteam.red_team import load_config, run_scan, main


class TestLoadConfig:
    def test_loads_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("scan:\n  max_requests_per_endpoint: 5\n")
            f.flush()

            config = load_config(f.name)
            assert config["scan"]["max_requests_per_endpoint"] == 5

        os.unlink(f.name)

    def test_returns_empty_on_missing_file(self):
        config = load_config("/nonexistent/config.yaml")
        assert config == {}


class TestRunScan:
    @patch("tools.redteam.red_team.enumerate_all")
    @patch("tools.redteam.red_team.audit_deps")
    @patch("tools.redteam.red_team.audit_config")
    @patch("tools.redteam.red_team.scan_path_traversal")
    @patch("tools.redteam.red_team.scan_auth_bypass")
    @patch("tools.redteam.red_team.scan_ssrf")
    def test_orchestrates_all_scanners(
        self, mock_ssrf, mock_auth, mock_traversal,
        mock_config, mock_deps, mock_enum
    ):
        from tools.redteam.finding_scorer import Finding, ServiceInfo

        mock_enum.return_value = [ServiceInfo(name="test-svc")]
        mock_deps.return_value = [Finding(title="dep", description="d", category="dependency-vuln-high")]
        mock_config.return_value = [Finding(title="cfg", description="d", category="hardcoded-secret")]
        mock_traversal.return_value = []
        mock_auth.return_value = []
        mock_ssrf.return_value = []

        # Use a minimal config with no targets
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("scan:\n  max_requests_per_endpoint: 5\nrepo_paths:\n  test: /tmp\n")
            f.flush()
            report = run_scan(f.name)

        os.unlink(f.name)

        assert len(report.services) == 1
        assert len(report.findings) == 2
        assert report.scan_duration_seconds > 0


class TestMain:
    @patch("tools.redteam.red_team.run_scan")
    def test_quiet_mode(self, mock_scan):
        from tools.redteam.finding_scorer import RedTeamReport

        mock_scan.return_value = RedTeamReport()

        exit_code = main(["--quiet", "--config", "/nonexistent.yaml"])
        assert exit_code == 0

    @patch("tools.redteam.red_team.run_scan")
    def test_returns_1_on_critical(self, mock_scan):
        from tools.redteam.finding_scorer import (
            Finding, RedTeamReport, ScoredFinding, Severity
        )

        mock_scan.return_value = RedTeamReport(
            findings=[
                ScoredFinding(
                    finding=Finding(title="x", description="d", category="c"),
                    cvss_score=9.5,
                    severity=Severity.CRITICAL,
                )
            ]
        )

        exit_code = main(["--quiet"])
        assert exit_code == 1
