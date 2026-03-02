"""agent_orchestrator.py — 統一 Agent 排程 Orchestrator。

PM2 進程名稱：ai-trader-agents
架構：asyncio 排程器，每分鐘輪詢定時 + 事件任務
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("agent_orchestrator")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATE_PATH = str(_REPO_ROOT / "config" / "daily_pm_state.json")
_TZ_TWN = timezone(timedelta(hours=8))
DB_PATH: str = os.environ.get("DB_PATH", str(_REPO_ROOT / "data" / "sqlite" / "trades.db"))


# ── 排程 helpers ──────────────────────────────────────────────────────────────

def _should_run_now(hhmm: str, now_twn: Optional[datetime] = None) -> bool:
    """True if 台灣當前時間 == hhmm（HH:MM）。"""
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.strftime("%H:%M") == hhmm


def _is_weekday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() < 5


def _is_monday_twn(now_twn: Optional[datetime] = None) -> bool:
    t = now_twn or datetime.now(tz=_TZ_TWN)
    return t.weekday() == 0


# ── 事件偵測 ──────────────────────────────────────────────────────────────────

def _pm_review_just_completed(
    state_path: str = _STATE_PATH,
    last_seen: Optional[str] = None,
) -> Optional[str]:
    """回傳新的 reviewed_at，或 None（無新事件）。"""
    try:
        with open(state_path) as f:
            state = json.load(f)
        reviewed_at = state.get("reviewed_at")
        if reviewed_at and reviewed_at != last_seen:
            return reviewed_at
    except Exception:
        pass
    return None


def _watcher_no_fills_3days(conn: sqlite3.Connection) -> bool:
    """近 3 日無成交時回傳 True。"""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM fills WHERE ts_fill > datetime('now','-3 days')"
        ).fetchone()
        return (row[0] == 0) if row else False
    except Exception:
        return False


# ── Agent 執行包裝 ────────────────────────────────────────────────────────────

async def _run_agent(name: str, fn, *args, **kwargs) -> None:
    """隔離執行：一個 agent crash 不影響排程器。"""
    try:
        log.info("[ORCHESTRATOR] Starting %s …", name)
        await asyncio.get_event_loop().run_in_executor(None, lambda: fn(*args, **kwargs))
        log.info("[ORCHESTRATOR] %s completed.", name)
    except Exception as e:
        log.error("[ORCHESTRATOR] %s failed: %s", name, e, exc_info=True)


# ── 主排程迴圈 ────────────────────────────────────────────────────────────────

async def run_orchestrator() -> None:
    from openclaw.agents.market_research import run_market_research
    from openclaw.agents.portfolio_review import run_portfolio_review
    from openclaw.agents.system_health import run_system_health
    from openclaw.agents.strategy_committee import run_strategy_committee
    from openclaw.agents.system_optimization import run_system_optimization

    log.info("Agent Orchestrator started | DB=%s", DB_PATH)

    last_pm_reviewed_at: Optional[str] = None
    last_health_run_utc: Optional[datetime] = None
    last_health_off_utc: Optional[datetime] = None
    last_opt_trigger_date: Optional[str] = None

    while True:
        now_twn = datetime.now(tz=_TZ_TWN)
        now_utc = datetime.now(tz=timezone.utc)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        try:
            # ── 定時任務 ──────────────────────────────────────────────────
            if _is_weekday_twn(now_twn):
                if _should_run_now("08:20", now_twn):
                    asyncio.create_task(_run_agent("MarketResearchAgent", run_market_research))

                if _should_run_now("14:30", now_twn):
                    asyncio.create_task(_run_agent("PortfolioReviewAgent", run_portfolio_review))

                # 每 30 分鐘系統健康（市場時段）
                if 9 <= now_twn.hour < 14:
                    if (last_health_run_utc is None or
                            (now_utc - last_health_run_utc).seconds >= 1800):
                        asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                        last_health_run_utc = now_utc

            # 每 2 小時系統健康（非市場時段）
            if not (9 <= now_twn.hour < 14):
                if (last_health_off_utc is None or
                        (now_utc - last_health_off_utc).seconds >= 7200):
                    asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                    last_health_off_utc = now_utc

            if _is_monday_twn(now_twn):
                if _should_run_now("07:00", now_twn):
                    asyncio.create_task(
                        _run_agent("SystemOptimizationAgent", run_system_optimization))
                if _should_run_now("07:30", now_twn):
                    asyncio.create_task(
                        _run_agent("StrategyCommitteeAgent", run_strategy_committee))

            # ── 事件任務 ──────────────────────────────────────────────────
            new_reviewed_at = _pm_review_just_completed(last_seen=last_pm_reviewed_at)
            if new_reviewed_at:
                log.info("[EVENT] PM review completed → StrategyCommitteeAgent")
                last_pm_reviewed_at = new_reviewed_at
                asyncio.create_task(
                    _run_agent("StrategyCommitteeAgent", run_strategy_committee))

            today_str = now_twn.strftime("%Y-%m-%d")
            if last_opt_trigger_date != today_str and _watcher_no_fills_3days(conn):
                log.info("[EVENT] 3-day no fills → SystemOptimizationAgent")
                last_opt_trigger_date = today_str
                asyncio.create_task(
                    _run_agent("SystemOptimizationAgent", run_system_optimization))

        except Exception as e:
            log.error("[ORCHESTRATOR] Main loop error: %s", e, exc_info=True)
        finally:
            conn.close()

        await asyncio.sleep(60)


def main() -> None:
    asyncio.run(run_orchestrator())


if __name__ == "__main__":  # pragma: no cover
    main()
