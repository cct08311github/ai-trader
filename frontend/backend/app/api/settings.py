from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json, os, sqlite3
from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/api/settings", tags=["Settings"])

POLICY_PATH  = os.path.join(os.path.dirname(__file__), "../../../../config/sentinel_policy_v1.json")
CAPITAL_PATH = os.path.join(os.path.dirname(__file__), "../../../../config/capital.json")
DB_PATH_ENV  = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "../../../../data/sqlite/trades.db"))


def _load_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─── Capital ──────────────────────────────────────────────────────────────────

class CapitalSettings(BaseModel):
    total_capital_twd: float
    max_single_position_pct: float = 0.10
    daily_loss_limit_twd: float = 5000.0
    monthly_loss_limit_twd: float = 30000.0


@router.get("/capital")
def get_capital():
    cfg = _load_json(CAPITAL_PATH, {
        "total_capital_twd": 500000.0,
        "max_single_position_pct": 0.10,
        "daily_loss_limit_twd": 5000.0,
        "monthly_loss_limit_twd": 30000.0,
    })
    total   = float(cfg.get("total_capital_twd", 500000))
    max_pct = float(cfg.get("max_single_position_pct", 0.10))
    return {**cfg, "max_single_position_twd": round(total * max_pct, 0)}


@router.put("/capital")
def update_capital(req: CapitalSettings):
    _save_json(CAPITAL_PATH, req.model_dump())
    return {"status": "ok", **req.model_dump()}


# ─── Sentinel Policy ──────────────────────────────────────────────────────────

class SentinelSettings(BaseModel):
    budget_halt_enabled: bool = True
    drawdown_suspended_enabled: bool = True
    reduce_only_enabled: bool = True
    broker_disconnected_enabled: bool = True
    db_latency_enabled: bool = True
    max_db_write_p99_ms: int = 200
    telegram_chat_id: Optional[str] = None
    health_check_interval_seconds: int = 30


@router.get("/sentinel")
def get_sentinel():
    data = _load_json(POLICY_PATH, {})
    policy      = data.get("policy", {})
    monitoring  = data.get("monitoring", {})
    return {
        "budget_halt_enabled":           policy.get("budget_halt_enabled", True),
        "drawdown_suspended_enabled":    policy.get("drawdown_suspended_enabled", True),
        "reduce_only_enabled":           policy.get("reduce_only_enabled", True),
        "broker_disconnected_enabled":   policy.get("broker_disconnected_enabled", True),
        "db_latency_enabled":            policy.get("db_latency_enabled", True),
        "max_db_write_p99_ms":           policy.get("max_db_write_p99_ms", 200),
        "telegram_chat_id":              monitoring.get("telegram_chat_id", ""),
        "health_check_interval_seconds": monitoring.get("health_check_interval_seconds", 30),
    }


@router.put("/sentinel")
def update_sentinel(req: SentinelSettings):
    data = _load_json(POLICY_PATH, {})
    if "policy" not in data:
        data["policy"] = {}
    if "monitoring" not in data:
        data["monitoring"] = {}
    data["policy"].update({
        "budget_halt_enabled":           req.budget_halt_enabled,
        "drawdown_suspended_enabled":    req.drawdown_suspended_enabled,
        "reduce_only_enabled":           req.reduce_only_enabled,
        "broker_disconnected_enabled":   req.broker_disconnected_enabled,
        "db_latency_enabled":            req.db_latency_enabled,
        "max_db_write_p99_ms":           req.max_db_write_p99_ms,
    })
    data["monitoring"].update({
        "telegram_chat_id":              req.telegram_chat_id or "",
        "health_check_interval_seconds": req.health_check_interval_seconds,
    })
    _save_json(POLICY_PATH, data)
    return {"status": "ok", **req.model_dump()}


# ─── Position Limits (all levels) ────────────────────────────────────────────

class PositionLimits(BaseModel):
    level_1_max_risk_pct: float = 0.001
    level_1_max_position_pct: float = 0.01
    level_2_max_risk_pct: float = 0.003
    level_2_max_position_pct: float = 0.05
    level_3_max_risk_pct: float = 0.005
    level_3_max_position_pct: float = 0.10


