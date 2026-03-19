from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from openclaw.audit_store import insert_incident

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Error Budget
# ──────────────────────────────────────────────

@dataclass
class ErrorBudgetPolicy:
    """Tunable thresholds for mismatch severity classification."""

    # Mismatch is "small noise" when total quantity delta <= this many shares.
    small_diff_shares: int = 100
    # How many consecutive days of small diffs before we downgrade to INFO.
    consecutive_days_to_suppress: int = 3
    # If today's mismatch count exceeds avg * this multiplier → P0.
    spike_multiplier: float = 3.0
    # Lookback window (days) for computing the baseline average.
    baseline_days: int = 7


@dataclass
class ErrorBudgetDecision:
    """Outcome from evaluate_error_budget()."""

    severity: str          # "info" | "warning" | "critical"
    suppress_incident: bool
    reason: str
    quantity_delta: int    # total shares difference
    consecutive_small_days: int
    baseline_avg: float
    details: dict[str, Any] = field(default_factory=dict)


def _compute_quantity_delta(mismatches: dict[str, list[dict[str, Any]]]) -> int:
    """Sum of |local.qty − broker.qty| across all quantity_mismatch entries."""
    total = 0
    for item in mismatches.get("quantity_mismatch", []):
        local_qty = int((item.get("local") or {}).get("quantity") or 0)
        broker_qty = int((item.get("broker") or {}).get("quantity") or 0)
        total += abs(local_qty - broker_qty)
    # Also count each missing-position as a full-position delta.
    for item in mismatches.get("missing_local_position", []):
        total += int((item.get("broker") or {}).get("quantity") or 0)
    for item in mismatches.get("missing_broker_position", []):
        total += int((item.get("local") or {}).get("quantity") or 0)
    return total


def _get_daily_mismatch_counts(
    conn: sqlite3.Connection,
    *,
    days: int = 7,
) -> list[int]:
    """Return the most recent `days` daily max-mismatch-count values.

    We pick the worst (max) reconciliation run per calendar day so that
    a noisy day does not look artificially clean.
    """
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    try:
        rows = conn.execute(
            """
            SELECT date(created_at / 1000, 'unixepoch') AS day,
                   max(mismatch_count) AS daily_max
              FROM reconciliation_reports
             WHERE created_at >= ?
             GROUP BY day
             ORDER BY day DESC
            """,
            (cutoff_ms,),
        ).fetchall()
        return [int(r[1]) for r in rows]
    except sqlite3.Error as exc:
        log.warning("[reconciliation] Error Budget: cannot query history: %s", exc)
        return []


def _count_consecutive_small_days(
    conn: sqlite3.Connection,
    *,
    small_diff_shares: int,
    consecutive_days: int,
) -> int:
    """Return the number of consecutive *recent* days where max quantity delta was small.

    Reads `summary_json` to extract `quantity_delta` stored per report.
    Returns 0 if the schema column is unavailable.
    """
    try:
        cutoff_ms = int((time.time() - consecutive_days * 86400) * 1000)
        rows = conn.execute(
            """
            SELECT date(created_at / 1000, 'unixepoch') AS day,
                   max(mismatch_count) AS daily_max,
                   summary_json
              FROM reconciliation_reports
             WHERE created_at >= ?
             GROUP BY day
             ORDER BY day DESC
            """,
            (cutoff_ms,),
        ).fetchall()
    except sqlite3.Error:
        return 0

    consecutive = 0
    for row in rows:
        mismatch_count = int(row[1])
        if mismatch_count == 0:
            # Perfect day — counts as small.
            consecutive += 1
            continue
        # Try to extract per-day quantity delta from any report summary.
        try:
            summary = json.loads(row[2] or "{}")
            qty_delta = int(summary.get("quantity_delta", -1))
            if qty_delta < 0:
                # Old row without quantity_delta field — fall back to mismatch count.
                qty_delta = mismatch_count
        except (json.JSONDecodeError, TypeError):
            qty_delta = mismatch_count
        if qty_delta <= small_diff_shares:
            consecutive += 1
        else:
            break
    return consecutive


