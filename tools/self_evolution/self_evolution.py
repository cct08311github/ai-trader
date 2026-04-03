"""self_evolution.py — 主控制器：協調分析 → 提案 → 報告 → 記錄。"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .evolution_report import generate_report
from .memory_analyzer import MemoryAnalysis, analyze_memories
from .proposal_generator import (
    EvolutionProposal,
    generate_proposals,
)
from .rule_analyzer import RuleAnalysis, analyze_rules

_THIS_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _THIS_DIR / "config.yaml"
_DEFAULT_LOG = _THIS_DIR / "evolution_log.json"


@dataclass
class EvolutionReport:
    """完整的進化報告。"""
    memory_analysis: MemoryAnalysis
    rule_analysis: RuleAnalysis
    proposals: List[EvolutionProposal]
    report_markdown: str
    run_date: str


def _load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """載入 config.yaml。"""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not path.is_file():
        return {
            "claude_md_paths": ["~/.claude/CLAUDE.md"],
            "rules_dir": "~/.claude/rules",
            "memory_dirs": [],
            "max_proposals": 3,
            "stale_memory_days": 30,
        }
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _append_log(
    log_path: Path,
    run_date: str,
    proposals: List[EvolutionProposal],
    memory_analysis: MemoryAnalysis,
    rule_analysis: RuleAnalysis,
) -> None:
    """將本次執行結果追加到 evolution_log.json。"""
    log_data: List[Dict[str, Any]] = []
    if log_path.is_file():
        try:
            log_data = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log_data = []

    entry = {
        "run_date": run_date,
        "proposals_generated": len(proposals),
        "proposals_accepted": 0,
        "proposals_rejected": 0,
        "memory_stats": {
            "total": memory_analysis.total,
            "stale": memory_analysis.stale_count,
            "duplicates": len(memory_analysis.duplicates),
            "by_type": memory_analysis.by_type,
        },
        "rule_stats": {
            "total": rule_analysis.total_rules,
            "redundant": len(rule_analysis.redundant_pairs),
            "outdated_refs": len(rule_analysis.outdated_refs),
            "conflicts": len(rule_analysis.conflicts),
        },
    }
    log_data.append(entry)
    log_path.write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_self_evolution(
    config_path: Optional[str] = None,
    log_path: Optional[str] = None,
) -> EvolutionReport:
    """執行完整的自我進化分析循環。

    流程：
    1. 載入設定
    2. 分析 memory 檔案
    3. 分析 rule 檔案
    4. 產生改善提案（最多 max_proposals 個）
    5. 產生 markdown 報告
    6. 寫入 evolution_log.json

    Args:
        config_path: config.yaml 路徑（None 使用預設）。
        log_path: evolution_log.json 路徑（None 使用預設）。

    Returns:
        EvolutionReport 包含完整分析結果。
    """
    config = _load_config(config_path)
    run_date = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolved_log = Path(log_path) if log_path else _DEFAULT_LOG

    # Step 1: Memory 分析
    memory_analysis = analyze_memories(
        memory_dirs=config.get("memory_dirs", []),
        stale_days=config.get("stale_memory_days", 30),
    )

    # Step 2: Rule 分析
    rule_analysis = analyze_rules(
        claude_md_paths=config.get("claude_md_paths", []),
        rules_dir=config.get("rules_dir", "~/.claude/rules"),
    )

    # Step 3: 產生提案
    max_proposals = config.get("max_proposals", 3)
    proposals = generate_proposals(
        memory_analysis, rule_analysis, max_proposals=max_proposals,
    )

    # Step 4: 產生報告
    report_md = generate_report(
        memory_analysis, rule_analysis, proposals,
        log_path=str(resolved_log),
    )

    # Step 5: 記錄到 log
    _append_log(resolved_log, run_date, proposals, memory_analysis, rule_analysis)

    return EvolutionReport(
        memory_analysis=memory_analysis,
        rule_analysis=rule_analysis,
        proposals=proposals,
        report_markdown=report_md,
        run_date=run_date,
    )


if __name__ == "__main__":
    result = run_self_evolution()
    print(result.report_markdown)
