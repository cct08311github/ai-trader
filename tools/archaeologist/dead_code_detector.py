"""Detect potentially dead (unreferenced) modules and exports."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import List, Optional, Set

from tools.archaeologist.models import DeadCode

# Entry-point patterns that should never be flagged as dead
_ENTRY_POINT_PATTERNS = {
    "main.py", "cli.py", "__main__.py", "app.py", "wsgi.py", "asgi.py",
    "manage.py", "setup.py", "conftest.py",
}
_ENTRY_POINT_PREFIXES = ("test_", "conftest")

_EXCLUDE_DIRS = {
    "node_modules", ".venv", "bin/venv", "deploy-offline",
    "__pycache__", ".next", ".git", "tests", "test",
    "frontend", "tools", "doc", "config", "data",
    ".eggs", "dist", "build", "migrations",
}


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


def _is_entry_point(rel_path: str) -> bool:
    name = Path(rel_path).name
    if name in _ENTRY_POINT_PATTERNS:
        return True
    if any(name.startswith(p) for p in _ENTRY_POINT_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# Python dead-module detection via ast import graph
# ---------------------------------------------------------------------------

def _collect_python_files(repo_path: Path, exclude_patterns: Optional[List[str]] = None) -> List[str]:
    """Return list of .py relative paths."""
    files: List[str] = []
    for p in repo_path.rglob("*.py"):
        rel = str(p.relative_to(repo_path))
        if not _should_skip(rel, exclude_patterns):
            files.append(rel)
    return files


def _module_name_from_path(rel_path: str) -> str:
    """Convert 'src/foo/bar.py' -> 'src.foo.bar', '__init__.py' -> package."""
    p = Path(rel_path)
    parts = list(p.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _extract_imports(source: str) -> Set[str]:
    """Parse a Python source and return set of imported module names."""
    imports: Set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
                # Also add parent packages
                parts = node.module.split(".")
                for i in range(1, len(parts)):
                    imports.add(".".join(parts[:i]))
    return imports


def _find_dead_python(repo_path: str, exclude_patterns: Optional[List[str]] = None) -> List[DeadCode]:
    root = Path(repo_path).resolve()
    py_files = _collect_python_files(root, exclude_patterns)

    # Build module -> path mapping
    module_map: dict[str, str] = {}
    for rel in py_files:
        mod = _module_name_from_path(rel)
        if mod:
            module_map[mod] = rel

    # Collect all imports across the repo
    all_imports: Set[str] = set()
    for rel in py_files:
        try:
            source = (root / rel).read_text(errors="replace")
        except OSError:
            continue
        all_imports.update(_extract_imports(source))

    dead: List[DeadCode] = []
    for mod, rel in module_map.items():
        if _is_entry_point(rel):
            continue
        # Check if any import references this module (exact or prefix match)
        referenced = any(
            imp == mod or imp.startswith(mod + ".")
            for imp in all_imports
        )
        if not referenced:
            dead.append(DeadCode(
                path=rel,
                type="module",
                reason=f"Module '{mod}' is never imported by any other file in the repo",
            ))

    dead.sort(key=lambda d: d.path)
    return dead


# ---------------------------------------------------------------------------
# TypeScript dead-export detection via regex import scan
# ---------------------------------------------------------------------------

_TS_IMPORT_RE = re.compile(
    r"""(?:import|from)\s+['"]([^'"]+)['"]"""
    r"""|import\s*\{[^}]*\}\s*from\s*['"]([^'"]+)['"]"""
    r"""|require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
)


def _collect_ts_files(repo_path: Path, exclude_patterns: Optional[List[str]] = None) -> List[str]:
    files: List[str] = []
    for ext in ("*.ts", "*.tsx", "*.js", "*.jsx"):
        for p in repo_path.rglob(ext):
            rel = str(p.relative_to(repo_path))
            if not _should_skip(rel, exclude_patterns):
                files.append(rel)
    return files


def _find_dead_typescript(repo_path: str, exclude_patterns: Optional[List[str]] = None) -> List[DeadCode]:
    root = Path(repo_path).resolve()
    ts_files = _collect_ts_files(root, exclude_patterns)

    # Collect all imported paths
    imported_paths: Set[str] = set()
    for rel in ts_files:
        try:
            source = (root / rel).read_text(errors="replace")
        except OSError:
            continue
        for m in _TS_IMPORT_RE.finditer(source):
            imp = m.group(1) or m.group(2) or m.group(3)
            if imp and imp.startswith("."):
                # Resolve relative import to file path
                base_dir = (root / rel).parent
                resolved = (base_dir / imp).resolve()
                try:
                    imported_paths.add(str(resolved.relative_to(root)))
                except ValueError:
                    pass

    dead: List[DeadCode] = []
    for rel in ts_files:
        if _is_entry_point(rel):
            continue
        stem = str((root / rel).with_suffix("").resolve().relative_to(root))
        if stem not in imported_paths and rel not in imported_paths:
            dead.append(DeadCode(
                path=rel,
                type="module",
                reason=f"File '{rel}' is never imported by any other file in the repo",
            ))

    dead.sort(key=lambda d: d.path)
    return dead


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_dead_code(
    repo_path: str,
    language: str,
    exclude_patterns: Optional[List[str]] = None,
) -> List[DeadCode]:
    """Find potentially dead code in *repo_path* for the given language."""
    lang = language.lower()
    if lang in ("python", "py"):
        return _find_dead_python(repo_path, exclude_patterns)
    if lang in ("typescript", "ts", "javascript", "js"):
        return _find_dead_typescript(repo_path, exclude_patterns)
    return []
