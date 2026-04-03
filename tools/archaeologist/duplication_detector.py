"""Detect near-duplicate source files using token-level Jaccard similarity."""
from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path
from typing import List, Optional, Set

from tools.archaeologist.models import DuplicateGroup

_EXCLUDE_DIRS = {
    "node_modules", ".venv", "bin/venv", "deploy-offline",
    "__pycache__", ".next", ".git",
}
_SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".go",
    ".rs", ".cs", ".rb", ".sh", ".yaml", ".yml",
}
_MIN_TOKENS = 30  # Skip very small files


def _should_skip(rel_path: str, exclude_patterns: Optional[List[str]] = None) -> bool:
    parts = Path(rel_path).parts
    for part in parts:
        if part in _EXCLUDE_DIRS:
            return True
        if exclude_patterns:
            for pat in exclude_patterns:
                if pat in part:
                    return True
    return False


def _tokenize(source: str) -> List[str]:
    """Strip whitespace and normalise variable names to produce comparable tokens."""
    # Remove comments (simplified: Python # and JS/TS //)
    lines = source.splitlines()
    cleaned: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        cleaned.append(stripped)
    text = "\n".join(cleaned)

    # Tokenize: split on non-word characters, lower-case
    tokens = re.findall(r"[a-zA-Z_]\w*", text)
    # Normalise identifiers: replace camelCase/snake_case with generic placeholder
    # to focus on structural similarity
    normalised: List[str] = []
    keywords = {
        "if", "else", "for", "while", "return", "def", "class", "import", "from",
        "function", "const", "let", "var", "async", "await", "try", "except",
        "catch", "finally", "with", "yield", "raise", "throw", "new", "export",
        "default", "switch", "case", "break", "continue", "pass", "lambda",
        "self", "this", "true", "false", "none", "null", "undefined",
        "and", "or", "not", "in", "is", "as", "elif", "type", "interface",
        "struct", "enum", "impl", "pub", "fn", "mod", "use", "crate",
    }
    for t in tokens:
        low = t.lower()
        if low in keywords:
            normalised.append(low)
        else:
            normalised.append("_ID_")
    return normalised


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _ngrams(tokens: List[str], n: int = 3) -> Set[str]:
    """Return set of n-gram strings for better structural comparison."""
    if len(tokens) < n:
        return set(tokens)
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def find_duplicates(
    repo_path: str,
    threshold: float = 0.7,
    exclude_patterns: Optional[List[str]] = None,
) -> List[DuplicateGroup]:
    """Find near-duplicate source files with Jaccard similarity > threshold."""
    root = Path(repo_path).resolve()

    # Collect source files
    file_tokens: dict[str, Set[str]] = {}
    file_previews: dict[str, str] = {}

    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in _SOURCE_EXTENSIONS:
            continue
        rel = str(p.relative_to(root))
        if _should_skip(rel, exclude_patterns):
            continue

        try:
            source = p.read_text(errors="replace")
        except OSError:
            continue

        tokens = _tokenize(source)
        if len(tokens) < _MIN_TOKENS:
            continue

        file_tokens[rel] = _ngrams(tokens)
        # Keep first 3 non-empty lines as preview
        preview_lines = [l for l in source.splitlines() if l.strip()][:3]
        file_previews[rel] = "\n".join(preview_lines)

    # Pairwise comparison
    files = list(file_tokens.keys())
    groups: List[DuplicateGroup] = []
    seen: Set[str] = set()

    for a, b in combinations(files, 2):
        if a in seen and b in seen:
            continue
        sim = _jaccard(file_tokens[a], file_tokens[b])
        if sim >= threshold:
            groups.append(DuplicateGroup(
                files=[a, b],
                similarity_score=round(sim, 3),
                snippet_preview=file_previews.get(a, "")[:200],
            ))
            seen.add(a)
            seen.add(b)

    groups.sort(key=lambda g: g.similarity_score, reverse=True)
    return groups
