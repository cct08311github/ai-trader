"""Shared dataclasses for Code Archaeologist."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class StaleFile:
    path: str
    last_modified_date: date
    days_stale: int


@dataclass
class DeadCode:
    path: str
    type: str  # module | function | export
    reason: str


@dataclass
class DuplicateGroup:
    files: List[str]
    similarity_score: float
    snippet_preview: str


@dataclass
class Finding:
    finding_type: str  # stale | dead_code | duplication
    summary: str
    details: str
    files: List[str]


@dataclass
class ArchaeologistReport:
    repo_name: str
    stale_files: List[StaleFile] = field(default_factory=list)
    dead_code: List[DeadCode] = field(default_factory=list)
    duplicates: List[DuplicateGroup] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    issues_created: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
