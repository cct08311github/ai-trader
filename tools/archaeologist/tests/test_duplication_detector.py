"""Tests for duplication_detector module."""
from __future__ import annotations

import pytest

from tools.archaeologist.duplication_detector import (
    _jaccard,
    _ngrams,
    _tokenize,
    find_duplicates,
)


class TestTokenize:
    def test_strips_comments(self):
        source = "# comment\nx = 1\n// another comment\ny = 2"
        tokens = _tokenize(source)
        # Should not contain comment text
        assert all("comment" not in t for t in tokens)

    def test_normalises_identifiers(self):
        tokens = _tokenize("my_variable = another_var")
        # Non-keyword identifiers become _ID_
        assert tokens.count("_ID_") >= 2

    def test_preserves_keywords(self):
        tokens = _tokenize("if True:\n    return False")
        assert "if" in tokens
        assert "return" in tokens


class TestJaccard:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_empty_sets(self):
        assert _jaccard(set(), set()) == 0.0


class TestNgrams:
    def test_produces_ngrams(self):
        tokens = ["a", "b", "c", "d"]
        result = _ngrams(tokens, n=3)
        assert "a b c" in result
        assert "b c d" in result
        assert len(result) == 2


class TestFindDuplicates:
    def test_detects_near_duplicates(self, tmp_path):
        # Two files with very similar content
        code = "\n".join([
            "def process_data(items):",
            "    result = []",
            "    for item in items:",
            "        if item.is_valid():",
            "            result.append(item.transform())",
            "    return result",
            "",
            "def validate(data):",
            "    for entry in data:",
            "        if not entry:",
            "            raise ValueError('empty')",
            "    return True",
        ])
        (tmp_path / "a.py").write_text(code)
        # Slightly modified copy
        code_b = code.replace("process_data", "handle_data").replace("items", "records")
        (tmp_path / "b.py").write_text(code_b)

        result = find_duplicates(str(tmp_path), threshold=0.5)
        assert len(result) >= 1
        assert result[0].similarity_score >= 0.5

    def test_no_duplicates_for_different_files(self, tmp_path):
        (tmp_path / "x.py").write_text(
            "import os\nimport sys\ndef main():\n    os.listdir('.')\n    sys.exit(0)\n" * 3
        )
        (tmp_path / "y.py").write_text(
            "class Animal:\n    def speak(self):\n        raise NotImplementedError\n"
            "class Dog(Animal):\n    def speak(self):\n        return 'woof'\n" * 3
        )
        result = find_duplicates(str(tmp_path), threshold=0.9)
        assert len(result) == 0

    def test_skips_small_files(self, tmp_path):
        (tmp_path / "tiny.py").write_text("x = 1")
        (tmp_path / "tiny2.py").write_text("y = 1")
        result = find_duplicates(str(tmp_path))
        assert len(result) == 0
