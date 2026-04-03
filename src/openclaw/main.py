from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass

from openclaw.audit_store import insert_incident, insert_risk_check
from openclaw.broker import BrokerAdapter, BrokerOrderStatus, SimBrokerAdapter
from openclaw.drawdown_guard import DrawdownPolicy, evaluate_drawdown_guard, evaluate_strategy_health_guard
from openclaw.order_store import insert_order_event, transition_with_event
from openclaw.orders import summarize_fill_status
from openclaw.risk_engine import Decision, MarketState, PortfolioState, SystemState, evaluate_and_build_order
from openclaw.risk_store import LimitQuery, load_limits
from openclaw.cash_mode_manager import CashModeManager
from openclaw.market_regime import MarketRegime, MarketRegimeResult
from openclaw.db_router import get_connection, init_execution_tables
from openclaw.pre_trade_guard import evaluate_pre_trade_guard
from openclaw.resume_protocol import system_self_check, run_resume_flow, ResumeProtocolTracker
from openclaw.sentinel import filter_locked_positions

def utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


@dataclass
class ExecutionResult:
    ok: bool
    order_id: str
    error_code: str = ""
    error_message: str = ""


def persist_order(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    decision_id: str,
    broker_order_id: str,
    symbol: str,
    side: str,
    qty: int,
    price: float,
    strategy_version: str,
    status: str = "submitted",
) -> None:
    conn.execute(
        """
        INSERT INTO orders (
          order_id, decision_id, broker_order_id, ts_submit, symbol, side, qty, price,
          order_type, tif, status, strategy_version
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            decision_id,
            broker_order_id,
            utc_now_iso(),
            symbol,
            side,
            qty,
            price,
            "limit",
            "IOC",
            status,
            strategy_version,
        ),
    )


def persist_decision(
    conn: sqlite3.Connection,
    *,
    decision: Decision,
    strategy_version: str,
    reason: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO decisions (
          decision_id, ts, symbol, strategy_id, strategy_version, signal_side, signal_score, signal_ttl_ms, llm_ref, reason_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision.decision_id,
            utc_now_iso(),
            decision.symbol,
            decision.strategy_id,
            strategy_version,
            decision.signal_side,
            decision.signal_score,
            decision.signal_ttl_ms,
            None,
            json.dumps(reason or {"source": "main_demo"}, ensure_ascii=True),
        ),
    )


def persist_fill(
    conn: sqlite3.Connection,
    *,
    fill_id: str,
    order_id: str,
    qty: int,
    price: float,
    fee: float,
    tax: float,
) -> None:
    conn.execute(
        """
        INSERT INTO fills (fill_id, order_id, ts_fill, qty, price, fee, tax)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (fill_id, order_id, utc_now_iso(), qty, price, fee, tax),
    )


