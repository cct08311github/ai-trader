import sqlite3
import time

from openclaw.decision_pipeline_v4 import run_decision_with_sentinel
from openclaw.drawdown_guard import DrawdownPolicy
from openclaw.risk_engine import SystemState


def test_decision_pipeline_stops_when_master_switch_off(monkeypatch):
    import openclaw.decision_pipeline_v4 as mod

    monkeypatch.setattr(mod, "check_system_switch", lambda *args, **kwargs: (False, "disabled"))

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
