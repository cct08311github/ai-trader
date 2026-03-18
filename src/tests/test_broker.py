import time
from unittest.mock import MagicMock, patch, PropertyMock

from openclaw.broker import (
    map_shioaji_error_to_reason_code,
    map_shioaji_exec_status,
    SimBrokerAdapter,
    ShioajiAdapter,
    BrokerSubmission,
    BrokerOrderStatus,
)
from openclaw.risk_engine import OrderCandidate


def test_map_known_code():
    assert map_shioaji_error_to_reason_code("TOKEN_EXPIRED", "token expired") == "EXEC_BROKER_AUTH"


def test_map_message_fallback():
    assert map_shioaji_error_to_reason_code(None, "network connection reset") == "EXEC_NETWORK_ERROR"


def test_map_price_error():
    assert map_shioaji_error_to_reason_code(None, "invalid price tick") == "RISK_PRICE_DEVIATION_LIMIT"


def test_map_exec_status_partial():
    assert map_shioaji_exec_status("part_filled") == "partially_filled"


# ========== SimBrokerAdapter Tests ==========

def test_sim_broker_adapter_submit_order():
    """Test SimBrokerAdapter submit_order creates order correctly."""
    adapter = SimBrokerAdapter()
    candidate = OrderCandidate(
        symbol="2330.TW",
        side="buy",
        qty=1000,
        price=580.0,
        order_type="limit",
        tif="day",
    )
    result = adapter.submit_order("order-123", candidate)
    
    assert isinstance(result, BrokerSubmission)
    assert result.broker_order_id.startswith("SIM-order-123")
    assert result.status == "submitted"
    assert result.reason == ""
    assert result.reason_code == ""


def test_sim_broker_adapter_poll_order_status():
    """Test SimBrokerAdapter poll_order_status transitions through states."""
    adapter = SimBrokerAdapter()
    candidate = OrderCandidate(
        symbol="2330.TW",
        side="buy",
        qty=1000,
        price=580.0,
        order_type="limit",
        tif="day",
    )
    submission = adapter.submit_order("order-123", candidate)
    
    # First poll: partially filled — buy side: fee=0.1425%, no tax
    status1 = adapter.poll_order_status(submission.broker_order_id)
    assert isinstance(status1, BrokerOrderStatus)
    assert status1.status == "partially_filled"
    assert status1.filled_qty == 500  # half of 1000
    assert status1.avg_fill_price == 580.0
    # 500 * 580.0 * 0.001425 = 413.25
    assert status1.fee == round(500 * 580.0 * 0.001425, 2)
    assert status1.tax == 0.0   # buy 無證交稅

    # Second poll: filled
    status2 = adapter.poll_order_status(submission.broker_order_id)
    assert status2.status == "filled"
    assert status2.filled_qty == 1000
    # 1000 * 580.0 * 0.001425 = 826.5
    assert status2.fee == round(1000 * 580.0 * 0.001425, 2)
    assert status2.tax == 0.0   # buy 無證交稅
    
    # Third poll: still filled (should remain filled)
    status3 = adapter.poll_order_status(submission.broker_order_id)
    assert status3.status == "filled"
    assert status3.filled_qty == 1000


def test_sim_broker_adapter_poll_nonexistent_order():
    """Test poll_order_status returns None for non-existent order."""
    adapter = SimBrokerAdapter()
    status = adapter.poll_order_status("NONEXISTENT")
    assert status is None


def test_sim_broker_adapter_cancel_order():
    """Test SimBrokerAdapter cancel_order marks order as cancelled."""
    adapter = SimBrokerAdapter()
    candidate = OrderCandidate(
        symbol="2330.TW",
        side="buy",
        qty=1000,
        price=580.0,
        order_type="limit",
        tif="day",
    )
    submission = adapter.submit_order("order-123", candidate)
    
    # Cancel the order
    cancel_result = adapter.cancel_order(submission.broker_order_id)
    assert isinstance(cancel_result, BrokerSubmission)
    assert cancel_result.status == "submitted"
    
    # Poll after cancellation should return cancelled status
    status = adapter.poll_order_status(submission.broker_order_id)
    assert status.status == "cancelled"


def test_sim_broker_adapter_cancel_nonexistent_order():
    """Test cancel_order returns rejected for non-existent order."""
    adapter = SimBrokerAdapter()
    result = adapter.cancel_order("NONEXISTENT")
    assert result.status == "rejected"
    assert result.reason == "order not found"
    assert result.reason_code == "EXEC_BROKER_UNKNOWN"


