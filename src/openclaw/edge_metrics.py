"""Edge Metrics (v4 #16).

This module defines how we quantify a strategy's **edge**.

Design goals:
- Deterministic, dependency-light (no numpy/pandas).
- Accepts flexible trade record formats.
- Optional integration hook to persist edge metrics into StrategyRegistry (#28).

Edge definition (high level):
- Edge is the *expected value* of a trade distribution after costs.
- We approximate this via win-rate, average win/loss, expectancy, and profit factor.

See: docs/edge_definition.md
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Tuple


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        fv = float(v)
    except Exception:
        return default
    if not math.isfinite(fv):
        return default
    return fv


@dataclass(frozen=True)
class EdgeMetrics:
    """Summary edge metrics for a set of trades."""

    n_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    expectancy: float
    profit_factor: float
    payoff_ratio: float
    total_pnl: float
    avg_pnl: float

    # Optional return-based stats if return_pct is provided in inputs.
    avg_return_pct: float | None = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_trades": self.n_trades,
            "win_rate": self.win_rate,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "expectancy": self.expectancy,
            "profit_factor": self.profit_factor,
            "payoff_ratio": self.payoff_ratio,
            "total_pnl": self.total_pnl,
            "avg_pnl": self.avg_pnl,
            "avg_return_pct": self.avg_return_pct,
        }


def _extract_trade_pnl_and_return(trade: Any) -> Tuple[float | None, float | None]:
    """Extract (pnl, return_pct) from a flexible trade record.

    Supported shapes:
    - number: treated as pnl
    - mapping: keys may include pnl, profit, realized_pnl, net_pnl, return_pct, ret, r
    - object with attributes: same names
    """

    if isinstance(trade, (int, float)):
        return _safe_float(trade), None

    keys_pnl = ("pnl", "profit", "realized_pnl", "net_pnl")
    keys_ret = ("return_pct", "ret", "r")

    if isinstance(trade, Mapping):
        pnl = None
        for k in keys_pnl:
            if k in trade:
                pnl = _safe_float(trade.get(k))
                if pnl is not None:
                    break
        ret = None
        for k in keys_ret:
            if k in trade:
                ret = _safe_float(trade.get(k))
                if ret is not None:
                    break
        return pnl, ret

    pnl = None
    for k in keys_pnl:
        if hasattr(trade, k):
            pnl = _safe_float(getattr(trade, k))
            if pnl is not None:
                break

    ret = None
    for k in keys_ret:
        if hasattr(trade, k):
            ret = _safe_float(getattr(trade, k))
            if ret is not None:
                break

    return pnl, ret


def compute_edge_metrics(trades: Iterable[Any]) -> EdgeMetrics:
    """Compute edge metrics from trade outcomes.

    Notes:
    - Trades with missing/invalid pnl are ignored.
    - avg_loss is returned as a *positive* number (magnitude).
    - If no losses exist, profit_factor becomes +inf and payoff_ratio becomes +inf.
    """

    pnls: List[float] = []
    rets: List[float] = []
    for t in trades:
        pnl, ret = _extract_trade_pnl_and_return(t)
        if pnl is None:
            continue
        pnls.append(float(pnl))
        if ret is not None:
            rets.append(float(ret))

    n = len(pnls)
    if n == 0:
        return EdgeMetrics(
            n_trades=0,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            expectancy=0.0,
            profit_factor=0.0,
            payoff_ratio=0.0,
            total_pnl=0.0,
            avg_pnl=0.0,
            avg_return_pct=None,
        )

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss_mag = abs(sum(losses) / len(losses)) if losses else 0.0

    expectancy = win_rate * avg_win - (1.0 - win_rate) * avg_loss_mag

    total_win = sum(wins)
    total_loss_mag = abs(sum(losses))
    if total_loss_mag <= 0:
        profit_factor = float("inf") if total_win > 0 else 0.0
        payoff_ratio = float("inf") if avg_win > 0 else 0.0
    else:
        profit_factor = total_win / total_loss_mag
        payoff_ratio = avg_win / max(avg_loss_mag, 1e-12)

    total_pnl = sum(pnls)
    avg_pnl = total_pnl / n

    avg_return_pct: float | None = None
    if rets:
        avg_return_pct = sum(rets) / len(rets)

    return EdgeMetrics(
        n_trades=n,
        win_rate=float(win_rate),
        avg_win=float(avg_win),
        avg_loss=float(avg_loss_mag),
        expectancy=float(expectancy),
        profit_factor=float(profit_factor),
        payoff_ratio=float(payoff_ratio),
        total_pnl=float(total_pnl),
        avg_pnl=float(avg_pnl),
        avg_return_pct=float(avg_return_pct) if avg_return_pct is not None else None,
    )


def edge_score(metrics: EdgeMetrics, *, scale: float = 100.0) -> float:
    """Convert EdgeMetrics into a bounded score (0..scale)."""

    if metrics.n_trades <= 0:
        return 0.0

    pf = metrics.profit_factor
    if math.isinf(pf):
        pf_score = 1.0
    else:
        # pf 0.8..2.0 => 0..1
        pf_score = _clamp((pf - 0.8) / 1.2, 0.0, 1.0)

    # win-rate 40%..70% => 0..1
    wr_score = _clamp((metrics.win_rate - 0.40) / 0.30, 0.0, 1.0)

    # Expectancy normalized by avg_loss to reduce scale dependence.
    denom = max(metrics.avg_loss, 1e-9)
    exp_norm = metrics.expectancy / denom
    # -0.2..0.6 => 0..1
    exp_score = _clamp((exp_norm + 0.2) / 0.8, 0.0, 1.0)

    combined = 0.45 * pf_score + 0.35 * wr_score + 0.20 * exp_score
    return float(scale * combined)


def persist_edge_metrics_to_strategy_version(
    *,
    db_path: str,
    version_id: str,
    metrics: EdgeMetrics,
    performed_by: str = "edge_metrics",
    notes: str | None = None,
) -> bool:
    """Persist edge metrics into `strategy_versions.strategy_config_json`.

    v4 #16 requires integration with strategy version control (#28).

    Implementation:
    - Stores metrics under `strategy_config["edge_metrics"]` and `edge_score`.
    - Best-effort inserts an audit-log entry (action=`edge_metrics_updated`).
    """

    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return False

    try:
        row = conn.execute(
            "SELECT strategy_config_json FROM strategy_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            return False

        try:
            cfg = json.loads(row[0]) if row[0] else {}
        except Exception:
            cfg = {}

        cfg["edge_metrics"] = metrics.as_dict()
        cfg["edge_score"] = edge_score(metrics)

        conn.execute(
            "UPDATE strategy_versions SET strategy_config_json = ? WHERE version_id = ?",
            (json.dumps(cfg, ensure_ascii=False), version_id),
        )

        # Best-effort audit log.
        try:
            conn.execute(
                """
                INSERT INTO version_audit_log(version_id, action, performed_by, details, performed_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (
                    version_id,
                    "edge_metrics_updated",
                    performed_by,
                    json.dumps({"notes": notes or "", "edge_score": cfg.get("edge_score")}, ensure_ascii=False),
                ),
            )
        except Exception:
            pass

        conn.commit()
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
