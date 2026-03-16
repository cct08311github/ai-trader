from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_STATE_PATH = Path(__file__).resolve().parents[2] / "config" / "system_state.json"


def default_system_state_path() -> str:
    return str(_DEFAULT_STATE_PATH)


def read_system_state(path: str | None = None) -> dict[str, Any]:
    target = path or default_system_state_path()
    try:
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug("Config file not found: %s, using defaults", target)
        return {
            "system_name": "AI-Trader v1.0",
            "version": "1.0.0",
            "description": "系統主開關與執行狀態配置 (自動生成)",
            "trading_enabled": False,
            "simulation_mode": True,
            "last_modified": dt.datetime.now().isoformat(),
            "last_modified_by": "bootstrap",
            "notes": "此為安全預設值。trading_enabled 必須為 true 且無 .EMERGENCY_STOP",
        }
    except json.JSONDecodeError as e:
        logger.warning("Corrupted config file: %s — %s", target, e)
        return {
            "system_name": "AI-Trader v1.0",
            "version": "1.0.0",
            "description": "系統主開關與執行狀態配置 (自動生成)",
            "trading_enabled": False,
            "simulation_mode": True,
            "last_modified": dt.datetime.now().isoformat(),
            "last_modified_by": "bootstrap",
            "notes": "此為安全預設值。trading_enabled 必須為 true 且無 .EMERGENCY_STOP",
        }
    except PermissionError:
        logger.error("Permission denied reading: %s", target)
        return {
            "system_name": "AI-Trader v1.0",
            "version": "1.0.0",
            "description": "系統主開關與執行狀態配置 (自動生成)",
            "trading_enabled": False,
            "simulation_mode": True,
            "last_modified": dt.datetime.now().isoformat(),
            "last_modified_by": "bootstrap",
            "notes": "此為安全預設值。trading_enabled 必須為 true 且無 .EMERGENCY_STOP",
        }
    except Exception as e:
        logger.warning("Unexpected error reading %s: %s", target, e)
        return {
            "system_name": "AI-Trader v1.0",
            "version": "1.0.0",
            "description": "系統主開關與執行狀態配置 (自動生成)",
            "trading_enabled": False,
            "simulation_mode": True,
            "last_modified": dt.datetime.now().isoformat(),
            "last_modified_by": "bootstrap",
            "notes": "此為安全預設值。trading_enabled 必須為 true 且無 .EMERGENCY_STOP",
        }


def write_system_state(state: dict[str, Any], path: str | None = None) -> dict[str, Any]:
    target = Path(path or default_system_state_path())
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return state


def clear_auto_lock_fields(state: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "auto_lock_active",
        "auto_lock_source",
        "auto_lock_reason_code",
        "auto_lock_reason",
        "auto_lock_report_id",
        "auto_lock_at",
    ):
        state.pop(key, None)
    return state


def update_system_state(
    *,
    path: str | None = None,
    modified_by: str,
    updates: dict[str, Any] | None = None,
    clear_auto_lock: bool = False,
) -> dict[str, Any]:
    state = read_system_state(path)
    if clear_auto_lock:
        clear_auto_lock_fields(state)
    if updates:
        state.update(updates)
    state["last_modified"] = dt.datetime.now().isoformat()
    state["last_modified_by"] = modified_by
    return write_system_state(state, path)


def apply_reconciliation_auto_lock(
    *,
    report: dict[str, Any],
    path: str | None = None,
    modified_by: str = "system (reconciliation auto lock)",
) -> dict[str, Any] | None:
    diagnostics = report.get("diagnostics") or {}
    if not diagnostics.get("suspected_mode_or_account_mismatch"):
        return None
    notes = diagnostics.get("notes") or []
    reason = str(notes[0]) if notes else "Broker reconciliation detected a mode or account mismatch."
    return update_system_state(
        path=path,
        modified_by=modified_by,
        updates={
            "trading_enabled": False,
            "auto_lock_active": True,
            "auto_lock_source": "broker_reconciliation",
            "auto_lock_reason_code": "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED",
            "auto_lock_reason": reason,
            "auto_lock_report_id": report.get("report_id"),
            "auto_lock_at": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
        },
    )


def system_state_path_from_env() -> str:
    return os.environ.get("SYSTEM_STATE_PATH") or default_system_state_path()
