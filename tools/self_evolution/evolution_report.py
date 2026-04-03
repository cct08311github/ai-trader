"""evolution_report.py — 產生 markdown 格式的進化報告。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .memory_analyzer import MemoryAnalysis
from .proposal_generator import EvolutionProposal
from .rule_analyzer import RuleAnalysis


def generate_report(
    memory_analysis: MemoryAnalysis,
    rule_analysis: RuleAnalysis,
    proposals: List[EvolutionProposal],
    log_path: Optional[str] = None,
) -> str:
    """產生完整的 markdown 進化報告。

    Args:
        memory_analysis: Memory 分析結果。
        rule_analysis: Rule 分析結果。
        proposals: 改善提案列表。
        log_path: evolution_log.json 路徑（用於 week-over-week 比較）。

    Returns:
        Markdown 格式的報告字串。
    """
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections: List[str] = []

    # Header
    sections.append(f"# Self-Evolution Report — {now}\n")

    # Memory Health
    sections.append("## Memory Health\n")
    sections.append(f"| 指標 | 數值 |")
    sections.append(f"|------|------|")
    sections.append(f"| 總計 | {memory_analysis.total} |")
    for mem_type, count in sorted(memory_analysis.by_type.items()):
        sections.append(f"| 類型: {mem_type} | {count} |")
    sections.append(f"| 過期 (>{30} 天) | {memory_analysis.stale_count} |")
    sections.append(f"| 疑似重複 | {len(memory_analysis.duplicates)} 組 |")
    if memory_analysis.oldest:
        sections.append(
            f"| 最舊 | {memory_analysis.oldest.name} ({memory_analysis.oldest.age_days} 天) |"
        )
    if memory_analysis.newest:
        sections.append(
            f"| 最新 | {memory_analysis.newest.name} ({memory_analysis.newest.age_days} 天) |"
        )
    sections.append("")

    # Rule Health
    sections.append("## Rule Health\n")
    sections.append(f"| 指標 | 數值 |")
    sections.append(f"|------|------|")
    sections.append(f"| 掃描檔案數 | {rule_analysis.files_scanned} |")
    sections.append(f"| 規則總計 | {rule_analysis.total_rules} |")
    sections.append(f"| 冗餘規則對 | {len(rule_analysis.redundant_pairs)} |")
    sections.append(f"| 過時參照 | {len(rule_analysis.outdated_refs)} |")
    sections.append(f"| 潛在衝突 | {len(rule_analysis.conflicts)} |")
    sections.append("")

    # Proposals
    sections.append("## Improvement Proposals\n")
    if not proposals:
        sections.append("_目前沒有改善提案。系統健康狀態良好。_\n")
    else:
        for i, p in enumerate(proposals, 1):
            sections.append(f"### Proposal {i}: {p.proposal_type.value}\n")
            sections.append(f"- **目標**: `{p.target_file}`")
            sections.append(f"- **說明**: {p.description}")
            sections.append(f"- **信心度**: {p.confidence:.0%}")
            sections.append(f"\n```diff\n{p.diff_preview}\n```\n")

    # Week-over-week comparison
    prev = _get_previous_run(log_path) if log_path else None
    if prev:
        sections.append("## Week-over-Week Comparison\n")
        sections.append(f"| 指標 | 上次 | 本次 | 變化 |")
        sections.append(f"|------|------|------|------|")
        prev_mem = prev.get("memory_stats", {})
        prev_rule = prev.get("rule_stats", {})
        _wow_row(sections, "Memory 總計", prev_mem.get("total", 0), memory_analysis.total)
        _wow_row(sections, "過期 Memory", prev_mem.get("stale", 0), memory_analysis.stale_count)
        _wow_row(sections, "規則總計", prev_rule.get("total", 0), rule_analysis.total_rules)
        _wow_row(
            sections, "冗餘規則",
            prev_rule.get("redundant", 0), len(rule_analysis.redundant_pairs),
        )
        sections.append("")

    # Footer
    sections.append("---")
    sections.append("*此報告為 advisory only — 所有提案需人工確認後才會執行。*\n")

    return "\n".join(sections)


def _wow_row(
    sections: List[str], label: str, prev_val: int, curr_val: int,
) -> None:
    """產生 week-over-week 比較的一行。"""
    delta = curr_val - prev_val
    sign = "+" if delta > 0 else ""
    sections.append(f"| {label} | {prev_val} | {curr_val} | {sign}{delta} |")


def _get_previous_run(log_path: Optional[str]) -> Optional[Dict]:
    """從 evolution_log.json 取得上一次執行記錄。"""
    if not log_path:
        return None
    expanded = os.path.expanduser(log_path)
    if not os.path.isfile(expanded):
        return None
    try:
        data = json.loads(Path(expanded).read_text(encoding="utf-8"))
        if isinstance(data, list) and data:
            return data[-1]
    except (json.JSONDecodeError, OSError):
        pass
    return None