# ---------------------------------------------------------------------------
# map_shioaji_error_to_reason_code — remaining branch coverage
# ---------------------------------------------------------------------------

def test_map_auth_failed_code():
    assert map_shioaji_error_to_reason_code("AUTH_FAILED", "") == "EXEC_BROKER_AUTH"


def test_map_no_permission_code():
    assert map_shioaji_error_to_reason_code("NO_PERMISSION", "") == "EXEC_BROKER_PERMISSION"


def test_map_order_rejected_code():
    assert map_shioaji_error_to_reason_code("ORDER_REJECTED", "") == "EXEC_BROKER_REJECTED"


def test_map_insufficient_balance_code():
    assert map_shioaji_error_to_reason_code("INSUFFICIENT_BALANCE", "") == "EXEC_INSUFFICIENT_BALANCE"


def test_map_invalid_price_code():
    assert map_shioaji_error_to_reason_code("INVALID_PRICE", "") == "RISK_PRICE_DEVIATION_LIMIT"


def test_map_invalid_qty_code():
    assert map_shioaji_error_to_reason_code("INVALID_QTY", "") == "RISK_LIQUIDITY_LIMIT"


def test_map_rate_limit_code():
    assert map_shioaji_error_to_reason_code("RATE_LIMIT", "") == "EXEC_BROKER_RATE_LIMIT"


def test_map_timeout_code():
    assert map_shioaji_error_to_reason_code("TIMEOUT", "") == "EXEC_NETWORK_TIMEOUT"


def test_map_network_error_code():
    assert map_shioaji_error_to_reason_code("NETWORK_ERROR", "") == "EXEC_NETWORK_ERROR"


def test_map_message_auth():
    assert map_shioaji_error_to_reason_code(None, "auth failed") == "EXEC_BROKER_AUTH"


def test_map_message_token():
    assert map_shioaji_error_to_reason_code(None, "token invalid") == "EXEC_BROKER_AUTH"


def test_map_message_balance():
    assert map_shioaji_error_to_reason_code(None, "balance not enough") == "EXEC_INSUFFICIENT_BALANCE"


def test_map_message_insufficient():
    assert map_shioaji_error_to_reason_code(None, "insufficient funds") == "EXEC_INSUFFICIENT_BALANCE"


def test_map_message_rate_limit():
    assert map_shioaji_error_to_reason_code(None, "rate limit exceeded") == "EXEC_BROKER_RATE_LIMIT"


def test_map_message_timeout():
    assert map_shioaji_error_to_reason_code(None, "request timeout") == "EXEC_NETWORK_TIMEOUT"


def test_map_message_unknown():
    assert map_shioaji_error_to_reason_code(None, "completely unknown error xyz") == "EXEC_BROKER_UNKNOWN"


# ---------------------------------------------------------------------------
# map_shioaji_exec_status — all branches
# ---------------------------------------------------------------------------

def test_exec_status_submitted():
    assert map_shioaji_exec_status("submitted") == "submitted"


def test_exec_status_pending():
    assert map_shioaji_exec_status("pending") == "submitted"


def test_exec_status_partial_filled():
    assert map_shioaji_exec_status("partial_filled") == "partially_filled"


def test_exec_status_filled():
    assert map_shioaji_exec_status("filled") == "filled"


def test_exec_status_deal():
    assert map_shioaji_exec_status("deal") == "filled"


def test_exec_status_cancelled():
    assert map_shioaji_exec_status("cancelled") == "cancelled"


def test_exec_status_canceled():
    assert map_shioaji_exec_status("canceled") == "cancelled"


def test_exec_status_failed():
    assert map_shioaji_exec_status("failed") == "rejected"


def test_exec_status_rejected():
    assert map_shioaji_exec_status("rejected") == "rejected"


def test_exec_status_expired():
    assert map_shioaji_exec_status("expired") == "expired"


def test_exec_status_unknown():
    assert map_shioaji_exec_status("some_unknown_status") == "submitted"


def test_exec_status_empty():
    assert map_shioaji_exec_status("") == "submitted"


# ---------------------------------------------------------------------------
# ShioajiAdapter — mocked API
# ---------------------------------------------------------------------------

