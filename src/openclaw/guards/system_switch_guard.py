"""system_switch_guard.py — Master switch guard adapter."""
from __future__ import annotations

import os

from openclaw.guards.base import Guard, GuardContext, GuardResult
from openclaw.system_switch import check_system_switch


class SystemSwitchGuard(Guard):
    """Check if the system master switch allows trading."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        system_state_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../config/system_state.json",
        )
        allowed, reason = check_system_switch(system_state_path)
        if not allowed:
            return GuardResult(
                passed=False,
                reject_code="MASTER_SWITCH_OFF",
                reason=reason or "disabled",
            )
        return GuardResult(passed=True)
