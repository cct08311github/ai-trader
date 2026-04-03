"""tests/test_self_evolution.py — Self-evolution 單元測試。"""
from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """建立模擬 memory 目錄。"""
    mem_dir = tmp_path / "memory"
    mem_dir.mkdir()

    # 一個 fresh memory
    (mem_dir / "fresh.md").write_text(textwrap.dedent("""\
        ---
        name: fresh_memory
        description: A fresh memory
        type: reference
        ---
        Content here.
    """))

    # 一個 stale memory（修改時間設為 60 天前）
    stale = mem_dir / "stale.md"
    stale.write_text(textwrap.dedent("""\
        ---
        name: stale_memory
        description: An old memory
        type: feedback
        ---
        Old content.
    """))
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=60)).timestamp()
    os.utime(stale, (old_time, old_time))

    # 一個有重複 description 的 memory
    (mem_dir / "duplicate.md").write_text(textwrap.dedent("""\
        ---
        name: duplicate_memory
        description: A fresh memory
        type: reference
        ---
        Same description as fresh.
    """))

    # MEMORY.md（應被跳過）
    (mem_dir / "MEMORY.md").write_text("# Memory Index\n- fresh.md\n")

    return mem_dir


@pytest.fixture
def rules_setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """建立模擬 rules 目錄和 CLAUDE.md。"""
    # Global CLAUDE.md
    global_md = tmp_path / "CLAUDE.md"
    global_md.write_text(textwrap.dedent("""\
        # Global Rules
        - Never commit secrets or API keys
        - Use parameterized queries for SQL
        - Run tests before pushing
    """))

    # Rules directory
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "security.md").write_text(textwrap.dedent("""\
        # Security Rules
        - Never commit secrets or API keys
        - Validate all external input
        - Reference: ~/.nonexistent/path.md
    """))

    # Project CLAUDE.md
    project_md = tmp_path / "project_CLAUDE.md"
    project_md.write_text(textwrap.dedent("""\
        # Project Rules
        - Run tests before pushing code
        - Use type hints everywhere
    """))

    return global_md, rules_dir, project_md


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """建立模擬 evolution_log.json。"""
    log = tmp_path / "evolution_log.json"
    log.write_text(json.dumps([
        {
            "run_date": "2026-03-25T00:00:00Z",
            "proposals_generated": 2,
            "proposals_accepted": 1,
            "proposals_rejected": 1,
            "memory_stats": {"total": 5, "stale": 1, "duplicates": 0, "by_type": {}},
            "rule_stats": {"total": 10, "redundant": 1, "outdated_refs": 0, "conflicts": 0},
        }
    ]))
    return log


# ---------------------------------------------------------------------------
# Memory Analyzer Tests
# ---------------------------------------------------------------------------

