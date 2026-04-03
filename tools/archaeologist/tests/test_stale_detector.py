"""Tests for stale_detector module."""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tools.archaeologist.stale_detector import _should_exclude, find_stale_files


class TestShouldExclude:
    def test_excludes_node_modules(self):
        assert _should_exclude("node_modules/foo/bar.js") is True

    def test_excludes_venv(self):
        assert _should_exclude(".venv/lib/site.py") is True

    def test_excludes_pycache(self):
        assert _should_exclude("src/__pycache__/mod.pyc") is True

    def test_excludes_lock_files(self):
        assert _should_exclude("poetry.lock") is True

    def test_excludes_json_config(self):
        assert _should_exclude("package.json") is True

    def test_allows_normal_files(self):
        assert _should_exclude("src/main.py") is False

    def test_extra_patterns(self):
        assert _should_exclude("vendor/lib.py", extra_patterns=["vendor"]) is True


class TestFindStaleFiles:
    @patch("tools.archaeologist.stale_detector.subprocess.run")
    def test_returns_stale_files(self, mock_run, tmp_path):
        # Create a fake file
        src = tmp_path / "old_file.py"
        src.write_text("x = 1")

        old_ts = int((date.today() - timedelta(days=200)).strftime("%s"))

        def side_effect(cmd, **kwargs):
            mock_result = MagicMock()
            if "ls-files" in cmd:
                mock_result.returncode = 0
                mock_result.stdout = "old_file.py\n"
            elif "log" in cmd:
                mock_result.returncode = 0
                mock_result.stdout = f"{old_ts}\n"
            else:
                mock_result.returncode = 1
                mock_result.stdout = ""
            return mock_result

        mock_run.side_effect = side_effect
        result = find_stale_files(str(tmp_path), days_threshold=180)
        assert len(result) == 1
        assert result[0].path == "old_file.py"
        assert result[0].days_stale >= 199

    @patch("tools.archaeologist.stale_detector.subprocess.run")
    def test_excludes_recent_files(self, mock_run, tmp_path):
        src = tmp_path / "new_file.py"
        src.write_text("x = 1")

        recent_ts = int((date.today() - timedelta(days=10)).strftime("%s"))

        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "ls-files" in cmd:
                m.returncode = 0
                m.stdout = "new_file.py\n"
            elif "log" in cmd:
                m.returncode = 0
                m.stdout = f"{recent_ts}\n"
            else:
                m.returncode = 1
                m.stdout = ""
            return m

        mock_run.side_effect = side_effect
        result = find_stale_files(str(tmp_path), days_threshold=180)
        assert len(result) == 0

    @patch("tools.archaeologist.stale_detector.subprocess.run")
    def test_handles_git_failure(self, mock_run, tmp_path):
        m = MagicMock()
        m.returncode = 1
        m.stdout = ""
        mock_run.return_value = m
        result = find_stale_files(str(tmp_path))
        assert result == []
