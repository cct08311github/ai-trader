from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from openclaw.system_state_store import (
    read_system_state,
    update_system_state,
)

def _clear_shioaji_cache():
    """Best-effort: clear Shioaji API cache so mode switch takes effect immediately."""
    try:
        from app.services.shioaji_service import _clear_api_cache
        _clear_api_cache()
    except Exception:
        pass

router = APIRouter(prefix="/api/control", tags=["Control"])

SYSTEM_STATE_PATH = os.path.join(os.path.dirname(__file__), "../../../../config/system_state.json")

class StopTradingRequest(BaseModel):
    reason: str = "User initiated manual stop"

@router.post("/stop")
def stop_trading(req: StopTradingRequest):
    """
    Emergency stop switch.
    Creates a sentinel file that the main loop can check.
    """
    try:
        # Create a hard block file that sentinel / main loop should check
        stop_file = os.path.join(os.path.dirname(__file__), "../../../../.EMERGENCY_STOP")
        with open(stop_file, "w") as f:
            f.write(req.reason)
            
        return {"status": "ok", "message": "Trading has been halted immediately."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/resume")
def resume_trading():
    """
    Resume trading (only removes emergency stop, doesn't enable auto-trading).
    """
    try:
        stop_file = os.path.join(os.path.dirname(__file__), "../../../../.EMERGENCY_STOP")
        if os.path.exists(stop_file):
            os.remove(stop_file)
        return {"status": "ok", "message": "Emergency stop cleared. Auto-trading still requires manual enable."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/enable")
def enable_auto_trading():
    """
    Enable auto-trading (主開關 ON).
    """
    try:
        update_system_state(
            path=SYSTEM_STATE_PATH,
            modified_by="user (via API)",
            updates={"trading_enabled": True},
            clear_auto_lock=True,
        )
        return {"status": "ok", "message": "Auto-trading enabled. System will start processing signals when market is open."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/disable")
def disable_auto_trading():
    """
    Disable auto-trading (主開關 OFF).
    """
    try:
        update_system_state(
            path=SYSTEM_STATE_PATH,
            modified_by="user (via API)",
            updates={"trading_enabled": False},
        )
        return {"status": "ok", "message": "Auto-trading disabled. System will not process any new signals."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/simulation")
def switch_to_simulation():
    """
    Switch to simulation mode (模擬盤).
    """
    try:
        update_system_state(
            path=SYSTEM_STATE_PATH,
            modified_by="user (via API: simulation)",
            updates={"simulation_mode": True},
        )
        _clear_shioaji_cache()  # ← clears cached Shioaji session so next call re-logins in simulation mode
        return {"status": "ok", "message": "Switched to simulation mode (模擬盤). No real money will be traded."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/live")
def switch_to_live():
    """
    Switch to live trading mode (實際盤). WARNING: Real money will be at risk.
    Automatically disables auto-trading for safety.
    """
    try:
        update_system_state(
            path=SYSTEM_STATE_PATH,
            modified_by="user (via API: live)",
            updates={"trading_enabled": False, "simulation_mode": False},
        )

        _clear_shioaji_cache()  # ← clears cached simulation session so next call connects to live account
        return {
            "status": "ok", 
            "message": "Switched to LIVE trading mode (實際盤). WARNING: Real money at risk! Auto-trading has been disabled for safety.",
            "warning": "REAL MONEY MODE ENABLED - AUTO-TRADING DISABLED"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/status")
def get_control_status():
    """
    Get current control status (emergency stop + auto-trading enabled + simulation mode).
    """
    try:
        system_state = read_system_state(SYSTEM_STATE_PATH)
        
        stop_file = os.path.join(os.path.dirname(__file__), "../../../../.EMERGENCY_STOP")
        emergency_stop = os.path.exists(stop_file)
        emergency_reason = None
        if emergency_stop:
            with open(stop_file, "r") as f:
                emergency_reason = f.read().strip()
        
        return {
            "status": "ok",
            "emergency_stop": emergency_stop,
            "emergency_reason": emergency_reason,
            "auto_trading_enabled": system_state["trading_enabled"],
            "simulation_mode": system_state["simulation_mode"],
            "last_modified": system_state["last_modified"],
            "auto_lock_active": bool(system_state.get("auto_lock_active", False)),
            "auto_lock_source": system_state.get("auto_lock_source"),
            "auto_lock_reason_code": system_state.get("auto_lock_reason_code"),
            "auto_lock_reason": system_state.get("auto_lock_reason"),
            "auto_lock_report_id": system_state.get("auto_lock_report_id"),
            "mode_warning": "REAL MONEY AT RISK" if not system_state["simulation_mode"] else "Simulation (safe)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
