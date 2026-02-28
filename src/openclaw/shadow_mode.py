"""Shadow Mode deployment manager (v4 #3).

Implements gradual rollout (10% → 30% → 100%) with a 2-hour rollback window.

This module is intentionally dependency-light so it can be imported by different
pipeline entrypoints.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


def _now_s() -> int:
    """Return current time in seconds.

    Unit tests patch ``time.time()`` directly, so we keep the same unit
    (seconds) to avoid ambiguity.
    """

    return int(time.time())


class DeploymentState(enum.Enum):
    """Deployment state machine."""

    PENDING = "pending"
    ACTIVE = "active"
    FULL_DEPLOYMENT = "full_deployment"
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"


@dataclass
class DeploymentMetric:
    """Metric recorded for shadow/stable comparison."""

    decision_id: str
    metric_type: str  # "pnl", "execution_time_ms", "decision_quality", ...
    stable_value: float
    shadow_value: float
    recorded_at: int = field(default_factory=_now_s)

    @property
    def shadow_better(self) -> bool:
        """Return True if shadow performed better than stable."""

        # Higher is better for metrics like pnl, decision_quality
        # Lower is better for metrics like execution_time_ms
        if self.metric_type in ["pnl", "decision_quality"]:
            return self.shadow_value > self.stable_value
        if self.metric_type in ["execution_time_ms"]:
            return self.shadow_value < self.stable_value
        return False


@dataclass
class ShadowModeManager:
    """Manages shadow deployment of new strategy versions."""

    # Configuration
    stable_version: str
    shadow_version: str
    deployment_id: str

    # State
    state: DeploymentState = DeploymentState.PENDING
    current_phase: str = "0%"  # "0%", "10%", "30%", "100%"
    shadow_traffic_percent: float = 0.0

    # Timestamps
    created_at: int = field(default_factory=_now_s)
    started_at: Optional[int] = None
    phase_changed_at: Optional[int] = None
    rolled_back_at: Optional[int] = None

    # Metrics
    metrics: List[DeploymentMetric] = field(default_factory=list)

    # Rollback info
    rollback_reason: Optional[str] = None
    last_error: Optional[str] = None

    # Phase configuration
    _phases: Dict[str, float] = field(
        default_factory=lambda: {"10%": 0.1, "30%": 0.3, "100%": 1.0}
    )

    def start_deployment(self) -> None:
        """Start the shadow deployment (move to 10% phase)."""

        if self.state not in (DeploymentState.PENDING, DeploymentState.ACTIVE):
            self.last_error = f"cannot start deployment from state={self.state.name}"
            return

        now = _now_s()
        self.state = DeploymentState.ACTIVE
        self.started_at = self.started_at or now
        self.current_phase = "10%"
        self.shadow_traffic_percent = float(self._phases["10%"])
        self.phase_changed_at = now
        self.last_error = None

    def advance_phase(self) -> bool:
        """Advance to next phase (10% → 30% → 100%)."""

        if self.state not in (DeploymentState.ACTIVE, DeploymentState.FULL_DEPLOYMENT):
            self.last_error = f"cannot advance phase from state={self.state.name}"
            return False

        phase_order = ["10%", "30%", "100%"]
        if self.current_phase not in phase_order:
            self.last_error = f"unknown current_phase={self.current_phase!r}"
            return False

        idx = phase_order.index(self.current_phase)
        if idx == len(phase_order) - 1:
            self.state = DeploymentState.COMPLETED
            self.last_error = "already at 100%"
            return False

        next_phase = phase_order[idx + 1]
        self.current_phase = next_phase
        self.shadow_traffic_percent = float(self._phases[next_phase])
        self.phase_changed_at = _now_s()
        self.last_error = None

        if next_phase == "100%":
            self.state = DeploymentState.FULL_DEPLOYMENT

        return True

    def rollback(self, reason: str) -> bool:
        """Rollback deployment within 2-hour window.

        Rollback window is measured from ``phase_changed_at``.
        """

        if self.state not in (DeploymentState.ACTIVE, DeploymentState.FULL_DEPLOYMENT):
            self.last_error = f"cannot rollback from state={self.state.name}"
            return False

        if not self.phase_changed_at:
            self.last_error = "phase_changed_at missing"
            return False

        now = _now_s()
        window_s = 2 * 3600
        if now - int(self.phase_changed_at) > window_s:
            self.last_error = "outside rollback window"
            return False

        self.state = DeploymentState.ROLLED_BACK
        self.rollback_reason = reason
        self.rolled_back_at = now
        self.current_phase = "0%"
        self.shadow_traffic_percent = 0.0
        self.last_error = None
        return True

    def should_route_to_shadow(self, decision_id: str) -> bool:
        """Determine if this decision should be routed to shadow version.

        Uses consistent hashing so the same ``decision_id`` deterministically
        routes to shadow or stable for a given deployment.
        """

        if self.state not in (DeploymentState.ACTIVE, DeploymentState.FULL_DEPLOYMENT):
            return False

        pct = float(self.shadow_traffic_percent)
        if pct <= 0.0:
            return False
        if pct >= 1.0:
            return True

        key = f"{self.deployment_id}:{decision_id}".encode("utf-8")
        digest = hashlib.sha256(key).digest()
        bucket = int.from_bytes(digest[:4], "big") % 10_000  # 0..9999
        return bucket < int(pct * 10_000)

    def record_metric(
        self, decision_id: str, metric_type: str, stable_value: float, shadow_value: float
    ) -> None:
        """Record metric for comparison between stable and shadow."""

        self.metrics.append(
            DeploymentMetric(
                decision_id=decision_id,
                metric_type=metric_type,
                stable_value=float(stable_value),
                shadow_value=float(shadow_value),
            )
        )

    def get_metrics_summary(self) -> List[Dict[str, Any]]:
        """Get summary of recorded metrics."""

        # Preserve insertion order of first-seen metric types.
        order: List[str] = []
        grouped: Dict[str, List[DeploymentMetric]] = {}
        for m in self.metrics:
            if m.metric_type not in grouped:
                grouped[m.metric_type] = []
                order.append(m.metric_type)
            grouped[m.metric_type].append(m)

        out: List[Dict[str, Any]] = []
        for metric_type in order:
            items = grouped[metric_type]
            count = len(items)
            shadow_better_count = sum(1 for x in items if x.shadow_better)
            stable_avg = sum(x.stable_value for x in items) / count
            shadow_avg = sum(x.shadow_value for x in items) / count

            out.append(
                {
                    "metric_type": metric_type,
                    "count": count,
                    "stable_avg": stable_avg,
                    "shadow_avg": shadow_avg,
                    "avg_delta": shadow_avg - stable_avg,
                    "shadow_better_count": shadow_better_count,
                    "shadow_better_ratio": shadow_better_count / count,
                    # Compatibility: early tests expect this boolean key.
                    "shadow_better": shadow_better_count >= (count / 2),
                    "last_recorded_at": max(x.recorded_at for x in items),
                }
            )

        return out

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state to dict."""

        return {
            "stable_version": self.stable_version,
            "shadow_version": self.shadow_version,
            "deployment_id": self.deployment_id,
            "state": self.state.name,
            "current_phase": self.current_phase,
            "shadow_traffic_percent": self.shadow_traffic_percent,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "phase_changed_at": self.phase_changed_at,
            "rolled_back_at": self.rolled_back_at,
            "rollback_reason": self.rollback_reason,
            "last_error": self.last_error,
            "metrics": [
                {
                    "decision_id": m.decision_id,
                    "metric_type": m.metric_type,
                    "stable_value": m.stable_value,
                    "shadow_value": m.shadow_value,
                    "recorded_at": m.recorded_at,
                }
                for m in self.metrics
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShadowModeManager":
        """Deserialize manager from dict."""

        mgr = cls(
            stable_version=str(data["stable_version"]),
            shadow_version=str(data["shadow_version"]),
            deployment_id=str(data["deployment_id"]),
        )

        mgr.state = DeploymentState[str(data.get("state", "PENDING"))]
        mgr.current_phase = str(data.get("current_phase", "0%"))
        mgr.shadow_traffic_percent = float(data.get("shadow_traffic_percent", 0.0))

        mgr.created_at = int(data.get("created_at", mgr.created_at))
        mgr.started_at = data.get("started_at")
        mgr.phase_changed_at = data.get("phase_changed_at")
        mgr.rolled_back_at = data.get("rolled_back_at")

        mgr.rollback_reason = data.get("rollback_reason")
        mgr.last_error = data.get("last_error")

        metrics_raw = data.get("metrics", []) or []
        mgr.metrics = [
            DeploymentMetric(
                decision_id=str(m["decision_id"]),
                metric_type=str(m["metric_type"]),
                stable_value=float(m["stable_value"]),
                shadow_value=float(m["shadow_value"]),
                recorded_at=int(m.get("recorded_at", _now_s())),
            )
            for m in metrics_raw
        ]
        return mgr


# In-process singleton (tests / local runs).
_ACTIVE_MANAGER: Optional[ShadowModeManager] = None


def get_shadow_mode_manager() -> Optional[ShadowModeManager]:
    """Get active shadow mode manager (if any).

    Lookup order:
      1) In-process singleton (if set)
      2) Load from JSON file specified by env ``OPENCLAW_SHADOW_MODE_FILE``

    Production wiring can replace this with DB-backed state.
    """

    global _ACTIVE_MANAGER
    if _ACTIVE_MANAGER is not None:
        if _ACTIVE_MANAGER.state in (DeploymentState.ACTIVE, DeploymentState.FULL_DEPLOYMENT):
            return _ACTIVE_MANAGER
        return None

    path = os.environ.get("OPENCLAW_SHADOW_MODE_FILE")
    if not path:
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mgr = ShadowModeManager.from_dict(data)
        if mgr.state in (DeploymentState.ACTIVE, DeploymentState.FULL_DEPLOYMENT):
            _ACTIVE_MANAGER = mgr
            return mgr
        return None
    except FileNotFoundError:
        return None
    except Exception:
        # Fail closed.
        return None


def integrate_with_decision_pipeline(
    decision_id: str,
    stable_decision_func: Callable[[], Any],
    shadow_decision_func: Callable[[], Any],
) -> Tuple[Any, bool, Optional[Dict[str, Any]]]:
    """Helper to integrate shadow mode with a decision pipeline.

    Returns:
        (decision_result, was_shadow_used_for_output, metric_data)
    """

    mgr = get_shadow_mode_manager()

    # No deployment → stable only.
    if mgr is None:
        t0 = _now_s()
        stable_result = stable_decision_func()
        t1 = _now_s()
        return stable_result, False, {"decision_id": decision_id, "stable_latency_s": t1 - t0}

    # FULL_DEPLOYMENT → use shadow output.
    if mgr.state == DeploymentState.FULL_DEPLOYMENT and mgr.shadow_traffic_percent >= 1.0:
        t0 = _now_s()
        shadow_result = shadow_decision_func()
        t1 = _now_s()
        return shadow_result, True, {"decision_id": decision_id, "shadow_latency_s": t1 - t0}

    # ACTIVE → stable output; shadow optionally executed.
    routed = mgr.should_route_to_shadow(decision_id)

    t0 = _now_s()
    stable_result = stable_decision_func()
    t1 = _now_s()

    metric: Dict[str, Any] = {
        "decision_id": decision_id,
        "deployment_id": mgr.deployment_id,
        "stable_latency_s": t1 - t0,
        "shadow_routed": routed,
    }

    if routed:
        s0 = _now_s()
        shadow_result = shadow_decision_func()
        s1 = _now_s()
        metric["shadow_latency_s"] = s1 - s0
        metric["shadow_result"] = shadow_result

        # Record a timing metric (best-effort).
        try:
            mgr.record_metric(
                decision_id=decision_id,
                metric_type="execution_time_ms",
                stable_value=float(metric["stable_latency_s"]),
                shadow_value=float(metric["shadow_latency_s"]),
            )
        except Exception:
            pass

    return stable_result, False, metric


# CLI commands (for /shadow-deploy, /shadow-rollback, etc.)
def handle_shadow_deploy_command(args: List[str]) -> str:
    """Handle /shadow-deploy CLI command.

    Usage:
        /shadow-deploy <stable_version> <shadow_version> <deployment_id>
    """

    if len(args) < 3:
        return "Usage: /shadow-deploy <stable_version> <shadow_version> <deployment_id>"

    stable_version, shadow_version, deployment_id = args[0], args[1], args[2]
    mgr = ShadowModeManager(
        stable_version=stable_version, shadow_version=shadow_version, deployment_id=deployment_id
    )
    mgr.start_deployment()

    global _ACTIVE_MANAGER
    _ACTIVE_MANAGER = mgr

    return (
        f"Shadow deployment started: id={deployment_id} stable={stable_version} "
        f"shadow={shadow_version} phase={mgr.current_phase} traffic={mgr.shadow_traffic_percent:.0%}"
    )


def handle_shadow_rollback_command(args: List[str]) -> str:
    """Handle /shadow-rollback CLI command.

    Usage:
        /shadow-rollback <reason...>
    """

    mgr = get_shadow_mode_manager()
    if mgr is None:
        return "No active shadow deployment."

    reason = " ".join(args).strip() or "manual rollback"
    ok = mgr.rollback(reason=reason)
    if ok:
        return f"Rolled back deployment {mgr.deployment_id}: reason={reason}"
    return f"Rollback failed for {mgr.deployment_id}: {mgr.last_error or 'unknown error'}"


if __name__ == "__main__":
    print("Shadow Mode Manager (v4 #3)")
    print("This module implements gradual rollout with rollback capability.")