def _make_mock_api(broker_id="SHIOAJI-ord-1", status_str="submitted",
                   deal_qty=0, avg_price=0.0):
    """Build a minimal mock shioaji API."""
    api = MagicMock()

    trade_status = MagicMock()
    trade_status.id = broker_id
    trade_status.status = status_str
    trade_status.deal_quantity = deal_qty
    trade_status.avg_price = avg_price

    trade = MagicMock()
    trade.status = trade_status

    api.place_order.return_value = trade
    api.Order.return_value = MagicMock()
    api.Contracts.Stocks.__getitem__ = MagicMock(return_value=MagicMock())
    return api, trade


def _make_candidate(side="buy", order_type="limit", tif="ROD"):
    return OrderCandidate(
        symbol="2330.TW",
        side=side,
        qty=1000,
        price=580.0,
        order_type=order_type,
        tif=tif,
    )


def test_shioaji_adapter_init():
    api = MagicMock()
    account = MagicMock()
    adapter = ShioajiAdapter(api, account, poll_interval_sec=0.1, max_poll_seconds=1.0)
    assert adapter.api is api
    assert adapter.account is account
    assert adapter.poll_interval_sec == 0.1
    assert adapter.max_poll_seconds == 1.0
    assert adapter._trades == {}


def test_shioaji_adapter_submit_order_success():
    api, trade = _make_mock_api(broker_id="SJ-001")
    adapter = ShioajiAdapter(api, MagicMock())
    candidate = _make_candidate(side="buy", order_type="limit", tif="ROD")
    result = adapter.submit_order("ord-1", candidate)
    assert result.status == "submitted"
    assert result.broker_order_id == "SJ-001"
    assert "SJ-001" in adapter._trades


def test_shioaji_adapter_submit_order_sell_market():
    """Sell + market order → different Action and price_type."""
    api, trade = _make_mock_api(broker_id="SJ-002")
    adapter = ShioajiAdapter(api, MagicMock())
    candidate = _make_candidate(side="sell", order_type="market", tif="FOK")
    result = adapter.submit_order("ord-2", candidate)
    assert result.status == "submitted"
    # Check api.Order was called with correct action/price_type
    call_kwargs = api.Order.call_args.kwargs
    assert call_kwargs["action"] == "Sell"
    assert call_kwargs["price_type"] == "MKT"
    assert call_kwargs["order_type"] == "FOK"


def test_shioaji_adapter_submit_order_fallback_id():
    """When trade.status.id is empty, fall back to SHIOAJI-<order_id>."""
    api, trade = _make_mock_api(broker_id="")
    adapter = ShioajiAdapter(api, MagicMock())
    candidate = _make_candidate()
    result = adapter.submit_order("ord-99", candidate)
    assert result.broker_order_id == "SHIOAJI-ord-99"


def test_shioaji_adapter_submit_order_exception():
    api = MagicMock()
    exc = Exception("rate limit exceeded")
    api.Order.side_effect = exc
    adapter = ShioajiAdapter(api, MagicMock())
    result = adapter.submit_order("ord-err", _make_candidate())
    assert result.status == "rejected"
    assert "rate limit exceeded" in result.reason
    assert result.reason_code == "EXEC_BROKER_RATE_LIMIT"


def test_shioaji_adapter_submit_order_exception_with_code():
    api = MagicMock()
    exc = Exception("auth error")
    exc.code = "TOKEN_EXPIRED"
    api.Order.side_effect = exc
    adapter = ShioajiAdapter(api, MagicMock())
    result = adapter.submit_order("ord-auth", _make_candidate())
    assert result.status == "rejected"
    assert result.reason_code == "EXEC_BROKER_AUTH"


def test_shioaji_adapter_poll_order_status_none_if_not_found():
    api = MagicMock()
    adapter = ShioajiAdapter(api, MagicMock())
    result = adapter.poll_order_status("NOT_EXIST")
    assert result is None


def test_shioaji_adapter_poll_order_status_success():
    api, trade = _make_mock_api(broker_id="SJ-100", status_str="filled", deal_qty=1000, avg_price=580.0)
    adapter = ShioajiAdapter(api, MagicMock())
    adapter._trades["SJ-100"] = {"trade": trade, "side": "buy"}
    result = adapter.poll_order_status("SJ-100")
    assert result is not None
    assert result.status == "filled"
    assert result.filled_qty == 1000
    assert result.avg_fill_price == 580.0
    api.update_status.assert_called_once()


