"""Test LLM + RL hybrid architecture (v4 #27)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest


def test_llm_strategy_planner_generates_plan():
    from openclaw.rl.hybrid_architecture import LLMStrategyPlanner

    planner = LLMStrategyPlanner(default_grid_points=5, default_relative_range=0.2)

    plan = planner.plan(
        market_context={"max_drawdown": 0.1, "risk_budget": 0.02},
        current_strategy={"buy_threshold": 0.02, "sell_threshold": 0.015, "name": "v1"},
        target_rule="entry_parameters",
        rule_category="entry_parameters",
        seed=42,
    )

    assert plan.target_rule == "entry_parameters"
    assert plan.rule_category == "entry_parameters"
    assert isinstance(plan.parameter_space, dict)
    assert "buy_threshold" in plan.parameter_space
    assert "sell_threshold" in plan.parameter_space
    assert len(plan.parameter_space["buy_threshold"]) >= 3
    assert plan.constraints["max_drawdown"] == 0.1


def test_rl_optimizer_reproducible():
    from openclaw.rl.hybrid_architecture import LLMStrategyPlanner, RLParameterOptimizer

    # objective: best at x=3
    def reward_fn(params: dict[str, float]) -> float:
        x = params["x"]
        return -((x - 3.0) ** 2)

    planner = LLMStrategyPlanner(default_grid_points=6, default_relative_range=1.0)
    plan = planner.plan(
        market_context={},
        current_strategy={"x": 0.0},
        target_rule="x",
        rule_category="entry_parameters",
        parameter_bounds={"x": (0.0, 5.0)},
        seed=123,
    )

    opt1 = RLParameterOptimizer(seed=7, epsilon=0.15, steps=80, candidate_count=32)
    res1 = opt1.optimize(plan=plan, reward_fn=reward_fn, baseline_params={"x": 0.0})

    opt2 = RLParameterOptimizer(seed=7, epsilon=0.15, steps=80, candidate_count=32)
    res2 = opt2.optimize(plan=plan, reward_fn=reward_fn, baseline_params={"x": 0.0})

    assert res1.best_params == res2.best_params
    assert res1.best_reward == res2.best_reward

    # Should find x close to 3
    assert abs(res1.best_params["x"] - 3.0) <= 1.0


def _create_core_tables(conn: sqlite3.Connection) -> None:
    # Proposal table (v4 #26)
    conn.execute(
        """
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at INTEGER,
            proposal_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            decided_at INTEGER,
            decided_by TEXT,
            decision_reason TEXT
        )
        """
    )

    # Reflection tables (v4 #25)
    conn.execute(
        """
        CREATE TABLE reflection_runs (
            run_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            stage1_diagnosis_json TEXT NOT NULL,
            stage2_abstraction_json TEXT NOT NULL,
            stage3_refinement_json TEXT NOT NULL,
            candidate_semantic_rules INTEGER,
            semantic_memory_size INTEGER
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE semantic_memory (
            id INTEGER PRIMARY KEY,
            status TEXT
        )
        """
    )
    conn.execute("INSERT INTO semantic_memory (status) VALUES ('active')")

    conn.commit()


def test_hybrid_coordinator_integration_creates_proposal_version_and_reflection():
    from openclaw.authority import AuthorityEngine
    from openclaw.strategy_registry import StrategyRegistry
    from openclaw.rl.hybrid_architecture import LLMStrategyPlanner, RLParameterOptimizer, HybridCoordinator

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        _create_core_tables(conn)

        authority = AuthorityEngine(db_path)
        registry = StrategyRegistry(db_path)

        planner = LLMStrategyPlanner(default_grid_points=5, default_relative_range=0.5)
        optimizer = RLParameterOptimizer(seed=11, epsilon=0.2, steps=50, candidate_count=32)
        coordinator = HybridCoordinator(
            planner=planner,
            optimizer=optimizer,
            generated_by="test_hybrid",
            authority_engine=authority,
            strategy_registry=registry,
        )

        # reward prefers buy_threshold near 0.03
        def reward_fn(params: dict[str, float]) -> float:
            bt = params.get("buy_threshold", 0.0)
            return -((bt - 0.03) ** 2)

        result = coordinator.run(
            conn=conn,
            current_strategy={"buy_threshold": 0.02, "sell_threshold": 0.015, "name": "v1"},
            market_context={"max_drawdown": 0.1},
            target_rule="entry_parameters",
            rule_category="entry_parameters",
            reward_fn=reward_fn,
            trade_date="2026-02-28",
        )

        assert result.proposal_id is not None
        assert result.version_id is not None
        assert result.reflection_run_id is not None
        assert result.requires_human_approval is True  # default authority is Level 2

        # Proposal exists
        row = conn.execute(
            "SELECT proposal_id, rule_category, current_value, proposed_value, supporting_evidence FROM strategy_proposals WHERE proposal_id = ?",
            (result.proposal_id,),
        ).fetchone()
        assert row is not None
        assert row[1] == "entry_parameters"

        current_value = json.loads(row[2])
        proposed_value = json.loads(row[3])
        evidence = json.loads(row[4])
        assert "buy_threshold" in current_value
        assert "buy_threshold" in proposed_value
        assert "optimizer" in evidence

        # Version exists as draft
        vrow = conn.execute(
            "SELECT version_id, status, source_proposal_id FROM strategy_versions WHERE version_id = ?",
            (result.version_id,),
        ).fetchone()
        assert vrow is not None
        assert vrow[1] == "draft"
        assert vrow[2] == result.proposal_id

        # Reflection run inserted
        rr = conn.execute("SELECT COUNT(*) FROM reflection_runs").fetchone()[0]
        assert rr == 1
    finally:
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_hybrid_coordinator_blocks_when_authority_too_low():
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    from openclaw.rl.hybrid_architecture import LLMStrategyPlanner, RLParameterOptimizer, HybridCoordinator

    authority = AuthorityEngine(":memory:")
    authority.get_current_level = lambda: AuthorityLevel.LEVEL_1  # type: ignore

    planner = LLMStrategyPlanner()
    optimizer = RLParameterOptimizer(seed=1)
    coordinator = HybridCoordinator(
        planner=planner,
        optimizer=optimizer,
        authority_engine=authority,
        strategy_registry=None,
        generated_by="test",
    )

    conn = sqlite3.connect(":memory:")

    def reward_fn(params: dict[str, float]) -> float:
        return 0.0

    with pytest.raises(PermissionError):
        coordinator.run(
            conn=conn,
            current_strategy={"x": 1.0},
            market_context={},
            target_rule="x",
            rule_category="entry_parameters",
            reward_fn=reward_fn,
        )

    conn.close()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
