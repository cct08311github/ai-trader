"""Tests for the main archaeologist controller."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tools.archaeologist.archaeologist import run_archaeologist
from tools.archaeologist.models import DeadCode, DuplicateGroup, StaleFile


class TestRunArchaeologist:
    @patch("tools.archaeologist.archaeologist.find_duplicates")
    @patch("tools.archaeologist.archaeologist.find_dead_code")
    @patch("tools.archaeologist.archaeologist.find_stale_files")
    @patch("tools.archaeologist.archaeologist._load_config")
    def test_dry_run_no_issues_created(
        self, mock_config, mock_stale, mock_dead, mock_dupes, tmp_path,
    ):
        mock_config.return_value = {
            "repos": [{"path": str(tmp_path), "name": "test-repo", "language": "python"}],
            "stale_threshold_days": 180,
            "max_issues_per_run": 5,
            "exclude_patterns": [],
        }
        from datetime import date
        mock_stale.return_value = [
            StaleFile(path="old.py", last_modified_date=date(2024, 1, 1), days_stale=400),
        ]
        mock_dead.return_value = [
            DeadCode(path="orphan.py", type="module", reason="not imported"),
        ]
        mock_dupes.return_value = []

        report = run_archaeologist(config_path=str(tmp_path / "fake.yaml"), dry_run=True)
        assert report.repo_name == "test-repo"
        assert len(report.stale_files) == 1
        assert len(report.dead_code) == 1
        assert len(report.findings) == 2
        assert report.issues_created == []  # dry_run = True

    @patch("tools.archaeologist.archaeologist.find_duplicates")
    @patch("tools.archaeologist.archaeologist.find_dead_code")
    @patch("tools.archaeologist.archaeologist.find_stale_files")
    @patch("tools.archaeologist.archaeologist._load_config")
    def test_handles_detector_errors(
        self, mock_config, mock_stale, mock_dead, mock_dupes, tmp_path,
    ):
        mock_config.return_value = {
            "repos": [{"path": str(tmp_path), "name": "test-repo", "language": "python"}],
            "stale_threshold_days": 180,
            "max_issues_per_run": 5,
            "exclude_patterns": [],
        }
        mock_stale.side_effect = RuntimeError("git not found")
        mock_dead.return_value = []
        mock_dupes.return_value = []

        report = run_archaeologist(config_path=str(tmp_path / "fake.yaml"), dry_run=True)
        assert len(report.errors) == 1
        assert "git not found" in report.errors[0]
