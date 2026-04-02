"""agents/optimization_quality_gate.py — 策略優化品質閘門

回測前後比較，確保調整確實帶來改善才允許建立 proposal。

品質門檻：
  - OOS Sharpe 改善 > 0.05
  - MDD 比值 <= 1.1（新 MDD 不可大幅惡化）
  - profit_factor >= 1.0
  - 最少 10 筆交易
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from openclaw.perf_metrics import PerfMetrics


@dataclass
class QualityGateConfig:
    """品質閘門參數（可由 optimization_policy.json 覆寫）。"""
    min_sharpe_improvement: float = 0.05
    max_mdd_ratio: float = 1.1
    min_profit_factor: float = 1.0
    min_trades: int = 10


@dataclass
class QualityGateResult:
    """品質閘門評估結果。"""
    passed: bool
    reason: str
    sharpe_before: float = 0.0
    sharpe_after: float = 0.0
    mdd_before: float = 0.0
    mdd_after: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    checks: dict = field(default_factory=dict)


def evaluate_quality_gate(
    baseline: PerfMetrics,
    candidate: PerfMetrics,
    config: Optional[QualityGateConfig] = None,
) -> QualityGateResult:
    """比較 baseline 與 candidate 回測結果，判斷是否通過品質閘門。

    Args:
        baseline:  調整前的回測指標
        candidate: 調整後的回測指標
        config:    品質閘門參數，None 時使用預設值

    Returns:
        QualityGateResult
    """
    cfg = config or QualityGateConfig()

    checks: dict = {}
    reasons: list[str] = []

    # 1. 最少交易筆數
    checks["min_trades"] = candidate.total_trades >= cfg.min_trades
    if not checks["min_trades"]:
        reasons.append(
            f"交易筆數 {candidate.total_trades} < {cfg.min_trades}"
        )

    # 2. OOS Sharpe 改善
    sharpe_diff = candidate.sharpe_ratio - baseline.sharpe_ratio
    checks["sharpe_improvement"] = sharpe_diff >= cfg.min_sharpe_improvement
    if not checks["sharpe_improvement"]:
        reasons.append(
            f"Sharpe 改善 {sharpe_diff:.4f} < {cfg.min_sharpe_improvement}"
        )

    # 3. MDD 比值
    if baseline.max_drawdown_pct > 0:
        mdd_ratio = candidate.max_drawdown_pct / baseline.max_drawdown_pct
    else:
        mdd_ratio = 1.0 if candidate.max_drawdown_pct <= 0 else 999.0
    checks["mdd_ratio"] = mdd_ratio <= cfg.max_mdd_ratio
    if not checks["mdd_ratio"]:
        reasons.append(
            f"MDD 比值 {mdd_ratio:.2f} > {cfg.max_mdd_ratio}"
        )

    # 4. profit_factor
    checks["profit_factor"] = candidate.profit_factor >= cfg.min_profit_factor
    if not checks["profit_factor"]:
        reasons.append(
            f"profit_factor {candidate.profit_factor:.2f} < {cfg.min_profit_factor}"
        )

    passed = all(checks.values())
    reason = "通過" if passed else "; ".join(reasons)

    return QualityGateResult(
        passed=passed,
        reason=reason,
        sharpe_before=baseline.sharpe_ratio,
        sharpe_after=candidate.sharpe_ratio,
        mdd_before=baseline.max_drawdown_pct,
        mdd_after=candidate.max_drawdown_pct,
        profit_factor=candidate.profit_factor,
        total_trades=candidate.total_trades,
        checks=checks,
    )
