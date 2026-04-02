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
from openclaw.config_manager import get_config
from openclaw.path_utils import get_repo_root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("agent_orchestrator")

_REPO_ROOT = get_repo_root()
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

_LAST_STRATEGY_COMMITEE_TRIGGER: Optional[datetime] = None


def _pm_review_just_completed(
    state_path: str = _STATE_PATH,
    last_seen: Optional[str] = None,
) -> Optional[str]:
    """回傳新的 reviewed_at，或 None（無新事件）。10 分鐘內不重複觸發。"""
    global _LAST_STRATEGY_COMMITEE_TRIGGER
    state = get_config().daily_pm_state()
    reviewed_at = state.reviewed_at
    if reviewed_at and reviewed_at != last_seen:
        # 10 分鐘冷卻：防止同一個 PM review 完成事件重複觸發多個 StrategyCommitteeAgent
        now = datetime.now(tz=_TZ_TWN)
        if (
            _LAST_STRATEGY_COMMITEE_TRIGGER
            and (now - _LAST_STRATEGY_COMMITEE_TRIGGER) < timedelta(minutes=10)
        ):
            log.info(
                "[ORCHESTRATOR] StrategyCommitteeAgent cooldown active "
                "(%.0f min since last trigger) — skipping duplicate PM review event",
                (now - _LAST_STRATEGY_COMMITEE_TRIGGER).total_seconds() / 60,
            )
            return None
        _LAST_STRATEGY_COMMITEE_TRIGGER = now
        return reviewed_at
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


def _run_reflection_agent() -> None:
    """同步包裝：在 executor 執行 ReflectionAgent.reflect_weekly()。
    自行開連線，避免與主迴圈共用 conn 導致 ProgrammingError（closed database）。
    """
    try:
        from openclaw.db_utils import get_readwrite_conn
        from openclaw.strategy_optimizer import ReflectionAgent
        with get_readwrite_conn(DB_PATH) as conn:
            proposals = ReflectionAgent(conn).reflect_weekly()
        log.info("[orchestrator] ReflectionAgent 建議 %d 項", len(proposals))
    except Exception as e:
        log.warning("[orchestrator] ReflectionAgent 失敗：%s", e)


# ── 主排程迴圈 ────────────────────────────────────────────────────────────────

async def run_orchestrator() -> None:
    from openclaw.agents.market_research import run_market_research
    from openclaw.agents.portfolio_review import run_portfolio_review
    from openclaw.agents.system_health import run_system_health
    from openclaw.agents.strategy_committee import run_strategy_committee
    from openclaw.agents.system_optimization import run_system_optimization
    from openclaw.agents.eod_analysis import run_eod_analysis
    from openclaw.agents.risk_monitor import run_risk_monitor
    from openclaw.agents.strategy_auto_optimizer import run_strategy_auto_optimizer

    log.info("Agent Orchestrator started | DB=%s", DB_PATH)

    last_pm_reviewed_at: Optional[str] = None
    last_health_run_utc: Optional[datetime] = None
    last_health_off_utc: Optional[datetime] = None
    last_opt_trigger_date: Optional[str] = None
    last_risk_market_utc: Optional[datetime] = None
    last_risk_off_utc: Optional[datetime] = None

    from openclaw.db_utils import get_readwrite_conn

    while True:
        now_twn = datetime.now(tz=_TZ_TWN)
        now_utc = datetime.now(tz=timezone.utc)
        try:
            with get_readwrite_conn(DB_PATH) as conn:
                # ── 定時任務 ──────────────────────────────────────────────────
                if _is_weekday_twn(now_twn):
                    if _should_run_now("08:20", now_twn):
                        asyncio.create_task(_run_agent("MarketResearchAgent", run_market_research))

                    if _should_run_now("14:30", now_twn):
                        asyncio.create_task(_run_agent("PortfolioReviewAgent", run_portfolio_review))

                    # 每交易日 22:00 TWN → 盤後分析（資料最晚 21:14 入庫，22:00 安全）
                    if _should_run_now("22:00", now_twn):
                        asyncio.create_task(_run_agent("EODAnalysisAgent", run_eod_analysis))

                    # 每 30 分鐘系統健康（市場時段）
                    if 9 <= now_twn.hour < 14:
                        if (last_health_run_utc is None or
                                (now_utc - last_health_run_utc).total_seconds() >= 1800):
                            asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                            last_health_run_utc = now_utc

                    # 每 15 分鐘風險監控（市場時段）
                    if 9 <= now_twn.hour < 14:
                        if (last_risk_market_utc is None or
                                (now_utc - last_risk_market_utc).total_seconds() >= 900):
                            asyncio.create_task(_run_agent("RiskMonitorAgent", run_risk_monitor))
                            last_risk_market_utc = now_utc

                # 每 2 小時系統健康（非市場時段）
                if not (9 <= now_twn.hour < 14):
                    if (last_health_off_utc is None or
                            (now_utc - last_health_off_utc).total_seconds() >= 7200):
                        asyncio.create_task(_run_agent("SystemHealthAgent", run_system_health))
                        last_health_off_utc = now_utc

                # 每 60 分鐘風險監控（非市場時段）
                if not (9 <= now_twn.hour < 14):
                    if (last_risk_off_utc is None or
                            (now_utc - last_risk_off_utc).total_seconds() >= 3600):
                        asyncio.create_task(_run_agent("RiskMonitorAgent", run_risk_monitor))
                        last_risk_off_utc = now_utc

                if _is_monday_twn(now_twn):
                    if _should_run_now("07:00", now_twn):
                        asyncio.create_task(
                            _run_agent("SystemOptimizationAgent", run_system_optimization))
                        # 週一 07:00 深度反思（非阻塞）
                        asyncio.create_task(asyncio.to_thread(_run_reflection_agent))
                    if _should_run_now("07:15", now_twn):
                        asyncio.create_task(
                            _run_agent("StrategyAutoOptimizer", run_strategy_auto_optimizer))
                    if _should_run_now("07:30", now_twn):
                        asyncio.create_task(
                            _run_agent("StrategyCommitteeAgent", run_strategy_committee))

                # ── 事件任務 ──────────────────────────────────────────────────
                new_reviewed_at = _pm_review_just_completed(last_seen=last_pm_reviewed_at)
                if new_reviewed_at:
                    log.info("[EVENT] PM review completed → StrategyCommitteeAgent + StrategyAutoOptimizer")
                    last_pm_reviewed_at = new_reviewed_at
                    asyncio.create_task(
                        _run_agent("StrategyCommitteeAgent", run_strategy_committee))
                    asyncio.create_task(
                        _run_agent("StrategyAutoOptimizer", run_strategy_auto_optimizer))

                today_str = now_twn.strftime("%Y-%m-%d")
                if last_opt_trigger_date != today_str and _watcher_no_fills_3days(conn):
                    log.info("[EVENT] 3-day no fills → SystemOptimizationAgent")
                    last_opt_trigger_date = today_str
                    asyncio.create_task(
                        _run_agent("SystemOptimizationAgent", run_system_optimization))

        except Exception as e:
            log.error("[ORCHESTRATOR] Main loop error: %s", e, exc_info=True)

        await asyncio.sleep(60)


def main() -> None:
    asyncio.run(run_orchestrator())


if __name__ == "__main__":  # pragma: no cover
    main()
