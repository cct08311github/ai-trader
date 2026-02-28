"""LLM + RL hybrid architecture (v4 #27).

Design goals
- LLM layer (planner) handles high-level reasoning: objective, constraints,
  parameter search space.
- RL layer (optimizer) handles low-level optimization: search/tuning within the
  planner-defined space.
- Coordinator integrates proposal_engine (#26), authority boundary (#29),
  strategy versioning (#28), and reflection loop (#25).

Safety
- The RL optimizer MUST NOT directly deploy/activate strategies.
  It can only generate proposals and draft versions.

Implementation notes
- Stable-Baselines3 is intentionally optional. The default optimizer is a
  lightweight bandit-style RL (epsilon-greedy) that is deterministic given a
  seed.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


RewardFn = Callable[[Dict[str, float]], float]


@dataclass(frozen=True)
class StrategyPlan:
    """Planner output: what to optimize and within which constraints."""

    target_rule: str
    rule_category: str
    objective: str
    parameter_space: Dict[str, Sequence[float]]
    constraints: Dict[str, Any]
    rationale: str
    confidence: float = 0.75


@dataclass(frozen=True)
class OptimizationResult:
    """Optimizer output: best parameters and training traces."""

    best_params: Dict[str, float]
    best_reward: float
    baseline_params: Dict[str, float]
    baseline_reward: float

    # Trace
    seed: int
    steps: int
    epsilon: float
    candidate_count: int
    rewards: List[float]


@dataclass(frozen=True)
class HybridRunResult:
    """Coordinator output for a single hybrid run."""

    plan: StrategyPlan
    optimization: OptimizationResult

    proposal_id: Optional[str]
    requires_human_approval: bool
    authority_level: int

    version_id: Optional[str]
    reflection_run_id: Optional[str]

    proposed_strategy: Dict[str, Any]


class LLMStrategyPlanner:
    """High-level planner.

    In production this may call an LLM. For unit tests and offline mode, it uses
    deterministic heuristics.

    The planner defines:
    - objective (what to maximize)
    - constraints (risk/guardrails)
    - parameter search space
    """

    def __init__(
        self,
        *,
        default_confidence: float = 0.78,
        default_relative_range: float = 0.25,
        default_grid_points: int = 7,
        llm_callable: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None:
        self.default_confidence = float(default_confidence)
        self.default_relative_range = float(default_relative_range)
        self.default_grid_points = int(default_grid_points)
        self._llm_callable = llm_callable

    def plan(
        self,
        *,
        market_context: Dict[str, Any],
        current_strategy: Dict[str, Any],
        target_rule: str,
        rule_category: str,
        tunable_params: Optional[Sequence[str]] = None,
        parameter_bounds: Optional[Dict[str, Tuple[float, float]]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        objective: Optional[str] = None,
        seed: int = 0,
    ) -> StrategyPlan:
        """Generate a StrategyPlan.

        Args:
            tunable_params: explicit list of parameter names to tune. If omitted,
                numeric values in current_strategy are used.
            parameter_bounds: optional bounds per parameter.
        """

        # If a real LLM callable exists, use it, but keep the output validated.
        if self._llm_callable is not None:
            payload = {
                "market_context": market_context,
                "current_strategy": current_strategy,
                "target_rule": target_rule,
                "rule_category": rule_category,
                "tunable_params": list(tunable_params) if tunable_params else None,
                "parameter_bounds": parameter_bounds,
                "constraints": constraints,
                "objective": objective,
                "seed": seed,
            }
            llm_out = self._llm_callable(payload)
            return self._normalize_llm_output(llm_out, fallback_seed=seed, target_rule=target_rule, rule_category=rule_category)

        rng = random.Random(seed)

        inferred_params: List[str]
        if tunable_params is not None:
            inferred_params = list(tunable_params)
        else:
            inferred_params = [
                k for k, v in current_strategy.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            ]

        bounds = parameter_bounds or {}

        parameter_space: Dict[str, Sequence[float]] = {}
        for name in inferred_params:
            current_val = current_strategy.get(name)
            if not isinstance(current_val, (int, float)) or isinstance(current_val, bool):
                continue

            low, high = bounds.get(name, self._default_bounds(float(current_val)))
            grid = self._linspace(low, high, self.default_grid_points)

            # Shuffle to avoid always identical order when grid symmetric; optimizer
            # is seed-driven so this remains reproducible.
            grid = list(dict.fromkeys(grid))  # unique, stable
            rng.shuffle(grid)
            parameter_space[name] = grid

        if not parameter_space:
            # Ensure at least something is tunable; use a no-op "temperature".
            parameter_space = {"_noop": [0.0]}

        merged_constraints = {
            "max_drawdown": market_context.get("max_drawdown"),
            "max_leverage": market_context.get("max_leverage"),
            "risk_budget": market_context.get("risk_budget"),
        }
        if constraints:
            merged_constraints.update(constraints)

        obj = objective or "maximize_reward"
        rationale = (
            "Heuristic planner: tune strategy parameters within bounded ranges "
            "under provided risk constraints."
        )

        return StrategyPlan(
            target_rule=target_rule,
            rule_category=rule_category,
            objective=obj,
            parameter_space=parameter_space,
            constraints=merged_constraints,
            rationale=rationale,
            confidence=self.default_confidence,
        )

    def _default_bounds(self, x: float) -> Tuple[float, float]:
        # If x is 0, use a small symmetric range.
        if x == 0.0:
            r = 0.1
            return (-r, r)

        r = abs(x) * self.default_relative_range
        return (x - r, x + r)

    @staticmethod
    def _linspace(low: float, high: float, n: int) -> List[float]:
        n = max(int(n), 2)
        if low == high:
            return [float(low)]
        step = (high - low) / (n - 1)
        return [float(low + i * step) for i in range(n)]

    def _normalize_llm_output(
        self,
        llm_out: Dict[str, Any],
        *,
        fallback_seed: int,
        target_rule: str,
        rule_category: str,
    ) -> StrategyPlan:
        """Validate/normalize LLM output to StrategyPlan."""

        try:
            ps = llm_out.get("parameter_space")
            if not isinstance(ps, dict) or not ps:
                raise ValueError("parameter_space missing")
            parameter_space: Dict[str, Sequence[float]] = {}
            for k, v in ps.items():
                if not isinstance(k, str):
                    continue
                if isinstance(v, (list, tuple)) and all(isinstance(x, (int, float)) for x in v):
                    parameter_space[k] = [float(x) for x in v]

            if not parameter_space:
                raise ValueError("parameter_space empty")

            confidence = float(llm_out.get("confidence", self.default_confidence))
            confidence = min(max(confidence, 0.0), 1.0)

            return StrategyPlan(
                target_rule=str(llm_out.get("target_rule", target_rule)),
                rule_category=str(llm_out.get("rule_category", rule_category)),
                objective=str(llm_out.get("objective", "maximize_reward")),
                parameter_space=parameter_space,
                constraints=dict(llm_out.get("constraints", {})) if isinstance(llm_out.get("constraints"), dict) else {},
                rationale=str(llm_out.get("rationale", "LLM planner")),
                confidence=confidence,
            )
        except Exception:
            # Safe fallback to heuristic plan
            return self.plan(
                market_context={},
                current_strategy={},
                target_rule=target_rule,
                rule_category=rule_category,
                seed=fallback_seed,
            )


class RLParameterOptimizer:
    """Low-level optimizer.

    Default implementation is a lightweight epsilon-greedy bandit over a finite
    candidate set.

    This is intentionally dependency-free while still being a form of RL.
    """

    def __init__(
        self,
        *,
        seed: int = 0,
        epsilon: float = 0.2,
        steps: int = 60,
        candidate_count: int = 64,
    ) -> None:
        self.seed = int(seed)
        self.epsilon = float(epsilon)
        self.steps = int(steps)
        self.candidate_count = int(candidate_count)

    def optimize(
        self,
        *,
        plan: StrategyPlan,
        reward_fn: RewardFn,
        baseline_params: Optional[Dict[str, float]] = None,
    ) -> OptimizationResult:
        rng = random.Random(self.seed)

        candidates = self._build_candidates(plan.parameter_space, rng, self.candidate_count)

        baseline_params = dict(baseline_params or {})
        baseline_numeric = {k: float(v) for k, v in baseline_params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

        # Baseline reward: evaluate on current values if possible, else on first candidate.
        if baseline_numeric and all(k in plan.parameter_space for k in plan.parameter_space.keys() if k != "_noop"):
            baseline_eval = {k: float(baseline_numeric.get(k, candidates[0].get(k, 0.0))) for k in candidates[0].keys()}
        else:
            baseline_eval = dict(candidates[0])

        baseline_reward = float(reward_fn(baseline_eval))

        # Bandit state
        q = [0.0 for _ in range(len(candidates))]
        n = [0 for _ in range(len(candidates))]

        rewards_trace: List[float] = []

        best_idx = 0
        best_reward = -math.inf

        for _step in range(self.steps):
            explore = rng.random() < self.epsilon
            if explore:
                idx = rng.randrange(len(candidates))
            else:
                idx = max(range(len(candidates)), key=lambda i: q[i])

            reward = float(reward_fn(dict(candidates[idx])))
            rewards_trace.append(reward)

            # Incremental mean update
            n[idx] += 1
            q[idx] += (reward - q[idx]) / n[idx]

            if reward > best_reward:
                best_reward = reward
                best_idx = idx

        return OptimizationResult(
            best_params=dict(candidates[best_idx]),
            best_reward=float(best_reward),
            baseline_params=baseline_eval,
            baseline_reward=float(baseline_reward),
            seed=self.seed,
            steps=self.steps,
            epsilon=self.epsilon,
            candidate_count=len(candidates),
            rewards=rewards_trace,
        )

    @staticmethod
    def _build_candidates(
        parameter_space: Dict[str, Sequence[float]],
        rng: random.Random,
        candidate_count: int,
    ) -> List[Dict[str, float]]:
        keys = sorted(parameter_space.keys())
        if not keys:
            return [{"_noop": 0.0}]

        # If the full cartesian product is small, enumerate it.
        total = 1
        for k in keys:
            total *= max(1, len(parameter_space[k]))
            if total > candidate_count * 50:
                break

        candidates: List[Dict[str, float]] = []

        if total <= candidate_count * 50:
            # Enumerate and sample
            all_candidates = [{}]
            for k in keys:
                new: List[Dict[str, float]] = []
                for base in all_candidates:
                    for v in parameter_space[k]:
                        d = dict(base)
                        d[k] = float(v)
                        new.append(d)
                all_candidates = new

            rng.shuffle(all_candidates)
            candidates = all_candidates[: max(1, min(candidate_count, len(all_candidates)))]
        else:
            # Randomly sample combinations.
            for _ in range(max(1, candidate_count)):
                d = {k: float(rng.choice(list(parameter_space[k]))) for k in keys}
                candidates.append(d)

        # De-duplicate while preserving order.
        seen = set()
        uniq: List[Dict[str, float]] = []
        for c in candidates:
            key = tuple(sorted(c.items()))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(c)

        return uniq or [{"_noop": 0.0}]


class HybridCoordinator:
    """Orchestrates LLM planner + RL optimizer and integrates v4 subsystems."""

    def __init__(
        self,
        *,
        planner: LLMStrategyPlanner,
        optimizer: RLParameterOptimizer,
        generated_by: str = "hybrid_llm_rl",
        authority_engine: Optional[Any] = None,
        strategy_registry: Optional[Any] = None,
    ) -> None:
        self.planner = planner
        self.optimizer = optimizer
        self.generated_by = generated_by
        self.authority_engine = authority_engine
        self.strategy_registry = strategy_registry

    def run(
        self,
        *,
        conn: sqlite3.Connection,
        current_strategy: Dict[str, Any],
        market_context: Dict[str, Any],
        target_rule: str,
        rule_category: str,
        reward_fn: RewardFn,
        trade_date: Optional[str] = None,
        create_version: bool = True,
        record_reflection: bool = True,
    ) -> HybridRunResult:
        """Execute a hybrid run.

        Safety: does NOT activate strategy versions.
        """

        # --- Authority gate (#29) ---
        authority_level = 2
        requires_human_approval = True
        auto_approve_flag = False

        if self.authority_engine is not None:
            if hasattr(self.authority_engine, "can_propose") and not self.authority_engine.can_propose():
                raise PermissionError("Authority level too low: cannot propose")

            if hasattr(self.authority_engine, "get_current_level"):
                authority_level = int(self.authority_engine.get_current_level().value)  # IntEnum

            if hasattr(self.authority_engine, "can_auto_approve"):
                auto_approve_flag = bool(self.authority_engine.can_auto_approve(rule_category))

        # --- Plan ---
        plan = self.planner.plan(
            market_context=market_context,
            current_strategy=current_strategy,
            target_rule=target_rule,
            rule_category=rule_category,
            seed=self.optimizer.seed,
        )

        # --- Optimize ---
        optimization = self.optimizer.optimize(
            plan=plan,
            reward_fn=reward_fn,
            baseline_params={k: v for k, v in current_strategy.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        )

        proposed_strategy = dict(current_strategy)
        for k, v in optimization.best_params.items():
            if k == "_noop":
                continue
            proposed_strategy[k] = v

        # --- Create proposal (#26) ---
        proposal_id: Optional[str] = None
        try:
            from openclaw.proposal_engine import create_proposal

            # Simple string payloads for current/proposed values
            current_value = json.dumps({k: current_strategy.get(k) for k in optimization.best_params.keys() if k != "_noop"}, ensure_ascii=False)
            proposed_value = json.dumps({k: proposed_strategy.get(k) for k in optimization.best_params.keys() if k != "_noop"}, ensure_ascii=False)
            evidence = {
                "planner_rationale": plan.rationale,
                "optimizer": {
                    "seed": optimization.seed,
                    "steps": optimization.steps,
                    "epsilon": optimization.epsilon,
                    "candidate_count": optimization.candidate_count,
                    "baseline_reward": optimization.baseline_reward,
                    "best_reward": optimization.best_reward,
                },
            }

            proposal = create_proposal(
                conn=conn,
                generated_by=self.generated_by,
                target_rule=plan.target_rule,
                rule_category=plan.rule_category,
                current_value=current_value,
                proposed_value=proposed_value,
                supporting_evidence=json.dumps(evidence, ensure_ascii=False),
                confidence=float(plan.confidence),
                backtest_sharpe_before=float(optimization.baseline_reward),
                backtest_sharpe_after=float(optimization.best_reward),
                auto_approve=auto_approve_flag,
            )
            proposal_id = getattr(proposal, "proposal_id", None)
            requires_human_approval = bool(getattr(proposal, "requires_human_approval", True))
        except Exception:
            # Proposal subsystem may be absent in certain minimal environments.
            proposal_id = None
            requires_human_approval = True

        # --- Version registry (#28) ---
        version_id: Optional[str] = None
        if create_version and self.strategy_registry is not None and proposal_id is not None:
            try:
                version = self.strategy_registry.create_version(
                    strategy_config=proposed_strategy,
                    created_by=self.generated_by,
                    source_proposal_id=proposal_id,
                    notes="Draft generated by LLM+RL hybrid optimizer (v4 #27).",
                )
                version_id = version.get("version_id")
            except Exception:
                version_id = None

        # --- Reflection loop (#25) ---
        reflection_run_id: Optional[str] = None
        if record_reflection and trade_date is not None:
            reflection_run_id = self._record_reflection(
                conn=conn,
                trade_date=trade_date,
                plan=plan,
                optimization=optimization,
                proposal_id=proposal_id,
                version_id=version_id,
            )

        return HybridRunResult(
            plan=plan,
            optimization=optimization,
            proposal_id=proposal_id,
            requires_human_approval=requires_human_approval,
            authority_level=authority_level,
            version_id=version_id,
            reflection_run_id=reflection_run_id,
            proposed_strategy=proposed_strategy,
        )

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _record_reflection(
        self,
        *,
        conn: sqlite3.Connection,
        trade_date: str,
        plan: StrategyPlan,
        optimization: OptimizationResult,
        proposal_id: Optional[str],
        version_id: Optional[str],
    ) -> Optional[str]:
        """Best-effort record RL outcomes into reflection loop."""

        try:
            from openclaw.reflection_loop import ReflectionOutput, insert_reflection_run
        except Exception:
            return None

        if not self._table_exists(conn, "reflection_runs"):
            return None

        # reflection_loop.insert_reflection_run expects semantic_memory table to exist.
        if not self._table_exists(conn, "semantic_memory"):
            return None

        stage1 = {
            "root_cause_code": "rl_optimization",
            "issues_found": [],
            "patterns": [],
            "meta": {"proposal_id": proposal_id, "version_id": version_id},
        }

        stage2 = {
            "rule_text": plan.target_rule,
            "rule_category": plan.rule_category,
            "confidence": plan.confidence,
            "objective": plan.objective,
            "constraints": plan.constraints,
        }

        stage3 = {
            "decision": {
                "action": "proposal",
                "current_value": optimization.baseline_params,
                "proposed_value": optimization.best_params,
                "supporting_evidence": {
                    "best_reward": optimization.best_reward,
                    "baseline_reward": optimization.baseline_reward,
                    "steps": optimization.steps,
                    "epsilon": optimization.epsilon,
                },
            }
        }

        output = ReflectionOutput(stage1_diagnosis=stage1, stage2_abstraction=stage2, stage3_refinement=stage3)

        try:
            run_id = insert_reflection_run(conn, trade_date, output)
            conn.commit()
            return run_id
        except Exception:
            return None
