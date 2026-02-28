from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class BudgetTier:
    name: str
    threshold_pct: float
    action: str
    message: str = ""
    adjustments: Dict[str, Any] | None = None


@dataclass(frozen=True)
class BudgetPolicy:
    system_name: str
    version: str
    currency: str
    base_monthly_budget: float
    tiers: Dict[str, BudgetTier]


def load_budget_policy(path: Path) -> BudgetPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    tiers: Dict[str, BudgetTier] = {}
    for name, tier in (data.get("tiers") or {}).items():
        tiers[name] = BudgetTier(
            name=name,
            threshold_pct=float(tier.get("threshold_pct", 0)),
            action=str(tier.get("action") or ""),
            message=str(tier.get("message") or ""),
            adjustments=dict(tier.get("adjustments") or {}),
        )
    return BudgetPolicy(
        system_name=str(data.get("system_name") or ""),
        version=str(data.get("version") or ""),
        currency=str(data.get("currency") or "TWD"),
        base_monthly_budget=float(data.get("base_monthly_budget") or 0.0),
        tiers=tiers,
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _month_key(ts_ms: Optional[int] = None) -> str:
    # YYYY-MM in UTC for simplicity; caller can decide tz externally.
    t = time.gmtime((ts_ms or int(time.time() * 1000)) / 1000)
    return f"{t.tm_year:04d}-{t.tm_mon:02d}"


def record_token_usage(
    conn: sqlite3.Connection,
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    est_cost_twd: float = 0.0,
    ts_ms: Optional[int] = None,
) -> None:
    """Upsert daily/monthly token usage.

    This is best-effort: if the required table doesn't exist, it no-ops.
    """

    if not _table_exists(conn, "token_usage_monthly"):
        return

    month = _month_key(ts_ms)
    conn.execute(
        """
        INSERT INTO token_usage_monthly(month, model, prompt_tokens, completion_tokens, est_cost_twd, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(month, model) DO UPDATE SET
          prompt_tokens = prompt_tokens + excluded.prompt_tokens,
          completion_tokens = completion_tokens + excluded.completion_tokens,
          est_cost_twd = est_cost_twd + excluded.est_cost_twd,
          updated_at = excluded.updated_at
        """,
        (month, model, int(prompt_tokens), int(completion_tokens), float(est_cost_twd)),
    )


def get_monthly_cost(conn: sqlite3.Connection, *, month: Optional[str] = None) -> float:
    if not _table_exists(conn, "token_usage_monthly"):
        return 0.0
    # For deterministic callers/tests: month=None means "no specific month".
    # Budget evaluation should pass an explicit month key.
    if month is None:
        return 0.0
    m = month
    row = conn.execute(
        "SELECT COALESCE(SUM(est_cost_twd), 0.0) FROM token_usage_monthly WHERE month = ?",
        (m,),
    ).fetchone()
    return float(row[0] if row else 0.0)


def evaluate_budget(conn: sqlite3.Connection, policy: BudgetPolicy, *, month: Optional[str] = None) -> Tuple[str, float, Optional[BudgetTier]]:
    """Return (status, used_pct, tier) where status is ok/warn/throttle/halt."""

    if policy.base_monthly_budget <= 0:
        return "ok", 0.0, None

    m = month or _month_key()
    used = get_monthly_cost(conn, month=m)
    used_pct = (used / policy.base_monthly_budget) * 100.0

    # Order is important: critical first
    critical = policy.tiers.get("critical_halt")
    throttling = policy.tiers.get("throttling")
    warning = policy.tiers.get("warning")

    if critical and used_pct >= critical.threshold_pct:
        return "halt", used_pct, critical
    if throttling and used_pct >= throttling.threshold_pct:
        return "throttle", used_pct, throttling
    if warning and used_pct >= warning.threshold_pct:
        return "warn", used_pct, warning
    return "ok", used_pct, None


def emit_budget_event(
    conn: sqlite3.Connection,
    *,
    tier: BudgetTier,
    used_pct: float,
    month: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    if not _table_exists(conn, "token_budget_events"):
        return
    conn.execute(
        """
        INSERT INTO token_budget_events(event_id, ts, month, tier, used_pct, action, message, extra_json)
        VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            month or _month_key(),
            tier.name,
            float(used_pct),
            tier.action,
            tier.message,
            json.dumps(extra or {}, ensure_ascii=True),
        ),
    )
