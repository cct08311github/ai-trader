"""System master switch check for auto-trading safety."""

import json
import os
from pathlib import Path
from typing import Tuple, Optional


def check_system_switch(system_state_path: str) -> Tuple[bool, Optional[str]]:
    """
    Check if system is allowed to auto-trade.
    
    Returns: (allowed, reason_if_not_allowed)
    """
    # Check emergency stop file
    project_root = Path(__file__).resolve().parents[2]
    emergency_stop_file = project_root / ".EMERGENCY_STOP"
    if emergency_stop_file.exists():
        try:
            reason = emergency_stop_file.read_text(encoding="utf-8").strip()
            return False, f"EMERGENCY_STOP: {reason}"
        except Exception:
            return False, "EMERGENCY_STOP file exists"
    
    # Check system state config
    try:
        with open(system_state_path, "r") as f:
            data = json.load(f)
        
        trading_enabled = data.get("trading_enabled", False)
        if not trading_enabled:
            return False, "Auto-trading is disabled (master switch OFF)"
        
        return True, None
    except FileNotFoundError:
        # If config file doesn't exist, default to disabled
        return False, "System state config not found (default: disabled)"
    except Exception as e:
        return False, f"Error reading system state: {str(e)}"


def is_auto_trading_allowed() -> bool:
    """Convenience function for quick check."""
    system_state_path = os.path.join(os.path.dirname(__file__), "../../config/system_state.json")
    allowed, _ = check_system_switch(system_state_path)
    return allowed
