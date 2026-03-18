from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any
from typing import Protocol

from .risk_engine import OrderCandidate

log = logging.getLogger(__name__)

_MAX_SUBMIT_RETRIES = 3
_RETRY_BASE_SEC = 1.0


@dataclass
class BrokerSubmission:
    broker_order_id: str
    status: str  # submitted/rejected
    reason: str = ""
    reason_code: str = ""


@dataclass
class BrokerFill:
    fill_id: str
    qty: int
    price: float
    fee: float
    tax: float


@dataclass
class BrokerOrderStatus:
    broker_order_id: str
    status: str  # submitted/partially_filled/filled/cancelled/rejected/expired
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    fee: float = 0.0
    tax: float = 0.0
    reason: str = ""
    reason_code: str = ""


class BrokerAdapter(Protocol):
    def submit_order(self, order_id: str, candidate: OrderCandidate) -> BrokerSubmission:
        ...

    def poll_order_status(self, broker_order_id: str) -> BrokerOrderStatus | None:
        ...

    def cancel_order(self, broker_order_id: str) -> BrokerSubmission:
        ...


class SimBrokerAdapter:
    """
    Reference broker adapter for local integration testing.
    """
    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._poll_count: dict[str, int] = {}

    def submit_order(self, order_id: str, candidate: OrderCandidate) -> BrokerSubmission:
        broker_order_id = f"SIM-{order_id}"
        self._orders[broker_order_id] = {
            "qty": candidate.qty,
            "price": candidate.price,
            "side": candidate.side,
            "cancelled": False,
        }
        self._poll_count[broker_order_id] = 0
        return BrokerSubmission(broker_order_id=broker_order_id, status="submitted")

    def poll_order_status(self, broker_order_id: str) -> BrokerOrderStatus | None:
        order = self._orders.get(broker_order_id)
        if not order:
            return None
        if order["cancelled"]:
            return BrokerOrderStatus(
                broker_order_id=broker_order_id,
                status="cancelled",
            )

        cnt = self._poll_count.get(broker_order_id, 0) + 1
        self._poll_count[broker_order_id] = cnt
        qty = int(order["qty"])
        price = float(order["price"])
        side = order["side"]

        # 台股實際手續費：0.1425%（買賣），證交稅：0.3%（僅 sell）
        _COMMISSION_RATE = 0.001425
        _TAX_RATE_SELL = 0.003

        if cnt == 1:
            partial_qty = max(1, qty // 2)
            partial_value = price * partial_qty
            fee = round(partial_value * _COMMISSION_RATE, 2)
            tax = round(partial_value * _TAX_RATE_SELL, 2) if side == "sell" else 0.0
            return BrokerOrderStatus(
                broker_order_id=broker_order_id,
                status="partially_filled",
                filled_qty=partial_qty,
                avg_fill_price=price,
                fee=fee,
                tax=tax,
            )
        full_value = price * qty
        fee = round(full_value * _COMMISSION_RATE, 2)
        tax = round(full_value * _TAX_RATE_SELL, 2) if side == "sell" else 0.0
        return BrokerOrderStatus(
            broker_order_id=broker_order_id,
            status="filled",
            filled_qty=qty,
            avg_fill_price=price,
            fee=fee,
            tax=tax,
        )

    def cancel_order(self, broker_order_id: str) -> BrokerSubmission:
        order = self._orders.get(broker_order_id)
        if not order:
            return BrokerSubmission(
                broker_order_id=broker_order_id,
                status="rejected",
                reason="order not found",
                reason_code="EXEC_BROKER_UNKNOWN",
            )
        order["cancelled"] = True
        return BrokerSubmission(broker_order_id=broker_order_id, status="submitted")


def map_shioaji_error_to_reason_code(raw_code: str | None, raw_message: str) -> str:
    """
    Map broker/library errors to internal execution/risk reason codes.
    """
    code = (raw_code or "").upper()
    msg = (raw_message or "").upper()

    code_map = {
        "TOKEN_EXPIRED": "EXEC_BROKER_AUTH",
        "AUTH_FAILED": "EXEC_BROKER_AUTH",
        "NO_PERMISSION": "EXEC_BROKER_PERMISSION",
        "ORDER_REJECTED": "EXEC_BROKER_REJECTED",
        "INSUFFICIENT_BALANCE": "EXEC_INSUFFICIENT_BALANCE",
        "INVALID_PRICE": "RISK_PRICE_DEVIATION_LIMIT",
        "INVALID_QTY": "RISK_LIQUIDITY_LIMIT",
        "RATE_LIMIT": "EXEC_BROKER_RATE_LIMIT",
        "TIMEOUT": "EXEC_NETWORK_TIMEOUT",
        "NETWORK_ERROR": "EXEC_NETWORK_ERROR",
    }
    if code in code_map:
        return code_map[code]

    if "AUTH" in msg or "TOKEN" in msg:
        return "EXEC_BROKER_AUTH"
    if "BALANCE" in msg or "INSUFFICIENT" in msg:
        return "EXEC_INSUFFICIENT_BALANCE"
    if "RATE" in msg and "LIMIT" in msg:
        return "EXEC_BROKER_RATE_LIMIT"
    if "TIMEOUT" in msg:
        return "EXEC_NETWORK_TIMEOUT"
    if "NETWORK" in msg or "CONNECTION" in msg:
        return "EXEC_NETWORK_ERROR"
    if "PRICE" in msg:
        return "RISK_PRICE_DEVIATION_LIMIT"
    return "EXEC_BROKER_UNKNOWN"


class ShioajiAdapter:
    """
    Template adapter for real Sinopac Shioaji integration.
    `api` should be an authenticated shioaji.Shioaji instance.
    """

    def __init__(
        self,
        api: Any,
        account: Any,
        *,
        poll_interval_sec: float = 0.5,
        max_poll_seconds: float = 5.0,
    ):
        self.api = api
        self.account = account
        self.poll_interval_sec = poll_interval_sec
        self.max_poll_seconds = max_poll_seconds
        self._trades: dict[str, Any] = {}

    def submit_order(self, order_id: str, candidate: OrderCandidate) -> BrokerSubmission:
        last_exc: Exception | None = None
        for attempt in range(_MAX_SUBMIT_RETRIES):
            try:
                # These fields are intentionally explicit for auditability.
                order = self.api.Order(
                    price=candidate.price,
                    quantity=candidate.qty,
                    action="Buy" if candidate.side == "buy" else "Sell",
                    price_type="LMT" if candidate.order_type == "limit" else "MKT",
                    order_type="ROD" if candidate.tif == "ROD" else candidate.tif,
                    order_lot="Common",
                    custom_field=order_id,
                )
                # NOTE: Replace contract lookup strategy as needed for futures/options.
                contract = self.api.Contracts.Stocks[candidate.symbol]
                trade = self.api.place_order(contract, order)

                broker_order_id = getattr(trade.status, "id", "") or f"SHIOAJI-{order_id}"
                self._trades[broker_order_id] = {"trade": trade, "side": candidate.side}
                return BrokerSubmission(broker_order_id=broker_order_id, status="submitted")
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_SUBMIT_RETRIES - 1:
                    time.sleep(_RETRY_BASE_SEC * (2 ** attempt))
                    log.warning(
                        "submit_order retry %d/%d for %s: %s",
                        attempt + 1, _MAX_SUBMIT_RETRIES, candidate.symbol, exc,
                    )
        raw_code = getattr(last_exc, "code", None)
        reason_code = map_shioaji_error_to_reason_code(raw_code, str(last_exc))
        return BrokerSubmission(
            broker_order_id="",
            status="rejected",
            reason=str(last_exc),
            reason_code=reason_code,
        )

    def poll_order_status(self, broker_order_id: str) -> BrokerOrderStatus | None:
        """
        Query latest broker status for an order.
        """
        try:
            entry = self._trades.get(broker_order_id)
            if entry is None:
                return None

            trade = entry["trade"]
            side = entry["side"]

            self.api.update_status(self.account)
            raw_status = str(getattr(trade.status, "status", "")).lower()
            mapped_status = map_shioaji_exec_status(raw_status)
            filled_qty = int(getattr(trade.status, "deal_quantity", 0) or 0)
            avg_price = float(getattr(trade.status, "avg_price", 0.0) or 0.0)

            # 台股交易成本：手續費 0.1425%（買賣雙向），證交稅 0.3%（sell only）
            _COMMISSION_RATE = 0.001425
            _TAX_RATE_SELL = 0.003
            trade_value = avg_price * filled_qty
            fee = round(trade_value * _COMMISSION_RATE)
            tax = round(trade_value * _TAX_RATE_SELL) if side == "sell" else 0

            return BrokerOrderStatus(
                broker_order_id=broker_order_id,
                status=mapped_status,
                filled_qty=filled_qty,
                avg_fill_price=avg_price,
                fee=float(fee),
                tax=float(tax),
            )
        except Exception as exc:
            reason_code = map_shioaji_error_to_reason_code(getattr(exc, "code", None), str(exc))
            return BrokerOrderStatus(
                broker_order_id=broker_order_id,
                status="rejected",
                reason=str(exc),
                reason_code=reason_code,
            )

    def cancel_order(self, broker_order_id: str) -> BrokerSubmission:
        try:
            entry = self._trades.get(broker_order_id)
            if entry is None:
                return BrokerSubmission(
                    broker_order_id=broker_order_id,
                    status="rejected",
                    reason="order not found",
                    reason_code="EXEC_BROKER_UNKNOWN",
                )
            trade = entry["trade"]
            self.api.cancel_order(trade)
            return BrokerSubmission(
                broker_order_id=broker_order_id,
                status="submitted",
            )
        except Exception as exc:
            reason_code = map_shioaji_error_to_reason_code(getattr(exc, "code", None), str(exc))
            return BrokerSubmission(
                broker_order_id=broker_order_id,
                status="rejected",
                reason=str(exc),
                reason_code=reason_code,
            )

    def wait_for_terminal(self, broker_order_id: str) -> BrokerOrderStatus:
        deadline = time.time() + self.max_poll_seconds
        latest = BrokerOrderStatus(broker_order_id=broker_order_id, status="submitted")
        while time.time() < deadline:
            status = self.poll_order_status(broker_order_id)
            if status is not None:
                latest = status
                if status.status in {"filled", "cancelled", "rejected", "expired"}:
                    return status
            time.sleep(self.poll_interval_sec)
        return latest


def map_shioaji_exec_status(raw_status: str) -> str:
    status = (raw_status or "").lower()
    if status in {"submitted", "pending", "part_filled", "partial_filled"}:
        if status in {"part_filled", "partial_filled"}:
            return "partially_filled"
        return "submitted"
    if status in {"filled", "deal"}:
        return "filled"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"failed", "rejected"}:
        return "rejected"
    if status in {"expired"}:
        return "expired"
    return "submitted"