def test_shioaji_adapter_poll_order_status_exception():
    api = MagicMock()
    api.update_status.side_effect = Exception("network connection reset")
    trade = MagicMock()
    adapter = ShioajiAdapter(api, MagicMock())
    adapter._trades["SJ-200"] = {"trade": trade, "side": "buy"}
    result = adapter.poll_order_status("SJ-200")
    assert result is not None
    assert result.status == "rejected"
    assert result.reason_code == "EXEC_NETWORK_ERROR"


def test_shioaji_adapter_cancel_order_not_found():
    api = MagicMock()
    adapter = ShioajiAdapter(api, MagicMock())
    result = adapter.cancel_order("UNKNOWN")
    assert result.status == "rejected"
    assert result.reason == "order not found"
    assert result.reason_code == "EXEC_BROKER_UNKNOWN"


def test_shioaji_adapter_cancel_order_success():
    api, trade = _make_mock_api()
    adapter = ShioajiAdapter(api, MagicMock())
    adapter._trades["SJ-300"] = {"trade": trade, "side": "buy"}
    result = adapter.cancel_order("SJ-300")
    assert result.status == "submitted"
    api.cancel_order.assert_called_once_with(trade)


def test_shioaji_adapter_cancel_order_exception():
    api = MagicMock()
    api.cancel_order.side_effect = Exception("timeout")
    trade = MagicMock()
    adapter = ShioajiAdapter(api, MagicMock())
    adapter._trades["SJ-400"] = {"trade": trade, "side": "buy"}
    result = adapter.cancel_order("SJ-400")
    assert result.status == "rejected"
    assert result.reason_code == "EXEC_NETWORK_TIMEOUT"


# ---------------------------------------------------------------------------
# ShioajiAdapter.wait_for_terminal
# ---------------------------------------------------------------------------

def test_wait_for_terminal_returns_filled_immediately():
    """When first poll returns 'filled', we get it back without looping."""
    api, trade = _make_mock_api(broker_id="SJ-T1", status_str="filled", deal_qty=1000, avg_price=580.0)
    adapter = ShioajiAdapter(api, MagicMock(), poll_interval_sec=0.01, max_poll_seconds=2.0)
    adapter._trades["SJ-T1"] = {"trade": trade, "side": "buy"}

    with patch("openclaw.broker.time.sleep") as mock_sleep:
        result = adapter.wait_for_terminal("SJ-T1")

    assert result.status == "filled"


def test_wait_for_terminal_returns_cancelled():
    """Simulate poll returning cancelled on second call."""
    api = MagicMock()
    account = MagicMock()

    trade_status = MagicMock()
    trade_status.status = "cancelled"
    trade_status.deal_quantity = 0
    trade_status.avg_price = 0.0
    trade = MagicMock()
    trade.status = trade_status

    api.update_status.return_value = None
    adapter = ShioajiAdapter(api, account, poll_interval_sec=0.01, max_poll_seconds=2.0)
    adapter._trades["SJ-CANCEL"] = {"trade": trade, "side": "buy"}

    with patch("openclaw.broker.time.sleep"):
        result = adapter.wait_for_terminal("SJ-CANCEL")

    assert result.status == "cancelled"


def test_wait_for_terminal_times_out_returns_latest():
    """When poll_order_status always returns non-terminal, deadline expires → returns latest."""
    api = MagicMock()
    account = MagicMock()

    trade_status = MagicMock()
    trade_status.status = "submitted"
    trade_status.deal_quantity = 0
    trade_status.avg_price = 0.0
    trade = MagicMock()
    trade.status = trade_status

    api.update_status.return_value = None
    adapter = ShioajiAdapter(api, account, poll_interval_sec=0.01, max_poll_seconds=0.0)
    adapter._trades["SJ-SLOW"] = {"trade": trade, "side": "buy"}

    # With max_poll_seconds=0, deadline is already in the past
    result = adapter.wait_for_terminal("SJ-SLOW")
    # Returns the initial status ("submitted")
    assert result.broker_order_id == "SJ-SLOW"


def test_wait_for_terminal_poll_returns_none():
    """When poll returns None (trade removed mid-loop), loop continues until deadline."""
    api = MagicMock()
    adapter = ShioajiAdapter(api, MagicMock(), poll_interval_sec=0.01, max_poll_seconds=0.05)
    # No trade in _trades → poll_order_status returns None

    with patch("openclaw.broker.time.sleep"):
        result = adapter.wait_for_terminal("SJ-GONE")

    # Returns initial "submitted" latest
    assert result.status == "submitted"