def execute_approved_order(
    conn: sqlite3.Connection,
    *,
    broker: BrokerAdapter,
    decision: Decision,
    strategy_version: str,
    symbol: str,
    side: str,
    qty: int,
    price: float,
    candidate,
    poll_interval_sec: float = 0.5,
    poll_timeout_sec: float = 5.0,
    guard_limits: dict[str, float] | None = None,
) -> ExecutionResult:
    order_id = str(uuid.uuid4())
    guard_result = evaluate_pre_trade_guard(conn, candidate, limits=guard_limits)
    if not guard_result.approved:
        persist_order(
            conn,
            order_id=order_id,
            decision_id=decision.decision_id,
            broker_order_id="",
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            strategy_version=strategy_version,
            status="rejected",
        )
        insert_order_event(
            conn,
            order_id=order_id,
            event_type="rejected",
            from_status=None,
            to_status="rejected",
            source="pre_trade_guard",
            reason_code=guard_result.reject_code,
            payload=guard_result.metrics,
        )
        return ExecutionResult(
            ok=False,
            order_id=order_id,
            error_code=guard_result.reject_code,
            error_message="pre-trade guard rejected order",
        )

    # v4 #12: IP allowlist gate for sensitive broker APIs (configurable via env)
    # #600: skip in simulation mode to avoid false-positive SEC_NETWORK_IP_DENIED
    from openclaw.network_allowlist import enforce_network_security

    _sim_mode = os.getenv("SIMULATION_MODE", "").lower() in ("1", "true", "yes")
    if not _sim_mode:
        try:
            import json as _json
            _ss_path = os.getenv("SYSTEM_STATE_PATH", "config/system_state.json")
            with open(_ss_path) as _f:
                _sim_mode = _json.load(_f).get("simulation_mode", False)
        except (OSError, ValueError):
            pass
    enforce_network_security(conn=conn, simulation_mode=_sim_mode)

    submission = broker.submit_order(order_id, candidate)
    if submission.status != "submitted":
        # Persist rejected order for audit; do not lose broker failure context.
        persist_order(
            conn,
            order_id=order_id,
            decision_id=decision.decision_id,
            broker_order_id=submission.broker_order_id or "",
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            strategy_version=strategy_version,
            status="rejected",
        )
        reason_code = submission.reason_code or "EXEC_BROKER_REJECTED"
        insert_order_event(
            conn,
            order_id=order_id,
            event_type="rejected",
            from_status=None,
            to_status="rejected",
            source="broker",
            reason_code=reason_code,
            payload={"reason": submission.reason},
        )
        return ExecutionResult(
            ok=False,
            order_id=order_id,
            error_code=reason_code,
            error_message=submission.reason or "broker rejected order",
        )

    persist_order(
        conn,
        order_id=order_id,
        decision_id=decision.decision_id,
        broker_order_id=submission.broker_order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        price=price,
        strategy_version=strategy_version,
        status="submitted",
    )
    insert_order_event(
        conn,
        order_id=order_id,
        event_type="submitted",
        from_status=None,
        to_status="submitted",
        source="execution",
        reason_code=None,
        payload={"broker_order_id": submission.broker_order_id},
    )

    deadline = time.time() + poll_timeout_sec
    last_filled_qty = 0
    while time.time() < deadline:
        status = broker.poll_order_status(submission.broker_order_id)
        if status is None:
            time.sleep(poll_interval_sec)
            continue
        last_filled_qty = _apply_broker_status(
            conn=conn,
            order_id=order_id,
            broker_status=status,
            last_filled_qty=last_filled_qty,
        )
        if status.status in {"filled", "cancelled", "rejected", "expired"}:
            return ExecutionResult(ok=True, order_id=order_id)
        time.sleep(poll_interval_sec)

    insert_order_event(
        conn,
        order_id=order_id,
        event_type="cancel_requested",
        from_status=None,
        to_status=None,
        source="execution",
        reason_code="EXEC_TIMEOUT_CANCEL",
        payload={"poll_timeout_sec": poll_timeout_sec},
    )
    cancel_result = broker.cancel_order(submission.broker_order_id)
    if cancel_result.status == "submitted":
        transition_with_event(
            conn,
            order_id=order_id,
            next_status="cancelled",
            source="broker",
            reason_code="EXEC_TIMEOUT_CANCEL",
            payload={"broker_order_id": submission.broker_order_id},
        )
    else:
        reason_code = cancel_result.reason_code or "EXEC_CANCEL_FAILED"
        insert_order_event(
            conn,
            order_id=order_id,
            event_type="cancel_failed",
            from_status=None,
            to_status=None,
            source="broker",
            reason_code=reason_code,
            payload={"reason": cancel_result.reason},
        )
        return ExecutionResult(
            ok=False,
            order_id=order_id,
            error_code=reason_code,
            error_message=cancel_result.reason or "cancel failed",
        )
    return ExecutionResult(ok=True, order_id=order_id)


