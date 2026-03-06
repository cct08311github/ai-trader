from __future__ import annotations

import json
from pathlib import Path

from openclaw.system_state_store import (
    apply_reconciliation_auto_lock,
    clear_auto_lock_fields,
    read_system_state,
    update_system_state,
)


def make_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "trading_enabled": True,
                "simulation_mode": True,
                "last_modified": "2026-03-06T00:00:00",
                "last_modified_by": "test",
            }
        ),
        encoding="utf-8",
    )


def test_update_system_state_can_clear_auto_lock(tmp_path):
    state_path = tmp_path / "system_state.json"
    make_state(state_path)
    state = read_system_state(str(state_path))
    state["auto_lock_active"] = True
    state["auto_lock_reason"] = "x"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    updated = update_system_state(
        path=str(state_path),
        modified_by="test",
        updates={"trading_enabled": True},
        clear_auto_lock=True,
    )

    assert updated["trading_enabled"] is True
    assert "auto_lock_active" not in updated


def test_apply_reconciliation_auto_lock_disables_trading(tmp_path):
    state_path = tmp_path / "system_state.json"
    make_state(state_path)

    updated = apply_reconciliation_auto_lock(
        report={
            "report_id": "r1",
            "diagnostics": {
                "suspected_mode_or_account_mismatch": True,
                "notes": ["verify account and simulation mode"],
            },
        },
        path=str(state_path),
    )

    assert updated is not None
    assert updated["trading_enabled"] is False
    assert updated["auto_lock_active"] is True
    assert updated["auto_lock_report_id"] == "r1"


def test_apply_reconciliation_auto_lock_noop_when_not_suspected(tmp_path):
    state_path = tmp_path / "system_state.json"
    make_state(state_path)

    updated = apply_reconciliation_auto_lock(
        report={"report_id": "r1", "diagnostics": {"suspected_mode_or_account_mismatch": False}},
        path=str(state_path),
    )

    assert updated is None
    current = read_system_state(str(state_path))
    assert current["trading_enabled"] is True


def test_clear_auto_lock_fields_removes_only_lock_keys():
    state = {
        "trading_enabled": False,
        "simulation_mode": True,
        "auto_lock_active": True,
        "auto_lock_source": "broker_reconciliation",
        "auto_lock_reason_code": "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED",
        "auto_lock_reason": "verify account",
        "auto_lock_report_id": "r1",
        "auto_lock_at": "2026-03-06T00:00:00Z",
    }

    clear_auto_lock_fields(state)

    assert state == {"trading_enabled": False, "simulation_mode": True}
