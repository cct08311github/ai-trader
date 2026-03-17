"""System master switch check for auto-trading safety."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from openclaw.path_utils import get_repo_root


DEFAULT_CONTROL_STATUS_URL = "http://127.0.0.1:8000/api/control/status"


def _read_trading_enabled_from_api(
    api_url: str,
    *,
    timeout_s: float = 1.0,
) -> Tuple[Optional[bool], Optional[str]]:
    """Read trading_enabled from control panel API.

    Returns: (trading_enabled_or_none, error_or_none)
    """

    try:
        req = Request(api_url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None, "Control API returned non-object JSON"
        return bool(data.get("trading_enabled", False)), None
    except (HTTPError, URLError) as e:
        return None, f"Control API request failed: {e}"
    except Exception as e:
        return None, f"Control API error: {e}"


def check_system_switch(
    system_state_path: str,
    *,
    api_url: Optional[str] = None,
    api_timeout_s: float = 1.0,
) -> Tuple[bool, Optional[str]]:
    """Check if system is allowed to auto-trade.

    Source priority:
    1) .EMERGENCY_STOP file (hard stop)
    2) config/system_state.json (local state)
    3) GET /api/control/status (fallback)

    Safety-first principle:
    - If reading state fails, default to disabled.

    Returns: (allowed, reason_if_not_allowed)
    """

    # Check emergency stop file
    _root_override = os.environ.get("_OPENCLAW_PROJECT_ROOT")
    project_root = Path(_root_override) if _root_override else get_repo_root()
    emergency_stop_file = project_root / ".EMERGENCY_STOP"
    if emergency_stop_file.exists():
        try:
            reason = emergency_stop_file.read_text(encoding="utf-8").strip()
            return False, f"EMERGENCY_STOP: {reason}"
        except Exception:
            return False, "EMERGENCY_STOP file exists"

    # Check system state config (primary)
    try:
        with open(system_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if bool(data.get("auto_lock_active", False)):
            source = str(data.get("auto_lock_source") or "system")
            code = str(data.get("auto_lock_reason_code") or "AUTO_LOCK")
            reason = str(data.get("auto_lock_reason") or "Auto lock is active.")
            return False, f"{source}:{code}: {reason}"

        trading_enabled = bool(data.get("trading_enabled", False))
        if not trading_enabled:
            return False, "Auto-trading is disabled (master switch OFF)"

        return True, None
    except FileNotFoundError:
        # Fallback to API
        pass
    except Exception as e:
        # Fallback to API, but include file error for audit
        file_error = f"Error reading system state: {str(e)}"
        api_url2 = api_url or os.getenv("CONTROL_STATUS_URL") or DEFAULT_CONTROL_STATUS_URL
        v, api_err = _read_trading_enabled_from_api(api_url2, timeout_s=api_timeout_s)
        if v is None:
            return False, f"{file_error}; fallback failed: {api_err}"
        if not v:
            return False, "Auto-trading is disabled (master switch OFF)"
        return True, None

    # File not found: try API fallback
    api_url2 = api_url or os.getenv("CONTROL_STATUS_URL") or DEFAULT_CONTROL_STATUS_URL
    v, api_err = _read_trading_enabled_from_api(api_url2, timeout_s=api_timeout_s)
    if v is None:
        return False, "System state config not found and control API unavailable (default: disabled)"
    if not v:
        return False, "Auto-trading is disabled (master switch OFF)"
    return True, None


def is_auto_trading_allowed() -> bool:
    """Convenience function for quick check."""

    system_state_path = os.path.join(os.path.dirname(__file__), "../../config/system_state.json")
    allowed, _ = check_system_switch(system_state_path)
    return allowed
