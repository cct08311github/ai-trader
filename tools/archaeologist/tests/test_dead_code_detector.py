"""Tests for dead_code_detector module."""
from __future__ import annotations

import pytest

from tools.archaeologist.dead_code_detector import (
    _extract_imports,
    _is_entry_point,
    _module_name_from_path,
    find_dead_code,
)


class TestModuleNameFromPath:
    def test_simple_module(self):
        assert _module_name_from_path("foo/bar.py") == "foo.bar"

    def test_init_file(self):
        assert _module_name_from_path("foo/__init__.py") == "foo"

    def test_top_level(self):
        assert _module_name_from_path("main.py") == "main"


class TestExtractImports:
    def test_import_statement(self):
        result = _extract_imports("import os\nimport sys")
        assert "os" in result
        assert "sys" in result

    def test_from_import(self):
        result = _extract_imports("from pathlib import Path")
        assert "pathlib" in result

    def test_dotted_import(self):
        result = _extract_imports("from foo.bar.baz import Something")
        assert "foo.bar.baz" in result
        assert "foo" in result
        assert "foo.bar" in result

    def test_syntax_error(self):
        result = _extract_imports("this is not valid python {{{")
        assert result == set()


class TestIsEntryPoint:
    def test_main_py(self):
        assert _is_entry_point("src/main.py") is True

    def test_cli_py(self):
        assert _is_entry_point("cli.py") is True

    def test_test_file(self):
        assert _is_entry_point("tests/test_foo.py") is True

    def test_conftest(self):
        assert _is_entry_point("conftest.py") is True

    def test_regular_file(self):
        assert _is_entry_point("src/utils.py") is False


class TestFindDeadCode:
    def test_finds_unreferenced_module(self, tmp_path):
        # Create two files: one imports the other, one is orphaned
        (tmp_path / "used.py").write_text("def helper(): pass")
        (tmp_path / "orphan.py").write_text("def lonely(): pass")
        (tmp_path / "main.py").write_text("import used\nused.helper()")

        result = find_dead_code(str(tmp_path), language="python")
        paths = [d.path for d in result]
        assert "orphan.py" in paths
        # main.py is entry point, used.py is imported -> neither should be dead
        assert "main.py" not in paths
        assert "used.py" not in paths

    def test_no_false_positive_for_entry_points(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "test_foo.py").write_text("def test_it(): pass")
        result = find_dead_code(str(tmp_path), language="python")
        paths = [d.path for d in result]
        assert "main.py" not in paths
        assert "test_foo.py" not in paths

    def test_unsupported_language_returns_empty(self, tmp_path):
        result = find_dead_code(str(tmp_path), language="rust")
        assert result == []
