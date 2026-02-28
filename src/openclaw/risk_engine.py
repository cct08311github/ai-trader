from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openclaw.position_sizing import calculate_position_qty


@dataclass
class Decision:
    decision_id: str
    ts_ms: int
    symbol: str
    strategy_id: str
    signal_side: str  # buy/sell/flat
    signal_score: float
    signal_ttl_ms: int = 30_000
    confidence: float = 1.0
    stop_price: Optional[float] = None
    volatility_multiplier: float = 1.0
    atr: Optional[float] = None
    atr_stop_multiple: float = 2.0


@dataclass
class MarketState:
    best_bid: float
    best_ask: float
    volume_1m: int
    feed_delay_ms: int


@dataclass
class Position:
    symbol: str
    qty: int
    avg_price: float
    last_price: float


@dataclass
class PortfolioState:
    nav: float
    cash: float
    realized_pnl_today: float
    unrealized_pnl: float
    positions: Dict[str, Position] = field(default_factory=dict)
    consecutive_losses: int = 0

    def position_value(self, symbol: str) -> float:
        pos = self.positions.get(symbol)
        if not pos:
            return 0.0
        return abs(pos.qty * pos.last_price)

    def gross_exposure(self) -> float:
        return sum(abs(p.qty * p.last_price) for p in self.positions.values()) / max(self.nav, 1.0)


@dataclass
class SystemState:
    now_ms: int
    trading_locked: bool
    broker_connected: bool
    db_write_p99_ms: int
    orders_last_60s: int
    reduce_only_mode: bool = False


@dataclass
class OrderCandidate:
    symbol: str
    side: str
    qty: int
    price: float
    order_type: str = "limit"
    tif: str = "IOC"
    opens_new_position: bool = True


@dataclass
class EvaluationResult:
    approved: bool
    reject_code: Optional[str] = None
    order: Optional[OrderCandidate] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


def _metrics(decision: Decision, market: MarketState, portfolio: PortfolioState, system_state: SystemState) -> Dict[str, Any]:
    return {
        "decision_id": decision.decision_id,
        "symbol": decision.symbol,
        "feed_delay_ms": market.feed_delay_ms,
        "orders_last_60s": system_state.orders_last_60s,
        "db_write_p99_ms": system_state.db_write_p99_ms,
        "gross_exposure": portfolio.gross_exposure(),
        "day_pnl": portfolio.realized_pnl_today + portfolio.unrealized_pnl,
    }


def _estimate_slippage_bps(candidate: OrderCandidate, market: MarketState) -> float:
    mid = (market.best_bid + market.best_ask) / 2
    if mid <= 0:
        return 9999.0
    return abs(candidate.price - mid) / mid * 10_000


def _build_candidate(decision: Decision, market: MarketState, portfolio: PortfolioState, limits: Dict[str, float]) -> Optional[OrderCandidate]:
    if decision.signal_side not in {"buy", "sell"}:
        return None

    mid = (market.best_bid + market.best_ask) / 2
    stop_price = decision.stop_price
    if stop_price is None:
        if decision.signal_side == "buy":
            stop_price = mid * (1 - limits["default_stop_pct"])
        else:
            stop_price = mid * (1 + limits["default_stop_pct"])

    authority_level = limits.get("authority_level")
    try:
        authority_level = int(authority_level) if authority_level is not None else None
    except Exception:
        authority_level = None

    qty = calculate_position_qty(
        nav=portfolio.nav,
        entry_price=mid,
        stop_price=stop_price,
        atr=decision.atr,
        atr_stop_multiple=decision.atr_stop_multiple,
        base_risk_pct=limits["max_loss_per_trade_pct_nav"],
        confidence=decision.confidence,
        confidence_threshold=limits.get("low_confidence_threshold", 0.60),
        low_confidence_scale=limits.get("low_confidence_scale", 0.50),
        volatility_multiplier=decision.volatility_multiplier,
        method=str(limits.get("position_sizing_method", "fixed_fractional")),
        authority_level=authority_level,
        sentinel_policy_path=str(limits.get("sentinel_policy_path", "config/sentinel_policy_v1.json")),
    )
    if qty <= 0:
        return None

    side = decision.signal_side
    pos = portfolio.positions.get(decision.symbol)
    opens_new = True
    if pos and ((side == "buy" and pos.qty < 0) or (side == "sell" and pos.qty > 0)):
        opens_new = False

    price = market.best_ask if side == "buy" else market.best_bid
    return OrderCandidate(
        symbol=decision.symbol,
        side=side,
        qty=qty,
        price=price,
        order_type="limit",
        tif="IOC",
        opens_new_position=opens_new,
    )


