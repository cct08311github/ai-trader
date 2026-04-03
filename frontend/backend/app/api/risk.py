"""
Risk API — concentration, correlation, drawdown, VaR, stop-loss, stress test.

Endpoints
---------
GET /api/risk/snapshot    — positions weights, sector allocation, correlation (sector-level),
                            max drawdown from daily_nav, VaR 95%, stop-loss status per position
GET /api/risk/stress-test — P&L impact under 5 macro scenarios

Cache: 300 s (5 min) for both endpoints.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from typing import Any, Dict, List

import os

from fastapi import APIRouter, Depends, Header, HTTPException

from app.core.cache import cached
from app.db import get_conn


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def verify_token(authorization: str = Header(default=None)) -> None:
    """Verify Bearer token from Authorization header.

    Disabled when AUTH_TOKEN env var is unset or empty (dev / local mode).
    """
    expected = os.environ.get("AUTH_TOKEN", "")
    if not expected:
        return  # auth disabled — no token configured
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")
    if authorization[7:] != expected:
        raise HTTPException(status_code=403, detail="Invalid token")

router = APIRouter(prefix="/api/risk", tags=["risk"])

_CAPITAL_FILE = os.path.join(
    os.path.dirname(__file__), "../../../../config/capital.json"
)

# ---------------------------------------------------------------------------
# Sector → macro sensitivity map
# Each value is a tuple: (fx_twd_5pct, us10y_100bp, memory_chip_30pct, vix40, sox_15pct)
# representing the approximate beta/sensitivity of that sector to each scenario.
# ---------------------------------------------------------------------------
_SECTOR_SENSITIVITY: Dict[str, Dict[str, float]] = {
    "半導體": {"fx": -0.05, "rates": -0.08, "memory": -0.30, "vix": -0.12, "sox": -0.15},
    "記憶體": {"fx": -0.04, "rates": -0.06, "memory": -0.50, "vix": -0.15, "sox": -0.18},
    "電子零組件": {"fx": -0.03, "rates": -0.05, "memory": -0.10, "vix": -0.10, "sox": -0.12},
    "科技": {"fx": -0.04, "rates": -0.07, "memory": -0.08, "vix": -0.12, "sox": -0.13},
    "金融": {"fx": 0.02, "rates": 0.05, "memory": 0.00, "vix": -0.08, "sox": -0.03},
    "傳產": {"fx": -0.02, "rates": -0.03, "memory": 0.00, "vix": -0.07, "sox": -0.02},
    "航運": {"fx": -0.06, "rates": -0.04, "memory": 0.00, "vix": -0.09, "sox": -0.02},
    "生技": {"fx": -0.01, "rates": -0.02, "memory": 0.00, "vix": -0.06, "sox": -0.01},
    "其他": {"fx": -0.02, "rates": -0.03, "memory": -0.02, "vix": -0.08, "sox": -0.04},
}

_DEFAULT_SENSITIVITY = {"fx": -0.03, "rates": -0.04, "memory": -0.05, "vix": -0.09, "sox": -0.05}

_SECTOR_CORRELATION: Dict[str, Dict[str, float]] = {
    "半導體": {"半導體": 1.00, "記憶體": 0.82, "電子零組件": 0.68, "科技": 0.75, "金融": 0.22, "傳產": 0.18, "航運": 0.15, "生技": 0.10, "其他": 0.25},
    "記憶體": {"半導體": 0.82, "記憶體": 1.00, "電子零組件": 0.70, "科技": 0.72, "金融": 0.20, "傳產": 0.16, "航運": 0.13, "生技": 0.08, "其他": 0.22},
    "電子零組件": {"半導體": 0.68, "記憶體": 0.70, "電子零組件": 1.00, "科技": 0.65, "金融": 0.25, "傳產": 0.20, "航運": 0.18, "生技": 0.12, "其他": 0.28},
    "科技": {"半導體": 0.75, "記憶體": 0.72, "電子零組件": 0.65, "科技": 1.00, "金融": 0.28, "傳產": 0.22, "航運": 0.17, "生技": 0.15, "其他": 0.30},
    "金融": {"半導體": 0.22, "記憶體": 0.20, "電子零組件": 0.25, "科技": 0.28, "金融": 1.00, "傳產": 0.45, "航運": 0.38, "生技": 0.20, "其他": 0.40},
    "傳產": {"半導體": 0.18, "記憶體": 0.16, "電子零組件": 0.20, "科技": 0.22, "金融": 0.45, "傳產": 1.00, "航運": 0.50, "生技": 0.18, "其他": 0.42},
    "航運": {"半導體": 0.15, "記憶體": 0.13, "電子零組件": 0.18, "科技": 0.17, "金融": 0.38, "傳產": 0.50, "航運": 1.00, "生技": 0.14, "其他": 0.35},
    "生技": {"半導體": 0.10, "記憶體": 0.08, "電子零組件": 0.12, "科技": 0.15, "金融": 0.20, "傳產": 0.18, "航運": 0.14, "生技": 1.00, "其他": 0.22},
    "其他": {"半導體": 0.25, "記憶體": 0.22, "電子零組件": 0.28, "科技": 0.30, "金融": 0.40, "傳產": 0.42, "航運": 0.35, "生技": 0.22, "其他": 1.00},
}


def _load_capital_twd() -> float:
    try:
        with open(_CAPITAL_FILE) as f:
            return float(json.load(f).get("total_capital_twd", 500_000.0))
    except (OSError, ValueError, KeyError):
        return 500_000.0


def _get_positions() -> List[Dict[str, Any]]:
    """Read active positions from the DB."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT p.symbol, p.quantity, p.avg_price, p.current_price, p.sector,
                       e.close AS eod_close
                  FROM positions p
                  LEFT JOIN (
                      SELECT ep.symbol, ep.close
                        FROM eod_prices ep
                        JOIN (
                            SELECT symbol, MAX(trade_date) AS trade_date
                              FROM eod_prices
                             GROUP BY symbol
                        ) latest ON ep.symbol = latest.symbol
                              AND ep.trade_date = latest.trade_date
                  ) e ON p.symbol = e.symbol
                 WHERE p.quantity > 0
                 ORDER BY p.symbol
                """
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _get_stop_loss(symbol: str, price: float, default_sl_pct: float) -> float:
    """Fetch position-specific stop-loss or compute from default pct."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT stop_loss FROM position_params WHERE UPPER(symbol)=? LIMIT 1",
                (symbol.upper(),),
            ).fetchone()
        if row and row["stop_loss"]:
            return float(row["stop_loss"])
    except sqlite3.Error:
        pass
    return round(price * (1.0 - default_sl_pct), 2)