@router.get("/position-limits")
def get_position_limits():
    data   = _load_json(POLICY_PATH, {})
    levels = data.get("position_limits", {}).get("levels", {})
    l1, l2, l3 = levels.get("1", {}), levels.get("2", {}), levels.get("3", {})
    return {
        "level_1_max_risk_pct":      l1.get("max_risk_per_trade_pct_nav", 0.001),
        "level_1_max_position_pct":  l1.get("max_position_notional_pct_nav", 0.01),
        "level_2_max_risk_pct":      l2.get("max_risk_per_trade_pct_nav", 0.003),
        "level_2_max_position_pct":  l2.get("max_position_notional_pct_nav", 0.05),
        "level_3_max_risk_pct":      l3.get("max_risk_per_trade_pct_nav", 0.005),
        "level_3_max_position_pct":  l3.get("max_position_notional_pct_nav", 0.10),
    }


@router.put("/position-limits")
def update_position_limits(req: PositionLimits):
    data = _load_json(POLICY_PATH, {})
    if "position_limits" not in data:
        data["position_limits"] = {"levels": {}}
    data["position_limits"]["levels"].update({
        "1": {"max_risk_per_trade_pct_nav": req.level_1_max_risk_pct, "max_position_notional_pct_nav": req.level_1_max_position_pct},
        "2": {"max_risk_per_trade_pct_nav": req.level_2_max_risk_pct, "max_position_notional_pct_nav": req.level_2_max_position_pct},
        "3": {"max_risk_per_trade_pct_nav": req.level_3_max_risk_pct, "max_position_notional_pct_nav": req.level_3_max_position_pct},
    })
    _save_json(POLICY_PATH, data)
    return {"status": "ok", **req.model_dump()}


# ─── Authority Level ──────────────────────────────────────────────────────────

class AuthorityLevelRequest(BaseModel):
    level: int
    reason: str


@router.get("/authority")
def get_authority():
    try:
        con = sqlite3.connect(DB_PATH_ENV)
        row = con.execute("SELECT level, changed_by, reason, effective_from FROM authority_policy ORDER BY id DESC LIMIT 1").fetchone()
        con.close()
        if row:
            return {"level": row[0], "changed_by": row[1], "reason": row[2], "effective_from": row[3]}
        return {"level": 0, "changed_by": "system", "reason": "default", "effective_from": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/authority")
def update_authority(req: AuthorityLevelRequest):
    if req.level not in (0, 1, 2, 3):
        raise HTTPException(status_code=400, detail="level 必須為 0-3")
    try:
        con = sqlite3.connect(DB_PATH_ENV)
        now = datetime.utcnow().isoformat()
        con.execute(
            "INSERT INTO authority_policy (level, changed_by, reason, effective_from, updated_at) VALUES (?, ?, ?, ?, ?)",
            (req.level, "user (via UI)", req.reason, now, now)
        )
        con.commit()
        con.close()
        return {"status": "ok", "level": req.level, "reason": req.reason, "effective_from": now}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Legacy: position limits update (kept for compat) ─────────────────────────

class BudgetUpdateRequest(BaseModel):
    max_position_notional_pct_nav: float


@router.get("/limits")
def get_limits():
    data   = _load_json(POLICY_PATH, {})
    levels = data.get("position_limits", {}).get("levels", {})
    return {"status": "ok", "level_3": levels.get("3", {})}


@router.post("/limits")
def update_limits(req: BudgetUpdateRequest):
    data = _load_json(POLICY_PATH, {})
    if "position_limits" not in data:
        data["position_limits"] = {"levels": {}}
    if "3" in data["position_limits"]["levels"]:
        data["position_limits"]["levels"]["3"]["max_position_notional_pct_nav"] = req.max_position_notional_pct_nav
    _save_json(POLICY_PATH, data)
    return {"status": "ok", "message": "Limits updated successfully"}