def evaluate_and_build_order(
    decision: Decision,
    market: MarketState,
    portfolio: PortfolioState,
    limits: Dict[str, float],
    system_state: SystemState,
    *,
    correlation_decision: Any | None = None,
    correlation_policy: Any | None = None,
) -> EvaluationResult:
    """
    Reference risk-engine flow for OpenClaw v1.1.
    `limits` is a flattened config dictionary.
    """

    base_metrics = _metrics(decision, market, portfolio, system_state)

    # Optional dynamic limits adjustment: correlation guard (v4 #22)
    if correlation_decision is not None:
        try:
            from openclaw.correlation_guard import apply_correlation_guard_to_limits

            limits = apply_correlation_guard_to_limits(limits, correlation_decision, policy=correlation_policy)
            base_metrics.update({
                "correlation_guard_ok": limits.get("correlation_guard_ok"),
                "correlation_guard_reason": limits.get("correlation_guard_reason"),
                "correlation_guard_scale": limits.get("correlation_guard_scale"),
            })
        except Exception as e:
            base_metrics["correlation_guard_error"] = str(e)


    if system_state.trading_locked:
        return EvaluationResult(False, "RISK_TRADING_LOCKED", metrics=base_metrics)

    if market.feed_delay_ms > limits["max_feed_delay_ms"]:
        return EvaluationResult(False, "RISK_DATA_STALENESS", metrics=base_metrics)

    if not system_state.broker_connected:
        return EvaluationResult(False, "RISK_BROKER_CONNECTIVITY", metrics=base_metrics)

    if system_state.db_write_p99_ms > limits["max_db_write_p99_ms"]:
        return EvaluationResult(False, "RISK_DB_WRITE_LATENCY", metrics=base_metrics)

    day_pnl = portfolio.realized_pnl_today + portfolio.unrealized_pnl
    if day_pnl <= -(limits["max_daily_loss_pct"] * portfolio.nav):
        return EvaluationResult(False, "RISK_DAILY_LOSS_LIMIT", metrics=base_metrics)

    if system_state.orders_last_60s >= int(limits["max_orders_per_min"]):
        return EvaluationResult(False, "RISK_ORDER_RATE_LIMIT", metrics=base_metrics)

    if system_state.now_ms - decision.ts_ms > decision.signal_ttl_ms:
        return EvaluationResult(False, "RISK_DATA_STALENESS", metrics=base_metrics)

    candidate = _build_candidate(decision, market, portfolio, limits)
    if not candidate:
        return EvaluationResult(False, "RISK_LIQUIDITY_LIMIT", metrics=base_metrics)

    if system_state.reduce_only_mode and candidate.opens_new_position:
        return EvaluationResult(False, "RISK_CONSECUTIVE_LOSSES", metrics=base_metrics)

    mid = (market.best_bid + market.best_ask) / 2
    price_dev_pct = abs(candidate.price - mid) / max(mid, 0.01)
    if price_dev_pct > limits["max_price_deviation_pct"]:
        m = dict(base_metrics)
        m["price_dev_pct"] = price_dev_pct
        return EvaluationResult(False, "RISK_PRICE_DEVIATION_LIMIT", metrics=m)

    slippage_bps = _estimate_slippage_bps(candidate, market)
    if slippage_bps > limits["max_slippage_bps"]:
        m = dict(base_metrics)
        m["slippage_bps"] = slippage_bps
        return EvaluationResult(False, "RISK_SLIPPAGE_ESTIMATE_LIMIT", metrics=m)

    max_qty = int(market.volume_1m * limits["max_qty_to_1m_volume_ratio"])
    if candidate.qty > max_qty:
        if int(limits.get("allow_auto_reduce_qty", 1)) == 1 and max_qty > 0:
            candidate.qty = max_qty
        else:
            return EvaluationResult(False, "RISK_LIQUIDITY_LIMIT", metrics=base_metrics)

    symbol_value_after = portfolio.position_value(decision.symbol) + candidate.qty * candidate.price
    symbol_weight_after = symbol_value_after / max(portfolio.nav, 1.0)
    if symbol_weight_after > limits["max_symbol_weight"]:
        m = dict(base_metrics)
        m["symbol_weight_after"] = symbol_weight_after
        return EvaluationResult(False, "RISK_POSITION_CONCENTRATION", metrics=m)

    gross_after = portfolio.gross_exposure() + (candidate.qty * candidate.price / max(portfolio.nav, 1.0))
    if gross_after > limits["max_gross_exposure"]:
        m = dict(base_metrics)
        m["gross_after"] = gross_after
        return EvaluationResult(False, "RISK_PORTFOLIO_EXPOSURE_LIMIT", metrics=m)

    est_trade_loss = candidate.qty * candidate.price * limits["default_stop_pct"]
    if est_trade_loss > (limits["max_loss_per_trade_pct_nav"] * portfolio.nav):
        return EvaluationResult(False, "RISK_PER_TRADE_LOSS_LIMIT", metrics=base_metrics)

    return EvaluationResult(True, order=candidate, metrics=base_metrics)


def default_limits() -> Dict[str, float]:
    return {
        "max_daily_loss_pct": 0.05,
        "max_loss_per_trade_pct_nav": 0.005,
        "low_confidence_threshold": 0.60,
        "low_confidence_scale": 0.50,
        "max_orders_per_min": 3,
        "max_price_deviation_pct": 0.02,
        "max_slippage_bps": 12,
        "max_qty_to_1m_volume_ratio": 0.15,
        "max_feed_delay_ms": 1000,
        "max_db_write_p99_ms": 200,
        "max_symbol_weight": 0.20,
        "max_gross_exposure": 1.20,
        "max_consecutive_losses": 3,
        "default_stop_pct": 0.015,
        "allow_auto_reduce_qty": 1,
        "position_sizing_method": "fixed_fractional",
        "sentinel_policy_path": "config/sentinel_policy_v1.json",
    }