def _apply_broker_status(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    broker_status: BrokerOrderStatus,
    last_filled_qty: int,
) -> int:
    new_filled_qty = max(last_filled_qty, int(broker_status.filled_qty))
    delta = new_filled_qty - last_filled_qty
    if delta > 0:
        fill_id = str(uuid.uuid4())
        persist_fill(
            conn,
            fill_id=fill_id,
            order_id=order_id,
            qty=delta,
            price=broker_status.avg_fill_price,
            fee=broker_status.fee,
            tax=broker_status.tax,
        )
        insert_order_event(
            conn,
            order_id=order_id,
            event_type="fill",
            from_status=None,
            to_status=None,
            source="broker",
            reason_code=None,
            payload={
                "fill_id": fill_id,
                "delta_qty": delta,
                "cum_filled_qty": new_filled_qty,
                "avg_fill_price": broker_status.avg_fill_price,
            },
        )

    next_status = summarize_fill_status(conn, order_id)
    broker_terminal = broker_status.status in {"cancelled", "rejected", "expired"}
    if broker_terminal:
        next_status = broker_status.status
    transition_with_event(
        conn,
        order_id=order_id,
        next_status=next_status,
        source="broker",
        reason_code=broker_status.reason_code or None,
        payload={"broker_status": broker_status.status, "reason": broker_status.reason},
    )
    return new_filled_qty


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenClaw v1.1 risk gate demo.")
    parser.add_argument("--db", default="trades.db", help="(Deprecated) Handled by db_router")
    parser.add_argument("--resume", action="store_true", help="Execute /RESUME crash recovery flow")
    args = parser.parse_args()

    # Gap #7: Initialize execution tables specifically in the trades database
    init_execution_tables()
    
    if args.resume:
        success = run_resume_flow()
        print(f"Resume flow completed: {'Success' if success else 'Nothing to resume/Failed'}")
        return

    # Gap #6: Perform self check on boot
    check_result = system_self_check()
    if check_result["status"] == "needs_resume":
        print("WARNING: System was halted or crashed mid-trade.")
        print("Please run with --resume to cleanly restore system state.")
        return

    # Use db_router to get connection safely enforcing WAL mode
    conn = get_connection("trades")
    broker: BrokerAdapter = SimBrokerAdapter()

    decision = Decision(
        decision_id="demo-decision-001",
        ts_ms=int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000),
        symbol="2330",
        strategy_id="breakout",
        signal_side="buy",
        signal_score=0.78,
    )
    strategy_version = "strat_demo_v1_1"
    market = MarketState(best_bid=999.0, best_ask=1000.0, volume_1m=3000, feed_delay_ms=40)
    portfolio = PortfolioState(nav=1_000_000.0, cash=700_000.0, realized_pnl_today=0.0, unrealized_pnl=-2_000.0)
    portfolio = filter_locked_positions(portfolio)  # exclude long-term locked holdings
    system = SystemState(
        now_ms=int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=20,
        orders_last_60s=0,
        reduce_only_mode=False,
    )

    limits = load_limits(conn, LimitQuery(symbol=decision.symbol, strategy_id=decision.strategy_id))

    dd_policy = DrawdownPolicy()
    dd_result = evaluate_drawdown_guard(conn, dd_policy)
    st_result = evaluate_strategy_health_guard(conn, dd_policy, decision.strategy_id)
    if dd_result.risk_mode == "suspended" or st_result.risk_mode == "suspended":
        system.trading_locked = True
    elif dd_result.risk_mode == "reduce_only" or st_result.risk_mode == "reduce_only":
        system.reduce_only_mode = True

    # Cash mode evaluation (v4 #20 active cash mechanism)
    # In production, market regime result would come from market analysis
    # For demo purposes, create a neutral market regime result
    market_regime_result = MarketRegimeResult(
        regime=MarketRegime.RANGE,
        confidence=0.7,
        features={"trend_strength": 0.01, "volatility": 0.02},
        volatility_multiplier=1.0,
        risk_multipliers=None
    )
    
    # Evaluate cash mode
    cash_mode_manager = CashModeManager(db_path=args.db)
    cash_decision, system = cash_mode_manager.evaluate(market_regime_result, system)
    
    # Log cash mode status
    print(f"Cash mode evaluation: rating={cash_decision.rating:.1f}, cash_mode={cash_decision.cash_mode}, reason={cash_decision.reason_code}")

    result = evaluate_and_build_order(decision, market, portfolio, limits, system)

    try:
        conn.execute("BEGIN IMMEDIATE")
        persist_decision(conn, decision=decision, strategy_version=strategy_version)

        insert_risk_check(
            conn,
            decision_id=decision.decision_id,
            ts=utc_now_iso(),
            passed=result.approved,
            reject_code=result.reject_code,
            metrics={
                **result.metrics,
                "drawdown_mode": dd_result.risk_mode,
                "drawdown_reason": dd_result.reason_code,
                "strategy_health_mode": st_result.risk_mode,
                "strategy_health_reason": st_result.reason_code,
                "cash_mode_rating": cash_decision.rating,
                "cash_mode_active": cash_decision.cash_mode,
                "cash_mode_reason": cash_decision.reason_code
            },
            auto_commit=False,
        )

        if not result.approved:
            insert_incident(
                conn,
                ts=utc_now_iso(),
                severity="warn",
                source="risk",
                code=result.reject_code or "RISK_UNKNOWN",
                detail={"decision_id": decision.decision_id, "metrics": result.metrics},
                auto_commit=False,
            )
            conn.commit()
            print(f"REJECTED: {result.reject_code}")
            return

        execution_result = execute_approved_order(
            conn,
            broker=broker,
            decision=decision,
            strategy_version=strategy_version,
            symbol=result.order.symbol,
            side=result.order.side,
            qty=result.order.qty,
            price=result.order.price,
            candidate=result.order,
        )
        if not execution_result.ok:
            insert_incident(
                conn,
                ts=utc_now_iso(),
                severity="critical",
                source="execution",
                code=execution_result.error_code or "EXECUTION_TXN_FAILED",
                detail={
                    "decision_id": decision.decision_id,
                    "order_id": execution_result.order_id,
                    "error": execution_result.error_message,
                },
                auto_commit=False,
            )
            conn.commit()
            print(f"FAILED: {execution_result.error_code}: {execution_result.error_message}")
            return
        conn.commit()
        print(f"APPROVED: order_submitted={execution_result.order_id}")
    except Exception as exc:
        conn.rollback()
        error_text = str(exc)
        incident_code = "EXECUTION_TXN_FAILED"
        if ":" in error_text:
            maybe_code = error_text.split(":", 1)[0].strip()
            if maybe_code.isupper() and "_" in maybe_code:
                incident_code = maybe_code
        insert_incident(
            conn,
            ts=utc_now_iso(),
            severity="critical",
            source="execution",
            code=incident_code,
            detail={"decision_id": decision.decision_id, "error": str(exc)},
            auto_commit=True,
        )
        print(f"FAILED: {exc}")

    # Gap #6: Periodic position snapshot
    try:
        tracker = ResumeProtocolTracker()
        # Mocking positions list and cash for the snapshot based on current logic
        mock_positions = [{"symbol": portfolio.nav, "qty": 1}] # Simplification for demo
        tracker.snapshot(
            system_state_dict={"mode": "ok", "locked": system.trading_locked},
            positions_list=mock_positions,
            available_cash=portfolio.cash,
            reason="periodic"
        )
    except Exception as e:
        print(f"Failed to record snapshot: {e}")

if __name__ == "__main__":  # pragma: no cover
    main()