class TestMemoryAnalyzer:
    def test_total_count_excludes_memory_md(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories([str(memory_dir)])
        assert result.total == 3  # fresh + stale + duplicate, not MEMORY.md

    def test_stale_detection(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories([str(memory_dir)], stale_days=30)
        assert result.stale_count == 1
        stale_entries = [e for e in result.entries if e.needs_review]
        assert stale_entries[0].name == "stale_memory"

    def test_age_calculation(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories([str(memory_dir)])
        stale = [e for e in result.entries if e.name == "stale_memory"][0]
        assert stale.age_days >= 59  # 設定為 60 天前

    def test_duplicate_detection(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories([str(memory_dir)])
        assert len(result.duplicates) == 1

    def test_by_type(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories([str(memory_dir)])
        assert result.by_type["reference"] == 2
        assert result.by_type["feedback"] == 1

    def test_empty_dir(self, tmp_path: Path):
        from tools.self_evolution.memory_analyzer import analyze_memories
        empty = tmp_path / "empty"
        empty.mkdir()
        result = analyze_memories([str(empty)])
        assert result.total == 0

    def test_nonexistent_dir(self):
        from tools.self_evolution.memory_analyzer import analyze_memories
        result = analyze_memories(["/nonexistent/path"])
        assert result.total == 0


# ---------------------------------------------------------------------------
# Rule Analyzer Tests
# ---------------------------------------------------------------------------

class TestRuleAnalyzer:
    def test_rule_count(self, rules_setup):
        from tools.self_evolution.rule_analyzer import analyze_rules
        global_md, rules_dir, project_md = rules_setup
        result = analyze_rules([str(global_md)], str(rules_dir))
        # global: 3 rules + security: 3 rules = 6
        assert result.total_rules == 6

    def test_redundancy_detection(self, rules_setup):
        from tools.self_evolution.rule_analyzer import analyze_rules
        global_md, rules_dir, _ = rules_setup
        result = analyze_rules([str(global_md)], str(rules_dir))
        # "Never commit secrets or API keys" appears in both
        assert len(result.redundant_pairs) >= 1

    def test_outdated_ref_detection(self, rules_setup):
        from tools.self_evolution.rule_analyzer import analyze_rules
        global_md, rules_dir, _ = rules_setup
        result = analyze_rules([str(global_md)], str(rules_dir))
        # ~/.nonexistent/path.md should be flagged
        assert len(result.outdated_refs) >= 1

    def test_files_scanned(self, rules_setup):
        from tools.self_evolution.rule_analyzer import analyze_rules
        global_md, rules_dir, _ = rules_setup
        result = analyze_rules([str(global_md)], str(rules_dir))
        assert result.files_scanned == 2  # CLAUDE.md + security.md


# ---------------------------------------------------------------------------
# Proposal Generator Tests
# ---------------------------------------------------------------------------

class TestProposalGenerator:
    def test_max_proposals_limit(self, memory_dir: Path, rules_setup):
        from tools.self_evolution.memory_analyzer import analyze_memories
        from tools.self_evolution.proposal_generator import generate_proposals
        from tools.self_evolution.rule_analyzer import analyze_rules

        global_md, rules_dir, _ = rules_setup
        mem = analyze_memories([str(memory_dir)])
        rules = analyze_rules([str(global_md)], str(rules_dir))

        proposals = generate_proposals(mem, rules, max_proposals=2)
        assert len(proposals) <= 2

    def test_stale_memory_proposal(self, memory_dir: Path):
        from tools.self_evolution.memory_analyzer import MemoryAnalysis, MemoryEntry, analyze_memories
        from tools.self_evolution.proposal_generator import ProposalType, generate_proposals
        from tools.self_evolution.rule_analyzer import RuleAnalysis

        mem = analyze_memories([str(memory_dir)], stale_days=30)
        rules = RuleAnalysis()  # 空的 rule 分析

        proposals = generate_proposals(mem, rules, max_proposals=3)
        archive_proposals = [p for p in proposals if p.proposal_type == ProposalType.MEMORY_ARCHIVE]
        assert len(archive_proposals) >= 1

    def test_no_proposals_when_healthy(self):
        from tools.self_evolution.memory_analyzer import MemoryAnalysis
        from tools.self_evolution.proposal_generator import generate_proposals
        from tools.self_evolution.rule_analyzer import RuleAnalysis

        mem = MemoryAnalysis()
        rules = RuleAnalysis()
        proposals = generate_proposals(mem, rules)
        assert len(proposals) == 0


# ---------------------------------------------------------------------------
# Evolution Report Tests
# ---------------------------------------------------------------------------

class TestEvolutionReport:
    def test_report_contains_sections(self, memory_dir: Path, rules_setup):
        from tools.self_evolution.evolution_report import generate_report
        from tools.self_evolution.memory_analyzer import analyze_memories
        from tools.self_evolution.proposal_generator import generate_proposals
        from tools.self_evolution.rule_analyzer import analyze_rules

        global_md, rules_dir, _ = rules_setup
        mem = analyze_memories([str(memory_dir)])
        rules = analyze_rules([str(global_md)], str(rules_dir))
        proposals = generate_proposals(mem, rules)

        report = generate_report(mem, rules, proposals)
        assert "## Memory Health" in report
        assert "## Rule Health" in report
        assert "## Improvement Proposals" in report

    def test_report_wow_comparison(self, memory_dir: Path, log_file: Path):
        from tools.self_evolution.evolution_report import generate_report
        from tools.self_evolution.memory_analyzer import analyze_memories
        from tools.self_evolution.proposal_generator import generate_proposals
        from tools.self_evolution.rule_analyzer import RuleAnalysis

        mem = analyze_memories([str(memory_dir)])
        rules = RuleAnalysis()
        proposals = generate_proposals(mem, rules)

        report = generate_report(mem, rules, proposals, log_path=str(log_file))
        assert "Week-over-Week" in report


# ---------------------------------------------------------------------------
# Evolution Log Tests
# ---------------------------------------------------------------------------

class TestEvolutionLog:
    def test_log_append(self, tmp_path: Path):
        from tools.self_evolution.memory_analyzer import MemoryAnalysis
        from tools.self_evolution.proposal_generator import EvolutionProposal
        from tools.self_evolution.rule_analyzer import RuleAnalysis
        from tools.self_evolution.self_evolution import _append_log

        log = tmp_path / "test_log.json"
        log.write_text("[]")

        _append_log(
            log, "2026-04-01T00:00:00Z",
            [], MemoryAnalysis(), RuleAnalysis(),
        )
        data = json.loads(log.read_text())
        assert len(data) == 1
        assert data[0]["run_date"] == "2026-04-01T00:00:00Z"

        # 追加第二次
        _append_log(
            log, "2026-04-02T00:00:00Z",
            [], MemoryAnalysis(), RuleAnalysis(),
        )
        data = json.loads(log.read_text())
        assert len(data) == 2
