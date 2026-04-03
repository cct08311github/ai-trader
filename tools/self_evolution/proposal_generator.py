"""proposal_generator.py — 從分析結果產生改善提案。"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from typing import List

from .memory_analyzer import MemoryAnalysis
from .rule_analyzer import RuleAnalysis


class ProposalType(str, Enum):
    MEMORY_ARCHIVE = "memory_archive"
    RULE_MERGE = "rule_merge"
    RULE_UPDATE = "rule_update"


@dataclass
class EvolutionProposal:
    """單一改善提案。"""
    proposal_type: ProposalType
    target_file: str
    description: str
    diff_preview: str
    confidence: float  # 0.0 ~ 1.0


def _make_archive_diff(file_path: str, name: str) -> str:
    """產生 memory 歸檔的 diff 預覽。"""
    old_lines = [f"# Active memory: {name}\n"]
    new_lines = [f"# Archived memory: {name}\n", "# Status: archived (stale > 30 days)\n"]
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=file_path,
        tofile=file_path.replace(".md", ".archived.md"),
        lineterm="",
    )
    return "\n".join(diff)


def _make_merge_diff(file_a: str, file_b: str, common_rule: str) -> str:
    """產生規則合併的 diff 預覽。"""
    old_lines = [
        f"# In {file_a}:\n",
        f"- {common_rule}\n",
        f"\n",
        f"# In {file_b}:\n",
        f"- {common_rule}\n",
    ]
    new_lines = [
        f"# Merged (keep in {file_a} only):\n",
        f"- {common_rule}\n",
        f"\n",
        f"# Removed from {file_b}\n",
    ]
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="before_merge",
        tofile="after_merge",
        lineterm="",
    )
    return "\n".join(diff)


def generate_proposals(
    memory_analysis: MemoryAnalysis,
    rule_analysis: RuleAnalysis,
    max_proposals: int = 3,
) -> List[EvolutionProposal]:
    """從 memory 與 rule 分析結果產生改善提案。

    優先順序：
    1. 過期 memory（建議歸檔）
    2. 冗餘規則（建議合併）
    3. 過時路徑參照（建議更新）

    Args:
        memory_analysis: Memory 分析結果。
        rule_analysis: Rule 分析結果。
        max_proposals: 最大提案數。

    Returns:
        最多 max_proposals 個 EvolutionProposal。
    """
    proposals: List[EvolutionProposal] = []

    # 1. 過期 memory → 建議歸檔
    stale_entries = [e for e in memory_analysis.entries if e.needs_review]
    stale_entries.sort(key=lambda e: e.age_days, reverse=True)
    for entry in stale_entries:
        if len(proposals) >= max_proposals:
            break
        proposals.append(EvolutionProposal(
            proposal_type=ProposalType.MEMORY_ARCHIVE,
            target_file=entry.file_path,
            description=(
                f"Memory '{entry.name}' 已 {entry.age_days} 天未更新，"
                f"建議 review 並考慮歸檔。"
            ),
            diff_preview=_make_archive_diff(entry.file_path, entry.name),
            confidence=min(0.9, 0.5 + entry.age_days / 100),
        ))

    # 2. 冗餘規則 → 建議合併
    for file_a, file_b, common in rule_analysis.redundant_pairs:
        if len(proposals) >= max_proposals:
            break
        proposals.append(EvolutionProposal(
            proposal_type=ProposalType.RULE_MERGE,
            target_file=file_a,
            description=(
                f"規則 '{common[:50]}...' 同時出現在 "
                f"{_short_path(file_a)} 和 {_short_path(file_b)}，建議合併。"
            ),
            diff_preview=_make_merge_diff(
                _short_path(file_a), _short_path(file_b), common,
            ),
            confidence=0.7,
        ))

    # 3. 過時參照 → 建議更新
    for file_path, ref in rule_analysis.outdated_refs:
        if len(proposals) >= max_proposals:
            break
        proposals.append(EvolutionProposal(
            proposal_type=ProposalType.RULE_UPDATE,
            target_file=file_path,
            description=(
                f"{_short_path(file_path)} 參照了不存在的路徑 '{ref}'，"
                f"建議更新或移除。"
            ),
            diff_preview=f"- 移除或修正對 '{ref}' 的參照",
            confidence=0.8,
        ))

    return proposals[:max_proposals]


def _short_path(path: str) -> str:
    """縮短路徑以提高可讀性。"""
    home = str(__import__("pathlib").Path.home())
    if path.startswith(home):
        return "~" + path[len(home):]
    return path
