from __future__ import annotations

import time
import json
import sqlite3
import psutil
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.db import DB_PATH, READONLY_POOL
import app.db as db

router = APIRouter(prefix="/api/system", tags=["System"])
inventory_router = APIRouter(prefix="/api/inventory", tags=["Inventory"])
capital_router = APIRouter(prefix="/api/capital", tags=["Capital"])


class QuarantineClearRequest(BaseModel):
    symbols: list[str] = []


@router.get("/health")
def system_health():
    """System health check with detailed status."""
    start_time = time.time()
    
    # Services status
    services = {}
    
    # FastAPI status
    services["fastapi"] = {"status": "online", "latency_ms": 12}
    
    # Shioaji status (simplified)
    services["shioaji"] = {"status": "simulation", "latency_ms": None}
    
    # SQLite status
    sqlite_latency = None
    try:
        with READONLY_POOL.conn() as conn:
            start = time.time()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            sqlite_latency = round((time.time() - start) * 1000, 2)
            services["sqlite"] = {"status": "online", "latency_ms": sqlite_latency}
    except Exception as e:
        services["sqlite"] = {"status": "offline", "latency_ms": None, "error": str(e)}
    
    # Sentinel status (simplified)
    services["sentinel"] = {
        "last_heartbeat": datetime.now().isoformat(),
        "today_circuit_breaks": 0
    }
    
    # System resources
    resources = {}
    try:
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        dsk = psutil.disk_usage('/')
        
        resources["cpu_percent"] = cpu_pct
        resources["memory_percent"] = mem.percent
        resources["disk_used_gb"] = round(dsk.used / (1024**3), 1)
        resources["disk_total_gb"] = round(dsk.total / (1024**3), 1)
    except Exception as e:
        # Fallback values if psutil fails (logging the error can help debug)
        resources["cpu_percent"] = 0.0
        resources["memory_percent"] = 0.0
        resources["disk_used_gb"] = 0.0
        resources["disk_total_gb"] = 0.0
        resources["error"] = str(e)
    
    # Database health (simplified)
    db_health = {}
    try:
        # Check WAL size (simplified)
        db_health["wal_size_bytes"] = 1048576  # Placeholder
        db_health["write_latency_p99_ms"] = 15  # Placeholder
        db_health["last_checkpoint"] = datetime.now().isoformat()
    except Exception:  # pragma: no cover
        db_health["wal_size_bytes"] = 0  # pragma: no cover
        db_health["write_latency_p99_ms"] = 0  # pragma: no cover
        db_health["last_checkpoint"] = None  # pragma: no cover
    
    return {
        "services": services,
        "resources": resources,
        "db_health": db_health,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/ops-summary")
def ops_summary():
    from openclaw.ops_health import collect_ops_health_summary

    with READONLY_POOL.conn() as conn:
        data = collect_ops_health_summary(conn)
    return data


@router.get("/reconciliation/latest")
def latest_reconciliation():
    with READONLY_POOL.conn() as conn:
        try:
            row = conn.execute(
                """
                SELECT report_id, created_at, mismatch_count, summary_json
                  FROM reconciliation_reports
              ORDER BY created_at DESC
                 LIMIT 1
                """
            ).fetchone()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    if row is None:
        return {"available": False}
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except Exception:
        summary = {}
    return {
        "available": True,
        "report_id": row["report_id"],
        "created_at": row["created_at"],
        "mismatch_count": row["mismatch_count"],
        "summary": summary,
    }


@router.get("/quarantine-status")
def quarantine_status():
    from openclaw.position_quarantine import get_quarantine_status

    with READONLY_POOL.conn() as conn:
        data = get_quarantine_status(conn)
    return data


@router.get("/remediation-history")
def remediation_history(limit: int = 20):
    from openclaw.operator_remediation import list_operator_remediations

    with READONLY_POOL.conn() as conn:
        data = list_operator_remediations(conn, limit=limit)
    return data


def _load_latest_reconciliation_report(conn: sqlite3.Connection) -> dict:
    try:
        row = conn.execute(
            """
            SELECT summary_json
              FROM reconciliation_reports
          ORDER BY created_at DESC
             LIMIT 1
            """
        ).fetchone()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if row is None:
        raise HTTPException(status_code=404, detail="No reconciliation report available")
    try:
        payload = json.loads(row[0] or "{}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Invalid reconciliation report JSON: {e}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Invalid reconciliation report payload")
    return payload


@router.get("/quarantine-plan")
def quarantine_plan():
    from openclaw.position_quarantine import build_reconciliation_quarantine_plan, get_quarantine_status

    with READONLY_POOL.conn() as conn:
        report = _load_latest_reconciliation_report(conn)
        plan = build_reconciliation_quarantine_plan(conn, report=report)
        plan["quarantine_status"] = get_quarantine_status(conn)
    return plan


@router.post("/quarantine/apply")
def apply_quarantine():
    from openclaw.position_quarantine import apply_quarantine_plan, build_reconciliation_quarantine_plan, get_quarantine_status

    with db.get_conn_rw() as conn:
        report = _load_latest_reconciliation_report(conn)
        plan = build_reconciliation_quarantine_plan(conn, report=report)
        result = apply_quarantine_plan(conn, plan=plan, auto_commit=False)
        result["quarantine_status"] = get_quarantine_status(conn)
        return result


@router.post("/quarantine/clear")
def clear_quarantine(req: QuarantineClearRequest):
    from openclaw.position_quarantine import clear_quarantine_symbols, get_quarantine_status

    with db.get_conn_rw() as conn:
        result = clear_quarantine_symbols(conn, symbols=req.symbols, auto_commit=False)
        result["quarantine_status"] = get_quarantine_status(conn)
        return result


@router.get("/quota")
def system_quota():
    """API quota usage calculated from llm_traces and openclaw.json costs."""
    from app.core.config import get_settings
    import json
    import os

    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ts_start = int(month_start.timestamp())

    # Load pricing from llm_observability_v1.json (configurable, not hardcoded)
    _obs_path = os.path.join(os.path.dirname(__file__), "../../../../config/llm_observability_v1.json")
    _DEFAULT_COSTS = {"in": 1.0, "out": 3.0}
    usd_to_twd = 32.5
    model_costs: dict = {}
    try:
        with open(_obs_path, "r") as _f:
            _obs = json.load(_f)
        _pricing = _obs.get("model_pricing_usd_per_1m_tokens", {})
        usd_to_twd = float(_pricing.get("usd_to_twd_rate", 32.5))
        model_costs = {k: v for k, v in _pricing.items()
                       if k not in ("_comment", "usd_to_twd_rate") and isinstance(v, dict)}
    except Exception:
        pass  # fall through to _DEFAULT_COSTS below

    used_usd = 0.0
    with READONLY_POOL.conn() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT model, SUM(prompt_tokens) as pt, SUM(completion_tokens) as ct "
            "FROM llm_traces WHERE created_at >= ? GROUP BY model",
            (ts_start,)
        )
        rows = cursor.fetchall()
        for r in rows:
            m = r["model"] or "unknown"
            pt = r["pt"] or 0
            ct = r["ct"] or 0
            cost = model_costs.get(m) or model_costs.get("_default") or _DEFAULT_COSTS
            used_usd += (pt * cost["in"] + ct * cost["out"]) / 1_000_000

    used_twd = used_usd * usd_to_twd
    
    # Read dynamic budget from capital settings
    import os, json
    cap_path = os.path.join(os.path.dirname(__file__), "../../../../config/capital.json")
    try:
        with open(cap_path, 'r') as f:
            cap_data = json.load(f)
            budget_twd = float(cap_data.get("monthly_api_budget_twd", 1000.0))
    except Exception:
        budget_twd = 1000.0

    return {
        "month": month_start.strftime("%Y-%m"),
        "budget_twd": budget_twd,
        "used_twd": round(used_twd, 2),
        "used_percent": round((used_twd / budget_twd) * 100, 1) if budget_twd > 0 else 0,
        "status": "ok",
        "daily_trend": [] # Placeholder for now
    }


