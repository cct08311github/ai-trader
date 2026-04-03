"""Tests for issue_creator module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tools.archaeologist.issue_creator import _build_title, create_issues
from tools.archaeologist.models import Finding


class TestBuildTitle:
    def test_format(self):
        finding = Finding(
            finding_type="stale",
            summary="5 files stale",
            details="...",
            files=["a.py"],
        )
        title = _build_title("ai-trader", finding)
        assert title.startswith("[Archaeologist]")
        assert "ai-trader" in title
        assert "stale" in title


class TestCreateIssues:
    @patch("tools.archaeologist.issue_creator.subprocess.run")
    def test_creates_issues(self, mock_run):
        # Mock: no existing issues, successful creation
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = ""
            elif "label" in cmd:
                m.returncode = 0
                m.stdout = ""
            elif "create" in cmd:
                m.returncode = 0
                m.stdout = "https://github.com/org/repo/issues/99\n"
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect

        findings = [
            Finding(finding_type="stale", summary="3 stale files", details="...", files=["a.py"]),
        ]
        urls = create_issues(findings, "ai-trader", max_issues=5)
        assert len(urls) == 1
        assert "issues/99" in urls[0]

    @patch("tools.archaeologist.issue_creator.subprocess.run")
    def test_respects_max_issues(self, mock_run):
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = ""
            elif "label" in cmd:
                m.returncode = 0
                m.stdout = ""
            elif "create" in cmd:
                m.returncode = 0
                m.stdout = "https://github.com/org/repo/issues/1\n"
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect

        findings = [
            Finding(finding_type=f"type_{i}", summary=f"finding {i}", details="...", files=["x.py"])
            for i in range(10)
        ]
        urls = create_issues(findings, "ai-trader", max_issues=2)
        assert len(urls) == 2

    @patch("tools.archaeologist.issue_creator.subprocess.run")
    def test_deduplicates(self, mock_run):
        existing_title = "[Archaeologist] ai-trader: stale - 3 stale files"

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = existing_title + "\n"
            elif "label" in cmd:
                m.returncode = 0
                m.stdout = ""
            elif "create" in cmd:
                m.returncode = 0
                m.stdout = "https://github.com/org/repo/issues/2\n"
            else:
                m.returncode = 0
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect

        findings = [
            Finding(finding_type="stale", summary="3 stale files", details="...", files=["a.py"]),
        ]
        urls = create_issues(findings, "ai-trader", max_issues=5)
        assert len(urls) == 0  # Should skip because title matches existing