def evaluate_error_budget(
    conn: sqlite3.Connection,
    mismatches: dict[str, list[dict[str, Any]]],
    *,
    policy: ErrorBudgetPolicy | None = None,
) -> ErrorBudgetDecision:
    """Classify this reconciliation mismatch using the Error Budget policy.

    Returns an ErrorBudgetDecision with:
    - severity: "info" | "warning" | "critical"
    - suppress_incident: True means skip writing to incidents table (just log)
    """
    if policy is None:
        policy = ErrorBudgetPolicy()

    qty_delta = _compute_quantity_delta(mismatches)
    history = _get_daily_mismatch_counts(conn, days=policy.baseline_days)
    baseline_avg = sum(history) / len(history) if history else 0.0

    total_mismatches = sum(len(v) for v in mismatches.values())

    # ── Spike detection ───────────────────────────────────────────────────
    if baseline_avg > 0 and total_mismatches > baseline_avg * policy.spike_multiplier:
        return ErrorBudgetDecision(
            severity="critical",
            suppress_incident=False,
            reason=f"SPIKE: {total_mismatches} mismatches > {policy.spike_multiplier}x avg ({baseline_avg:.1f})",
            quantity_delta=qty_delta,
            consecutive_small_days=0,
            baseline_avg=baseline_avg,
            details={"trigger": "spike", "multiplier": policy.spike_multiplier},
        )

    # ── Small-noise suppression ───────────────────────────────────────────
    if qty_delta <= policy.small_diff_shares:
        consecutive = _count_consecutive_small_days(
            conn,
            small_diff_shares=policy.small_diff_shares,
            consecutive_days=policy.consecutive_days_to_suppress,
        )
        if consecutive >= policy.consecutive_days_to_suppress:
            return ErrorBudgetDecision(
                severity="info",
                suppress_incident=True,
                reason=(
                    f"SMALL_NOISE: qty_delta={qty_delta} shares ≤ {policy.small_diff_shares} "
                    f"for {consecutive} consecutive days"
                ),
                quantity_delta=qty_delta,
                consecutive_small_days=consecutive,
                baseline_avg=baseline_avg,
                details={"trigger": "suppress"},
            )

    return ErrorBudgetDecision(
        severity="warning",
        suppress_incident=False,
        reason=f"NORMAL: qty_delta={qty_delta} shares, mismatches={total_mismatches}",
        quantity_delta=qty_delta,
        consecutive_small_days=0,
        baseline_avg=baseline_avg,
        details={"trigger": "normal"},
    )


def ensure_reconciliation_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_reports (
            report_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            mismatch_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reconciliation_reports_created ON reconciliation_reports (created_at)"
    )
    conn.commit()


def reconcile_broker_state(
    conn: sqlite3.Connection,
    *,
    broker_positions: list[dict[str, Any]],
    broker_open_orders: list[dict[str, Any]] | None = None,
    broker_context: dict[str, Any] | None = None,
    auto_commit: bool = True,
) -> dict[str, Any]:
    ensure_reconciliation_schema(conn)
    broker_open_orders = broker_open_orders or []
    broker_context = broker_context or {}

    local_positions_rows = conn.execute(
        "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
    ).fetchall()
    local_positions = {
        str(r[0]): {"quantity": int(r[1] or 0), "current_price": float(r[2] or 0.0)}
        for r in local_positions_rows
    }
    broker_positions_map = {
        str(p["symbol"]): {"quantity": int(p.get("quantity") or 0), "current_price": float(p.get("current_price") or 0.0)}
        for p in broker_positions
        if int(p.get("quantity") or 0) > 0
    }

    mismatches: dict[str, list[dict[str, Any]]] = {
        "missing_local_position": [],
        "missing_broker_position": [],
        "quantity_mismatch": [],
        "missing_broker_order": [],
    }

    for symbol, bpos in broker_positions_map.items():
        lpos = local_positions.get(symbol)
        if lpos is None:
            mismatches["missing_local_position"].append({"symbol": symbol, "broker": bpos})
        elif int(lpos["quantity"]) != int(bpos["quantity"]):
            mismatches["quantity_mismatch"].append({"symbol": symbol, "local": lpos, "broker": bpos})

    for symbol, lpos in local_positions.items():
        if symbol not in broker_positions_map:
            mismatches["missing_broker_position"].append({"symbol": symbol, "local": lpos})

    local_open_orders = conn.execute(
        "SELECT order_id, broker_order_id, symbol, status FROM orders WHERE status IN ('submitted', 'partially_filled')"
    ).fetchall()
    broker_order_ids = {str(o.get("broker_order_id") or "") for o in broker_open_orders}
    for row in local_open_orders:
        broker_order_id = str(row[1] or "")
        if broker_order_id and broker_order_id not in broker_order_ids:
            mismatches["missing_broker_order"].append(
                {
                    "order_id": str(row[0]),
                    "broker_order_id": broker_order_id,
                    "symbol": str(row[2]),
                    "status": str(row[3]),
                }
            )

    mismatch_count = sum(len(v) for v in mismatches.values())
    diagnostics = _build_reconciliation_diagnostics(
        local_positions=local_positions,
        broker_positions_map=broker_positions_map,
        local_open_orders=local_open_orders,
        broker_open_orders=broker_open_orders,
        mismatches=mismatches,
        broker_context=broker_context,
    )

    # Evaluate error budget before writing the report (history lookup uses
    # existing rows so we must query *before* inserting the new one).
    budget: ErrorBudgetDecision | None = None
    if mismatch_count:
        budget = evaluate_error_budget(conn, mismatches)

    quantity_delta = budget.quantity_delta if budget else 0
    report = {
        "report_id": str(uuid.uuid4()),
        "created_at": int(time.time() * 1000),
        "mismatch_count": mismatch_count,
        "quantity_delta": quantity_delta,
        "ok": mismatch_count == 0,
        "mismatches": mismatches,
        "diagnostics": diagnostics,
    }

    conn.execute(
        "INSERT INTO reconciliation_reports(report_id, created_at, mismatch_count, summary_json) VALUES (?, ?, ?, ?)",
        (report["report_id"], report["created_at"], mismatch_count, json.dumps(report, ensure_ascii=True)),
    )

    simulation_expected = (
        diagnostics.get("resolved_simulation") is True
        and "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in diagnostics.get("diagnosis_codes", [])
    )
    if mismatch_count and not simulation_expected:
        if budget is not None and budget.suppress_incident:
            log.info("[reconciliation] Error Budget suppressed incident: %s", budget.reason)
        else:
            try:
                _insert_reconciliation_incident_best_effort(
                    conn=conn,
                    report=report,
                    mismatches=mismatches,
                    diagnostics=diagnostics,
                    budget=budget,
                )
            except sqlite3.Error:
                pass

    if auto_commit:
        conn.commit()
    return report


