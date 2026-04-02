"""Tests for dependency_auditor module."""
import json
import os
import tempfile
from unittest.mock import patch

import pytest

from tools.redteam.dependency_auditor import audit_npm, audit_pip, audit_all


class TestAuditNpm:
    def test_skips_if_no_package_json(self):
        with tempfile.TemporaryDirectory() as d:
            assert audit_npm(d) == []

    @patch("tools.redteam.dependency_auditor._run_json")
    def test_parses_npm_audit(self, mock_run):
        mock_run.return_value = {
            "vulnerabilities": {
                "lodash": {
                    "severity": "high",
                    "title": "Prototype Pollution",
                    "range": "<4.17.21",
                },
                "minimist": {
                    "severity": "critical",
                    "title": "Prototype Pollution",
                    "range": "<1.2.6",
                },
            }
        }

        with tempfile.TemporaryDirectory() as d:
            # Create package.json so the check passes
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write("{}")

            findings = audit_npm(d)
            assert len(findings) == 2
            categories = {f.category for f in findings}
            assert "dependency-vuln-high" in categories
            assert "dependency-vuln-critical" in categories

    @patch("tools.redteam.dependency_auditor._run_json")
    def test_empty_on_no_vulns(self, mock_run):
        mock_run.return_value = {"vulnerabilities": {}}

        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write("{}")
            assert audit_npm(d) == []


class TestAuditPip:
    def test_skips_if_no_requirements(self):
        with tempfile.TemporaryDirectory() as d:
            assert audit_pip(d) == []

    @patch("tools.redteam.dependency_auditor._run_json")
    def test_parses_pip_audit(self, mock_run):
        mock_run.return_value = {
            "vulnerabilities": [
                {
                    "name": "requests",
                    "id": "CVE-2023-1234",
                    "description": "SSRF vulnerability",
                    "version": "2.28.0",
                    "fix_versions": ["2.31.0"],
                },
            ]
        }

        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "requirements.txt"), "w") as f:
                f.write("requests==2.28.0\n")

            findings = audit_pip(d)
            assert len(findings) == 1
            assert "requests" in findings[0].title
            assert "CVE-2023-1234" in findings[0].evidence


class TestAuditAll:
    @patch("tools.redteam.dependency_auditor.audit_pip")
    @patch("tools.redteam.dependency_auditor.audit_npm")
    def test_combines_results(self, mock_npm, mock_pip):
        from tools.redteam.finding_scorer import Finding

        mock_npm.return_value = [Finding(title="npm-vuln", description="d", category="dependency-vuln-high")]
        mock_pip.return_value = [Finding(title="pip-vuln", description="d", category="dependency-vuln-high")]

        result = audit_all({"repo1": "/some/path"})
        assert len(result) == 2