@router.get("/risk")
def system_risk():
    """Risk management status based on real trades pnl."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    today_str   = now.strftime("%Y-%m-%d")
    month_str   = now.strftime("%Y-%m")

    today_pnl   = 0.0
    monthly_pnl = 0.0
    try:
        from openclaw.pnl_engine import get_today_pnl, get_monthly_pnl
        with READONLY_POOL.conn() as conn:
            today_pnl   = get_today_pnl(conn, today_str)
            monthly_pnl = get_monthly_pnl(conn, month_str)
    except Exception:
        pass

    return {
        "today_realized_pnl": round(today_pnl, 2),
        "monthly_realized_pnl": round(monthly_pnl, 2),
        "monthly_drawdown_limit_pct": 0.15,
        "risk_mode": "normal" if today_pnl >= -5000 else "defensive"
    }


@router.get("/events")
def system_events():
    """System events timeline."""
    # Simplified implementation
    return {
        "events": [
            {
                "ts": datetime.now().isoformat(),
                "severity": "info",
                "source": "sentinel",
                "code": "SENTINEL_OK",
                "detail": "System monitoring operational"
            }
        ]
    }


# ─── /api/inventory ────────────────────────────────────────────────────────────

@inventory_router.get("")
def get_inventory():
    """Return current stock holdings from positions table (ticker_watcher source of truth)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT symbol, quantity, avg_price, current_price, chip_health_score, sector "
            "FROM positions WHERE quantity > 0 ORDER BY symbol"
        ).fetchall()
        conn.close()
        inventory = []
        for r in rows:
            qty = int(r["quantity"] or 0)
            avg_price = float(r["avg_price"] or 0)
            last_price = float(r["current_price"]) if r["current_price"] else avg_price
            inventory.append({
                "id": r["symbol"],
                "code": r["symbol"],
                "name": r["symbol"],
                "quantity": qty,
                "unitCost": avg_price,
                "currentValue": round(qty * last_price, 2),
                "status": "正常" if qty > 0 else "缺貨",
                "chip_health_score": r["chip_health_score"],
                "sector": r["sector"],
            })
        return inventory
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── /api/capital ──────────────────────────────────────────────────────────────