def _build_reconciliation_diagnostics(
    *,
    local_positions: dict[str, dict[str, Any]],
    broker_positions_map: dict[str, dict[str, Any]],
    local_open_orders: list[tuple[Any, ...]],
    broker_open_orders: list[dict[str, Any]],
    mismatches: dict[str, list[dict[str, Any]]],
    broker_context: dict[str, Any],
) -> dict[str, Any]:
    diagnosis_codes: list[str] = []
    notes: list[str] = []
    missing_broker_count = len(mismatches.get("missing_broker_position", []))

    if local_positions and not broker_positions_map:
        diagnosis_codes.append("MODE_OR_ACCOUNT_MISMATCH_SUSPECTED")
        notes.append("Local positions exist while broker snapshot is empty; verify account and simulation mode.")
    elif local_positions and missing_broker_count == len(local_positions):
        diagnosis_codes.append("BROKER_POSITION_DIVERGENCE")
        notes.append("Every local position is absent from broker snapshot; verify account mapping and sync source.")

    return {
        "resolved_simulation": broker_context.get("resolved_simulation"),
        "requested_simulation": broker_context.get("requested_simulation"),
        "broker_source": broker_context.get("broker_source"),
        "broker_accounts": sorted({str(a) for a in broker_context.get("broker_accounts", []) if str(a)}),
        "local_position_count": len(local_positions),
        "broker_position_count": len(broker_positions_map),
        "local_open_order_count": len(local_open_orders),
        "broker_open_order_count": len(broker_open_orders),
        "diagnosis_codes": diagnosis_codes,
        "suspected_mode_or_account_mismatch": "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in diagnosis_codes,
        "notes": notes,
    }


def _stable_incident_detail(
    mismatches: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mismatch_count": sum(len(v) for v in mismatches.values()),
        "missing_local_symbols": sorted(item["symbol"] for item in mismatches.get("missing_local_position", [])),
        "missing_broker_symbols": sorted(item["symbol"] for item in mismatches.get("missing_broker_position", [])),
        "quantity_mismatch_symbols": sorted(item["symbol"] for item in mismatches.get("quantity_mismatch", [])),
        "missing_broker_order_ids": sorted(item["order_id"] for item in mismatches.get("missing_broker_order", [])),
        "diagnosis_codes": diagnostics.get("diagnosis_codes", []),
        "resolved_simulation": diagnostics.get("resolved_simulation"),
        "requested_simulation": diagnostics.get("requested_simulation"),
        "broker_source": diagnostics.get("broker_source"),
        "broker_accounts": diagnostics.get("broker_accounts", []),
    }


def _insert_reconciliation_incident_best_effort(
    *,
    conn: sqlite3.Connection,
    report: dict[str, Any],
    mismatches: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, Any],
    budget: "ErrorBudgetDecision | None" = None,
) -> None:
    stable_detail = _stable_incident_detail(mismatches, diagnostics)
    rows = conn.execute(
        """
        SELECT detail_json
          FROM incidents
         WHERE resolved=0
           AND source='broker_reconciliation'
           AND code='RECONCILIATION_MISMATCH'
        """,
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("stable_detail") == stable_detail:
            return

    # Severity priority: budget spike → critical; account mismatch → critical;
    # budget normal/warning; fallback → warning.
    if budget is not None and budget.severity == "critical":
        severity = "critical"
    elif diagnostics.get("suspected_mode_or_account_mismatch"):
        severity = "critical"
    elif budget is not None:
        severity = budget.severity  # "warning" or "info"
    else:
        severity = "warning"

    detail: dict[str, Any] = {
        "report_id": report["report_id"],
        "stable_detail": stable_detail,
        "mismatches": mismatches,
        "diagnostics": diagnostics,
    }
    if budget is not None:
        detail["error_budget"] = {
            "severity": budget.severity,
            "reason": budget.reason,
            "quantity_delta": budget.quantity_delta,
            "baseline_avg": budget.baseline_avg,
        }

    insert_incident(
        conn,
        ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        severity=severity,
        source="broker_reconciliation",
        code="RECONCILIATION_MISMATCH",
        detail=detail,
        auto_commit=False,
    )