def _get_max_drawdown() -> float:
    """Compute max drawdown from daily_nav (peak-to-trough) in percent."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT nav FROM daily_nav ORDER BY trade_date ASC"
            ).fetchall()
        navs = [float(r["nav"]) for r in rows if r["nav"] is not None]
        if not navs:
            raise ValueError("no nav data")
        peak = navs[0]
        max_dd = 0.0
        for nav in navs:
            if nav > peak:
                peak = nav
            dd = (peak - nav) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd * 100, 2)
    except (sqlite3.Error, ValueError):
        pass

    # Fallback: try daily_pnl_summary rolling_drawdown
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(COALESCE(rolling_drawdown, 0)) FROM daily_pnl_summary"
            ).fetchone()
        return round(float(row[0] or 0.0) * 100, 2) if row else 0.0
    except sqlite3.Error:
        return 0.0


@cached(ttl=300, maxsize=4)
def _snapshot_cached() -> Dict[str, Any]:
    """Compute the full risk snapshot (cached 300 s)."""
    positions = _get_positions()
    capital = _load_capital_twd()

    # ── Position values & weights ─────────────────────────────────────────
    pos_data: List[Dict[str, Any]] = []
    for p in positions:
        price = (
            float(p["current_price"]) if p["current_price"] is not None
            else (float(p["eod_close"]) if p["eod_close"] is not None else float(p["avg_price"] or 0))
        )
        notional = price * float(p["quantity"])
        pos_data.append({
            "symbol": p["symbol"],
            "qty": int(p["quantity"]),
            "price": price,
            "notional": notional,
            "sector": p.get("sector") or "其他",
        })

    total_notional = sum(pd["notional"] for pd in pos_data) or 1.0

    for pd in pos_data:
        pd["weight_pct"] = round(pd["notional"] / total_notional * 100, 2)

    # ── Sector allocation ─────────────────────────────────────────────────
    sector_map: Dict[str, float] = {}
    for pd in pos_data:
        sector_map[pd["sector"]] = sector_map.get(pd["sector"], 0.0) + pd["notional"]
    sector_allocation = [
        {
            "sector": sector,
            "notional": round(notional, 0),
            "weight_pct": round(notional / total_notional * 100, 2),
        }
        for sector, notional in sorted(sector_map.items(), key=lambda x: -x[1])
    ]

    # ── Concentration score (HHI-based, 0-100) ───────────────────────────
    weights = [pd["weight_pct"] / 100.0 for pd in pos_data]
    hhi = sum(w**2 for w in weights)  # Herfindahl-Hirschman Index (0-1)
    # Normalise: min (1/n) → 0, max (1.0) → 100
    n = len(weights) or 1
    hhi_min = 1.0 / n
    concentration_score = round((hhi - hhi_min) / (1.0 - hhi_min) * 100, 1) if n > 1 else 100.0

    # ── VaR 95% (parametric, σ = 2% daily assumed, z=1.645) ─────────────
    # Simplified: VaR = total_notional * daily_vol * z_score
    # Daily vol estimate: 2% (conservative for TW equities)
    daily_vol = 0.02
    z_95 = 1.645
    var_95_twd = round(total_notional * daily_vol * z_95, 0)
    var_95_pct = round(daily_vol * z_95 * 100, 2)

    # ── Max drawdown ─────────────────────────────────────────────────────
    max_drawdown_pct = _get_max_drawdown()

    # ── Stop-loss status per position ────────────────────────────────────
    try:
        with get_conn() as conn:
            cap_row = conn.execute(
                "SELECT value FROM system_settings WHERE key='capital' LIMIT 1"
            ).fetchone()
        cap_cfg = json.loads(cap_row["value"]) if cap_row else {}
    except (sqlite3.Error, json.JSONDecodeError, TypeError):
        cap_cfg = {}
    default_sl_pct = float(cap_cfg.get("default_stop_loss_pct", 0.05))

    stop_losses: List[Dict[str, Any]] = []
    for pd in pos_data:
        sl_price = _get_stop_loss(pd["symbol"], pd["price"], default_sl_pct)
        distance_pct = round((pd["price"] - sl_price) / pd["price"] * 100, 2) if pd["price"] > 0 else 0.0
        breached = pd["price"] <= sl_price
        stop_losses.append({
            "symbol": pd["symbol"],
            "current_price": pd["price"],
            "stop_loss_price": sl_price,
            "distance_pct": distance_pct,
            "breached": breached,
        })

    # ── Sector correlation matrix ─────────────────────────────────────────
    sectors_present = sorted({pd["sector"] for pd in pos_data})
    correlation_matrix = {
        s1: {
            s2: _SECTOR_CORRELATION.get(s1, {}).get(s2, (1.0 if s1 == s2 else 0.3))
            for s2 in sectors_present
        }
        for s1 in sectors_present
    }

    return {
        "status": "ok",
        "positions": [
            {
                "symbol": pd["symbol"],
                "notional": round(pd["notional"], 0),
                "weight_pct": pd["weight_pct"],
                "sector": pd["sector"],
            }
            for pd in pos_data
        ],
        "sector_allocation": sector_allocation,
        "correlation_matrix": {
            "sectors": sectors_present,
            "matrix": correlation_matrix,
        },
        "kpis": {
            "var_95_twd": var_95_twd,
            "var_95_pct": var_95_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "concentration_score": concentration_score,
            "total_notional": round(total_notional, 0),
            "position_count": len(pos_data),
        },
        "stop_losses": stop_losses,
    }


@cached(ttl=300, maxsize=4)
def _stress_cached() -> Dict[str, Any]:
    """Compute stress test P&L impacts (cached 300 s)."""
    positions = _get_positions()

    pos_values: List[Dict[str, Any]] = []
    for p in positions:
        price = (
            float(p["current_price"]) if p["current_price"] is not None
            else (float(p["eod_close"]) if p["eod_close"] is not None else float(p["avg_price"] or 0))
        )
        notional = price * float(p["quantity"])
        sector = p.get("sector") or "其他"
        sens = _SECTOR_SENSITIVITY.get(sector, _DEFAULT_SENSITIVITY)
        pos_values.append({"symbol": p["symbol"], "notional": notional, "sector": sector, "sens": sens})

    total_notional = sum(pv["notional"] for pv in pos_values) or 1.0

    def _compute_impact(shock_key: str) -> float:
        pnl = sum(pv["notional"] * pv["sens"].get(shock_key, -0.03) for pv in pos_values)
        return round(pnl, 0)

    def _pct(impact: float) -> float:
        return round(impact / total_notional * 100, 2)

    scenarios = [
        {
            "id": "fx_twd_5pct",
            "name": "TWD 升值 5%",
            "description": "台幣兌美元升值 5%，出口導向企業獲利受壓",
            "impact_twd": _compute_impact("fx"),
            "impact_pct": _pct(_compute_impact("fx")),
        },
        {
            "id": "us10y_100bp",
            "name": "美債殖利率 +100bp",
            "description": "10 年期美債殖利率上升 100 個基點，估值折現率上升",
            "impact_twd": _compute_impact("rates"),
            "impact_pct": _pct(_compute_impact("rates")),
        },
        {
            "id": "memory_chip_30pct",
            "name": "記憶體均價 -30%",
            "description": "DRAM/NAND 現貨均價下跌 30%，記憶體供應鏈受衝擊",
            "impact_twd": _compute_impact("memory"),
            "impact_pct": _pct(_compute_impact("memory")),
        },
        {
            "id": "vix_spike_40",
            "name": "VIX 飆升至 40",
            "description": "市場恐慌情緒急升，流動性縮減，全面性拋售",
            "impact_twd": _compute_impact("vix"),
            "impact_pct": _pct(_compute_impact("vix")),
        },
        {
            "id": "sox_drop_15pct",
            "name": "SOX 指數 -15%",
            "description": "費城半導體指數單月下跌 15%，科技股同步走弱",
            "impact_twd": _compute_impact("sox"),
            "impact_pct": _pct(_compute_impact("sox")),
        },
    ]

    return {
        "status": "ok",
        "total_notional": round(total_notional, 0),
        "scenarios": scenarios,
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/snapshot", dependencies=[Depends(verify_token)])
def risk_snapshot():
    """
    Return full risk snapshot:
    - positions with weights
    - sector allocation
    - sector-level correlation matrix
    - max drawdown from daily_nav
    - VaR 95% estimate (parametric)
    - stop-loss status per position
    """
    return _snapshot_cached()


@router.get("/stress-test", dependencies=[Depends(verify_token)])
def risk_stress_test():
    """
    Return estimated P&L impact under 5 macro stress scenarios.
    Sensitivity coefficients are sector-level approximations.
    """
    return _stress_cached()