import json, os as _os

_CAPITAL_FILE = _os.path.join(_os.path.dirname(__file__), "../../../../config/capital.json")

class CapitalSettings(BaseModel):
    total_capital_twd: float  # 總可操作資金 (TWD)
    max_single_position_pct: float = 0.10  # 單一持倉上限 (%)
    daily_loss_limit_twd: float = 5000.0   # 每日最大虧損上限 (TWD)
    monthly_loss_limit_twd: float = 30000.0 # 每月最大虧損上限 (TWD)


def _load_capital() -> dict:
    try:
        with open(_CAPITAL_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "total_capital_twd": 500000.0,
            "max_single_position_pct": 0.10,
            "daily_loss_limit_twd": 5000.0,
            "monthly_loss_limit_twd": 30000.0
        }


def _save_capital(data: dict):
    _os.makedirs(_os.path.dirname(_CAPITAL_FILE), exist_ok=True)
    with open(_CAPITAL_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@capital_router.get("")
def get_capital():
    """Get current capital settings."""
    cfg = _load_capital()
    total = cfg.get("total_capital_twd", 500000.0)
    max_pct = cfg.get("max_single_position_pct", 0.10)
    return {
        **cfg,
        "max_single_position_twd": round(total * max_pct, 0),
        "note": "total_capital_twd 為可操作資金總額，系統依此計算各項比例上限"
    }


@capital_router.put("")
def update_capital(req: CapitalSettings):
    """Update capital settings."""
    data = req.model_dump()
    _save_capital(data)
    return {"status": "ok", "message": "資金設定已更新", **data}
