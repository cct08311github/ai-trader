from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import os

router = APIRouter(prefix="/api/settings", tags=["Settings"])

POLICY_PATH = os.path.join(os.path.dirname(__file__), "../../../../config/sentinel_policy_v1.json")

class BudgetUpdateRequest(BaseModel):
    max_position_notional_pct_nav: float

@router.get("/limits")
def get_limits():
    """Get current position limits from sentinel policy"""
    try:
        with open(POLICY_PATH, "r") as f:
            data = json.load(f)
        levels = data.get("position_limits", {}).get("levels", {})
        # Return level 3 for demo
        return {"status": "ok", "level_3": levels.get("3", {})}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/limits")
def update_limits(req: BudgetUpdateRequest):
    """Update max position sizing via sentinel policy"""
    try:
        with open(POLICY_PATH, "r") as f:
            data = json.load(f)
            
        if "position_limits" not in data:
            data["position_limits"] = {"levels": {}}
            
        # Update level 3 auto-trading limit
        if "3" in data["position_limits"]["levels"]:
            data["position_limits"]["levels"]["3"]["max_position_notional_pct_nav"] = req.max_position_notional_pct_nav
            
        with open(POLICY_PATH, "w") as f:
            json.dump(data, f, indent=2)
            
        return {"status": "ok", "message": "Limits updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
