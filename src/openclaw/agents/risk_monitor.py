"""agents/risk_monitor.py — 風險監控迴圈 Agent。

定時檢查 6 項風險指標，依嚴重程度 Telegram 通知並自動啟用 reduce_only。
排程：市場時段每 15 分鐘、非市場每 60 分鐘（由 agent_orchestrator 驅動）。
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from openclaw.agents.base import AgentResult, open_conn
from openclaw.path_utils import get_repo_root

log = logging.getLogger(__name__)

_REPO_ROOT = get_repo_root()
_DEFAULT_POLICY_PATH = str(_REPO_ROOT / "config" / "risk_monitor_policy.json")

# ── Severity levels ──────────────────────────────────────────────────────────

SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"
SEVERITY_EMERGENCY = "emergency"

_SEVERITY_ORDER = {
    SEVERITY_OK: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_CRITICAL: 2,
    SEVERITY_EMERGENCY: 3,
}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RiskCheckResult:
    indicator: str
    value: float
    threshold: float
    severity: str  # ok / warning / critical / emergency


@dataclass
class RiskMonitorReport:
    checks: List[RiskCheckResult]
    worst_breach: str  # severity of worst breach
    nav: float
    timestamp: int  # epoch seconds
    cash: float = 0.0
    gross_exposure: float = 0.0
    max_symbol_weight: float = 0.0
    daily_pnl_pct: float = 0.0
    drawdown_pct: float = 0.0


# ── Schema ───────────────────────────────────────────────────────────────────

_ENSURE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS risk_monitor_log (
    check_id TEXT PRIMARY KEY,
    checked_at INTEGER NOT NULL,
    nav REAL,
    cash REAL,
    gross_exposure REAL,
    max_symbol_weight REAL,
    daily_pnl_pct REAL,
    drawdown_pct REAL,
    worst_breach TEXT,
    breaches_json TEXT,
    notified INTEGER DEFAULT 0
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_ENSURE_SCHEMA_SQL)


# ── Policy loading ───────────────────────────────────────────────────────────

def _load_policy(path: str = _DEFAULT_POLICY_PATH) -> Dict[str, Any]:
    defaults = {
        "gross_exposure_limit": 1.20,
        "max_symbol_weight": 0.20,
        "daily_loss_pct_threshold": 0.05,
        "drawdown_pct_threshold": 0.15,
        "correlation_max_pair_abs_corr": 0.85,
        "correlation_max_weighted_avg_abs_corr": 0.55,
        "cash_min_pct": 0.05,
        "notification_cooldown_seconds": 3600,
    }
    try:
        raw = json.loads(Path(path).read_text())
        defaults.update({k: v for k, v in raw.items() if k in defaults})
    except Exception:
        log.debug("risk_monitor policy not found at %s, using defaults", path)
    return defaults


# ── Helper: table exists ─────────────────────────────────────────────────────

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


# ── Helper: try loading risk_store limits ─────────────────────────────────────

def _try_load_risk_store_limit(conn: sqlite3.Connection, rule_name: str) -> Optional[float]:
    """Read a global limit from risk_limits table if available."""
    if not _table_exists(conn, "risk_limits"):
        return None
    try:
        row = conn.execute(
            "SELECT rule_value FROM risk_limits "
            "WHERE enabled = 1 AND scope = 'global' AND rule_name = ?",
            (rule_name,),
        ).fetchone()
        return float(row[0]) if row else None
    except Exception:
        return None


# ── Individual risk checks ───────────────────────────────────────────────────

def _check_gross_exposure(
    conn: sqlite3.Connection,
    nav: float,
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
) -> RiskCheckResult:
    """Check 1: gross exposure vs limit."""
    if nav <= 0:
        return RiskCheckResult("gross_exposure", 0.0, 0.0, SEVERITY_OK)

    gross = sum(abs(float(p.get("qty", 0)) * float(p.get("current_price", 0))) for p in positions)
    exposure_ratio = gross / nav

    limit = _try_load_risk_store_limit(conn, "max_gross_exposure")
    if limit is None:
        limit = float(policy.get("gross_exposure_limit", 1.20))

    if exposure_ratio >= limit * 1.2:
        severity = SEVERITY_EMERGENCY
    elif exposure_ratio >= limit:
        severity = SEVERITY_CRITICAL
    elif exposure_ratio >= limit * 0.9:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_OK

    return RiskCheckResult("gross_exposure", round(exposure_ratio, 4), limit, severity)


def _check_symbol_concentration(
    nav: float,
    positions: List[Dict[str, Any]],
    policy: Dict[str, Any],
) -> RiskCheckResult:
    """Check 2: single symbol weight vs max."""
    if nav <= 0 or not positions:
        return RiskCheckResult("symbol_concentration", 0.0, 0.0, SEVERITY_OK)

    max_weight = 0.0
    for p in positions:
        value = abs(float(p.get("qty", 0)) * float(p.get("current_price", 0)))
        weight = value / nav
        max_weight = max(max_weight, weight)

    limit = float(policy.get("max_symbol_weight", 0.20))

    if max_weight >= limit * 1.3:
        severity = SEVERITY_EMERGENCY
    elif max_weight >= limit:
        severity = SEVERITY_CRITICAL
    elif max_weight >= limit * 0.85:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_OK

    return RiskCheckResult("symbol_concentration", round(max_weight, 4), limit, severity)


def _check_daily_loss(
    conn: sqlite3.Connection,
    nav: float,
    policy: Dict[str, Any],
) -> RiskCheckResult:
    """Check 3: daily P&L loss vs threshold."""
    threshold = float(policy.get("daily_loss_pct_threshold", 0.05))
    pnl_pct = 0.0

    try:
        if _table_exists(conn, "daily_pnl_summary"):
            row = conn.execute(
                "SELECT pnl_pct FROM daily_pnl_summary ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if row:
                pnl_pct = float(row[0] or 0.0)
    except Exception:
        pass

    loss_pct = abs(min(pnl_pct, 0.0))

    if loss_pct >= threshold * 1.5:
        severity = SEVERITY_EMERGENCY
    elif loss_pct >= threshold:
        severity = SEVERITY_CRITICAL
    elif loss_pct >= threshold * 0.7:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_OK

    return RiskCheckResult("daily_loss", round(loss_pct, 4), threshold, severity)


def _check_drawdown(conn: sqlite3.Connection, policy: Dict[str, Any]) -> RiskCheckResult:
    """Check 4: drawdown vs threshold (reuse drawdown_guard logic if available)."""
    threshold = float(policy.get("drawdown_pct_threshold", 0.15))
    drawdown = 0.0

    try:
        if _table_exists(conn, "daily_pnl_summary"):
            row = conn.execute(
                "SELECT rolling_drawdown FROM daily_pnl_summary "
                "ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if row:
                drawdown = float(row[0] or 0.0)
    except Exception:
        pass

    if drawdown >= threshold * 1.3:
        severity = SEVERITY_EMERGENCY
    elif drawdown >= threshold:
        severity = SEVERITY_CRITICAL
    elif drawdown >= threshold * 0.7:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_OK

    return RiskCheckResult("drawdown", round(drawdown, 4), threshold, severity)


def _check_correlation_concentration(
    conn: sqlite3.Connection,
    positions: List[Dict[str, Any]],
    nav: float,
    policy: Dict[str, Any],
) -> RiskCheckResult:
    """Check 5: correlation concentration (use correlation_guard if available)."""
    max_corr_limit = float(policy.get("correlation_max_pair_abs_corr", 0.85))

    if not positions or nav <= 0:
        return RiskCheckResult("correlation_concentration", 0.0, max_corr_limit, SEVERITY_OK)

    try:
        from openclaw.correlation_guard import (
            CorrelationGuardPolicy,
            evaluate_correlation_risk,
        )

        # Build weights from positions
        weights: Dict[str, float] = {}
        for p in positions:
            sym = str(p.get("symbol", ""))
            value = abs(float(p.get("qty", 0)) * float(p.get("current_price", 0)))
            if sym and value > 0:
                weights[sym] = value / nav

        # Try to get returns from eod_prices
        returns_by_symbol: Dict[str, List[float]] = {}
        if _table_exists(conn, "eod_prices"):
            for sym in weights:
                rows = conn.execute(
                    "SELECT close FROM eod_prices WHERE symbol = ? "
                    "ORDER BY trade_date DESC LIMIT 61",
                    (sym,),
                ).fetchall()
                if len(rows) >= 10:
                    closes = [float(r[0]) for r in reversed(rows)]
                    rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                            for i in range(1, len(closes)) if closes[i - 1] > 0]
                    if rets:
                        returns_by_symbol[sym] = rets

        if len(returns_by_symbol) < 2:
            return RiskCheckResult("correlation_concentration", 0.0, max_corr_limit, SEVERITY_OK)

        decision = evaluate_correlation_risk(
            returns_by_symbol=returns_by_symbol,
            weights_by_symbol=weights,
            policy=CorrelationGuardPolicy(
                max_pair_abs_corr=max_corr_limit,
                max_weighted_avg_abs_corr=float(
                    policy.get("correlation_max_weighted_avg_abs_corr", 0.55)
                ),
            ),
        )

        max_pair = decision.max_pair_abs_corr
        if not decision.ok and max_pair >= 0.95:
            severity = SEVERITY_CRITICAL
        elif not decision.ok:
            severity = SEVERITY_WARNING
        else:
            severity = SEVERITY_OK

        return RiskCheckResult("correlation_concentration", round(max_pair, 4), max_corr_limit, severity)

    except Exception as e:
        log.debug("correlation check skipped: %s", e)
        return RiskCheckResult("correlation_concentration", 0.0, max_corr_limit, SEVERITY_OK)


def _check_cash_level(
    cash: float,
    nav: float,
    policy: Dict[str, Any],
) -> RiskCheckResult:
    """Check 6: cash level < 5% NAV."""
    min_pct = float(policy.get("cash_min_pct", 0.05))

    if nav <= 0:
        return RiskCheckResult("cash_level", 0.0, min_pct, SEVERITY_OK)

    cash_pct = cash / nav

    if cash_pct < min_pct * 0.5:
        severity = SEVERITY_EMERGENCY
    elif cash_pct < min_pct:
        severity = SEVERITY_CRITICAL
    elif cash_pct < min_pct * 1.5:
        severity = SEVERITY_WARNING
    else:
        severity = SEVERITY_OK

    return RiskCheckResult("cash_level", round(cash_pct, 4), min_pct, severity)


# ── Main check function ─────────────────────────────────────────────────────

def _get_portfolio_snapshot(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Read latest portfolio snapshot from DB."""
    nav = 0.0
    cash = 0.0
    positions: List[Dict[str, Any]] = []

    # Try position_snapshots first (most recent)
    if _table_exists(conn, "position_snapshots"):
        try:
            row = conn.execute(
                "SELECT positions_json, available_cash FROM position_snapshots "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                positions = json.loads(row[0]) if row[0] else []
                cash = float(row[1] or 0.0)
        except Exception:
            pass

    # Fall back to positions table
    if not positions and _table_exists(conn, "positions"):
        try:
            rows = conn.execute(
                "SELECT symbol, qty, avg_cost, current_price FROM positions"
            ).fetchall()
            positions = [dict(r) for r in rows]
        except Exception:
            pass

    # NAV from daily_nav or compute from positions + cash
    if _table_exists(conn, "daily_nav"):
        try:
            row = conn.execute(
                "SELECT nav FROM daily_nav ORDER BY trade_date DESC LIMIT 1"
            ).fetchone()
            if row:
                nav = float(row[0] or 0.0)
        except Exception:
            pass

    if nav <= 0:
        position_value = sum(
            abs(float(p.get("qty", 0)) * float(p.get("current_price", 0)))
            for p in positions
        )
        nav = position_value + cash

    # Try capital.json for cash if not available
    if cash <= 0:
        try:
            capital = json.loads((_REPO_ROOT / "config" / "capital.json").read_text())
            cash = float(capital.get("available_cash", 0))
        except Exception:
            pass

    return {"nav": nav, "cash": cash, "positions": positions}


def check_portfolio_risk(
    conn: sqlite3.Connection,
    policy_path: str = _DEFAULT_POLICY_PATH,
) -> RiskMonitorReport:
    """Run all 6 risk checks and produce a RiskMonitorReport."""
    policy = _load_policy(policy_path)
    snapshot = _get_portfolio_snapshot(conn)

    nav = snapshot["nav"]
    cash = snapshot["cash"]
    positions = snapshot["positions"]

    checks = [
        _check_gross_exposure(conn, nav, positions, policy),
        _check_symbol_concentration(nav, positions, policy),
        _check_daily_loss(conn, nav, policy),
        _check_drawdown(conn, policy),
        _check_correlation_concentration(conn, positions, nav, policy),
        _check_cash_level(cash, nav, policy),
    ]

    worst = max(checks, key=lambda c: _SEVERITY_ORDER.get(c.severity, 0))

    # Compute summary metrics for logging
    gross = sum(abs(float(p.get("qty", 0)) * float(p.get("current_price", 0))) for p in positions)
    gross_exposure = gross / nav if nav > 0 else 0.0

    max_sym_weight = 0.0
    for p in positions:
        v = abs(float(p.get("qty", 0)) * float(p.get("current_price", 0)))
        w = v / nav if nav > 0 else 0.0
        max_sym_weight = max(max_sym_weight, w)

    # daily_pnl_pct
    daily_pnl_pct = 0.0
    for c in checks:
        if c.indicator == "daily_loss":
            daily_pnl_pct = -c.value  # stored as abs, restore sign
            break

    drawdown_pct = 0.0
    for c in checks:
        if c.indicator == "drawdown":
            drawdown_pct = c.value
            break

    return RiskMonitorReport(
        checks=checks,
        worst_breach=worst.severity,
        nav=nav,
        timestamp=int(time.time()),
        cash=cash,
        gross_exposure=round(gross_exposure, 4),
        max_symbol_weight=round(max_sym_weight, 4),
        daily_pnl_pct=round(daily_pnl_pct, 4),
        drawdown_pct=round(drawdown_pct, 4),
    )


# ── Notification ─────────────────────────────────────────────────────────────

def _should_notify(
    conn: sqlite3.Connection,
    breach_type: str,
    cooldown_seconds: int,
) -> bool:
    """Check if we should notify for this breach type (1h cooldown per breach).

    EMERGENCY severity always notifies — cooldown must never mask a second emergency.
    """
    if breach_type == SEVERITY_EMERGENCY:
        return True  # Always notify on EMERGENCY

    if not _table_exists(conn, "risk_monitor_log"):
        return True

    try:
        cutoff = int(time.time()) - cooldown_seconds
        row = conn.execute(
            "SELECT COUNT(*) FROM risk_monitor_log "
            "WHERE worst_breach = ? AND notified = 1 AND checked_at > ?",
            (breach_type, cutoff),
        ).fetchone()
        return (row[0] == 0) if row else True
    except Exception:
        return True


def alert_if_needed(
    report: RiskMonitorReport,
    conn: sqlite3.Connection,
    policy_path: str = _DEFAULT_POLICY_PATH,
) -> bool:
    """Send Telegram alert by severity, with dedup cooldown.

    Returns True if a notification was sent.
    """
    if report.worst_breach == SEVERITY_OK:
        return False

    policy = _load_policy(policy_path)
    cooldown = int(policy.get("notification_cooldown_seconds", 3600))

    if not _should_notify(conn, report.worst_breach, cooldown):
        log.info("[risk_monitor] notification suppressed by cooldown for %s", report.worst_breach)
        return False

    # Build breach summary
    breaches = [c for c in report.checks if c.severity != SEVERITY_OK]
    breach_lines = "\n".join(
        f"  • {c.indicator}: {c.value:.4f} (limit {c.threshold:.4f}) [{c.severity}]"
        for c in breaches
    )

    if report.worst_breach == SEVERITY_EMERGENCY:
        header = "🚨 <b>[RISK EMERGENCY]</b>"
        action_line = "⚡ 自動啟用 reduce_only 模式，禁止新開倉"
        _set_reduce_only(conn)
    elif report.worst_breach == SEVERITY_CRITICAL:
        header = "⚠️ <b>[RISK CRITICAL]</b>"
        action_line = "💡 建議啟用 reduce_only 模式"
    else:
        header = "📋 <b>[RISK WARNING]</b>"
        action_line = ""

    cash_pct = report.cash / report.nav if report.nav > 0 else 0.0
    msg = (
        f"{header}\n"
        f"Cash比例: {cash_pct:.1%} | Gross Exposure: {report.gross_exposure:.2%}\n\n"
        f"<b>Breaches:</b>\n{breach_lines}"
    )
    if action_line:
        msg += f"\n\n{action_line}"

    try:
        from openclaw.tg_notify import send_message
        send_message(msg)
        log.info("[risk_monitor] Telegram alert sent: %s", report.worst_breach)
        return True
    except Exception as e:
        log.warning("[risk_monitor] Telegram send failed: %s", e)
        if report.worst_breach == SEVERITY_EMERGENCY:
            # EMERGENCY: reduce_only already activated — ensure DB records it
            log.critical(
                "[risk_monitor] EMERGENCY notification failed! "
                "reduce_only_mode was activated but Telegram delivery failed. "
                "breach_count=%d, nav=%.0f",
                len([c for c in report.checks if c.severity != SEVERITY_OK]),
                report.nav,
            )
            # Return True so _log_to_db records notified=1 (reduce_only IS active)
            return True
        return False


def _set_reduce_only(conn: sqlite3.Connection) -> None:
    """Auto-set reduce_only in system_state on EMERGENCY.

    Uses file lock (fcntl.flock) + atomic write (tmp + os.replace)
    to prevent race conditions with other processes.
    """
    try:
        state_path = _REPO_ROOT / "config" / "system_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        # Acquire exclusive lock, read-modify-write, atomic replace
        if state_path.exists():
            with open(state_path, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    state = json.load(f)
                except json.JSONDecodeError:
                    state = {}
                state["reduce_only_mode"] = True
                state["reduce_only_reason"] = "risk_monitor_emergency"
                state["reduce_only_at"] = int(time.time())
                tmp = state_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                os.replace(str(tmp), str(state_path))
        else:
            state = {
                "reduce_only_mode": True,
                "reduce_only_reason": "risk_monitor_emergency",
                "reduce_only_at": int(time.time()),
            }
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
            os.replace(str(tmp), str(state_path))

        log.warning("[risk_monitor] reduce_only_mode ENABLED via system_state.json")
    except Exception as e:
        log.error("[risk_monitor] failed to set reduce_only: %s", e)


# ── Log to DB ────────────────────────────────────────────────────────────────

def _log_to_db(
    conn: sqlite3.Connection,
    report: RiskMonitorReport,
    notified: bool,
) -> None:
    """Write check result to risk_monitor_log."""
    _ensure_schema(conn)
    breaches = [
        {"indicator": c.indicator, "value": c.value, "threshold": c.threshold, "severity": c.severity}
        for c in report.checks
        if c.severity != SEVERITY_OK
    ]
    conn.execute(
        """INSERT INTO risk_monitor_log
           (check_id, checked_at, nav, cash, gross_exposure,
            max_symbol_weight, daily_pnl_pct, drawdown_pct,
            worst_breach, breaches_json, notified)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            str(uuid.uuid4()),
            report.timestamp,
            report.nav,
            report.cash,
            report.gross_exposure,
            report.max_symbol_weight,
            report.daily_pnl_pct,
            report.drawdown_pct,
            report.worst_breach,
            json.dumps(breaches, ensure_ascii=False),
            1 if notified else 0,
        ),
    )
    conn.commit()


# ── Entry point ──────────────────────────────────────────────────────────────

def run_risk_monitor(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
    policy_path: str = _DEFAULT_POLICY_PATH,
) -> AgentResult:
    """Run risk monitoring loop — called by agent_orchestrator."""
    _conn = conn or (open_conn(db_path) if db_path else open_conn())
    try:
        _ensure_schema(_conn)
        report = check_portfolio_risk(_conn, policy_path=policy_path)

        notified = alert_if_needed(report, _conn, policy_path=policy_path)
        _log_to_db(_conn, report, notified)

        breach_count = sum(1 for c in report.checks if c.severity != SEVERITY_OK)
        summary = (
            f"Risk monitor: {breach_count} breach(es), "
            f"worst={report.worst_breach}, NAV={report.nav:,.0f}, "
            f"exposure={report.gross_exposure:.2%}"
        )
        if notified:
            summary += " [notified]"

        log.info("[risk_monitor] %s", summary)

        return AgentResult(
            summary=summary,
            confidence=1.0,
            action_type="observe" if report.worst_breach == SEVERITY_OK else "suggest",
            proposals=[],
            raw={
                "worst_breach": report.worst_breach,
                "breach_count": breach_count,
                "nav": report.nav,
                "cash": report.cash,
                "gross_exposure": report.gross_exposure,
                "notified": notified,
                "checks": [
                    {
                        "indicator": c.indicator,
                        "value": c.value,
                        "threshold": c.threshold,
                        "severity": c.severity,
                    }
                    for c in report.checks
                ],
            },
        )
    finally:
        if conn is None:
            _conn.close()
