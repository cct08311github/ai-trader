import sqlite3
import time

from openclaw.decision_pipeline_v4 import run_decision_with_sentinel
from openclaw.drawdown_guard import DrawdownPolicy
from openclaw.risk_engine import SystemState


def test_decision_pipeline_stops_when_master_switch_off(monkeypatch):
    import openclaw.decision_pipeline_v4 as mod
    from openclaw.guards.base import GuardResult

    monkeypatch.setattr(mod, "check_system_switch", lambda *args, **kwargs: (False, "disabled"))
    # Monkeypatch SystemSwitchGuard.evaluate to return MASTER_SWITCH_OFF
    import openclaw.guards.system_switch_guard as ssg_mod
    monkeypatch.setattr(ssg_mod.SystemSwitchGuard, "evaluate",
        lambda self, ctx: GuardResult(passed=False, reject_code="MASTER_SWITCH_OFF", reason="disabled", metadata={"check_type": "master_switch"}))
    # budget_guard is locally imported in run_decision_with_sentinel, patch it there
    import openclaw.guards.budget_guard as bg_mod
    import openclaw.guards.drawdown_guard as dg_mod
    monkeypatch.setattr(bg_mod.BudgetGuard, "evaluate",
        lambda self, ctx: GuardResult(passed=True, reason="budget_skipped", metadata={}))
    monkeypatch.setattr(dg_mod.DrawdownGuard, "evaluate",
        lambda self, ctx: GuardResult(passed=True, reason="drawdown_skipped", metadata={}))

    conn = sqlite3.connect(":memory:")
    ok, reason_code, record = run_decision_with_sentinel(
        conn,
        system_state=SystemState(
            now_ms=int(time.time() * 1000),
            trading_locked=False,
            broker_connected=True,
            db_write_p99_ms=10,
            orders_last_60s=0,
            reduce_only_mode=False,
        ),
        order_candidate=None,
        budget_policy_path="config/budget_policy_v1.json",
        drawdown_policy=DrawdownPolicy(),
        pm_context={},
        pm_approved=False,
        llm_call=lambda model, prompt: {},
        decision_id="dec_test_001",
    )

    assert ok is False
    assert reason_code == "MASTER_SWITCH_OFF"
    assert record is None
