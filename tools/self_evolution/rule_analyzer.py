"""rule_analyzer.py — 分析 CLAUDE.md 與 rules 的一致性與冗餘。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple


@dataclass
class RuleAnalysis:
    """Rules 分析結果。"""
    total_rules: int = 0
    redundant_pairs: List[Tuple[str, str, str]] = field(default_factory=list)
    outdated_refs: List[Tuple[str, str]] = field(default_factory=list)
    conflicts: List[Tuple[str, str, str]] = field(default_factory=list)
    files_scanned: int = 0


def _extract_rules(content: str) -> List[str]:
    """從 markdown 中提取條列式規則（以 - 或 * 開頭的行）。"""
    rules: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")):
            # 移除 list marker
            rule_text = re.sub(r"^[-*]\s+|^\d+\.\s+", "", stripped).strip()
            if len(rule_text) > 10:  # 跳過太短的行
                rules.append(rule_text)
    return rules


def _extract_path_refs(content: str) -> List[str]:
    """提取內容中參照的檔案路徑。"""
    paths: List[str] = []
    # 匹配 ~/... 或 ~/.claude/... 格式的路徑
    for match in re.finditer(r"[~./][\w./\-]+(?:\.(?:md|py|json|yaml|yml|toml))", content):
        paths.append(match.group())
    return paths


def _normalize_rule(rule: str) -> str:
    """正規化規則文字以便比較（小寫、移除標點符號和多餘空白）。"""
    text = rule.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    """簡單 Jaccard 相似度。"""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def analyze_rules(
    claude_md_paths: List[str],
    rules_dir: str,
    project_claude_md_paths: List[str] | None = None,
) -> RuleAnalysis:
    """分析 CLAUDE.md 和 rules 目錄中的規則。

    Args:
        claude_md_paths: 全域 CLAUDE.md 路徑列表。
        rules_dir: rules 目錄路徑。
        project_claude_md_paths: 專案層級 CLAUDE.md 路徑列表。

    Returns:
        RuleAnalysis 結果。
    """
    analysis = RuleAnalysis()
    # file_path -> list of rules
    all_file_rules: Dict[str, List[str]] = {}

    # 收集所有 rule 來源
    paths_to_scan: List[str] = []
    for p in claude_md_paths:
        expanded = os.path.expanduser(p)
        if os.path.isfile(expanded):
            paths_to_scan.append(expanded)

    rules_dir_path = Path(os.path.expanduser(rules_dir))
    if rules_dir_path.is_dir():
        for f in sorted(rules_dir_path.glob("*.md")):
            paths_to_scan.append(str(f))

    if project_claude_md_paths:
        for p in project_claude_md_paths:
            expanded = os.path.expanduser(p)
            if os.path.isfile(expanded):
                paths_to_scan.append(expanded)

    # 讀取每個檔案的規則
    for file_path in paths_to_scan:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        rules = _extract_rules(content)
        all_file_rules[file_path] = rules
        analysis.total_rules += len(rules)
        analysis.files_scanned += 1

        # 偵測過時的路徑參照
        path_refs = _extract_path_refs(content)
        for ref in path_refs:
            expanded_ref = os.path.expanduser(ref)
            if not os.path.exists(expanded_ref) and not ref.startswith("./"):
                analysis.outdated_refs.append((file_path, ref))

    # 偵測跨檔案冗餘規則
    file_list = list(all_file_rules.keys())
    for i in range(len(file_list)):
        for j in range(i + 1, len(file_list)):
            file_a, file_b = file_list[i], file_list[j]
            rules_a = [_normalize_rule(r) for r in all_file_rules[file_a]]
            rules_b = [_normalize_rule(r) for r in all_file_rules[file_b]]
            for ra in rules_a:
                for rb in rules_b:
                    if _similarity(ra, rb) > 0.75:
                        analysis.redundant_pairs.append((file_a, file_b, ra[:80]))

    # 偵測 project vs global 衝突（簡易：相似度高但不完全相同）
    if project_claude_md_paths:
        global_rules: List[Tuple[str, str]] = []
        project_rules: List[Tuple[str, str]] = []
        for fp, rules in all_file_rules.items():
            expanded_fp = fp
            for proj_path in project_claude_md_paths:
                if expanded_fp == os.path.expanduser(proj_path):
                    project_rules.extend((fp, r) for r in rules)
                    break
            else:
                global_rules.extend((fp, r) for r in rules)

        for gf, gr in global_rules:
            gr_norm = _normalize_rule(gr)
            for pf, pr in project_rules:
                pr_norm = _normalize_rule(pr)
                sim = _similarity(gr_norm, pr_norm)
                if 0.5 < sim < 0.9:  # 類似但不同 → 可能衝突
                    analysis.conflicts.append((gf, pf, gr_norm[:80]))

    return analysis
