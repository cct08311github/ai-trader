"""ShioajiAdapter 測試 — retry + partial fill + error mapping。"""
import pytest
from unittest.mock import MagicMock, patch
from openclaw.broker import ShioajiAdapter, BrokerSubmission, BrokerOrderStatus
from openclaw.risk_engine import OrderCandidate


def _make_adapter():
    mock_api = MagicMock()
    mock_account = MagicMock()
    return ShioajiAdapter(api=mock_api, account=mock_account)


def test_poll_order_status_filled():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.status = "Filled"
    mock_trade.status.deal_quantity = 100
    mock_trade.status.avg_price = 600.0
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "buy"}
    result = adapter.poll_order_status("test-oid")
    assert result is not None
    assert result.status == "filled"
    assert result.filled_qty == 100
    # fee = round(600.0 * 100 * 0.001425) = round(85.5) = 86; tax = 0 (buy)
    assert result.fee == round(600.0 * 100 * 0.001425)
    assert result.tax == 0


def test_poll_order_status_filled_sell():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.status = "Filled"
    mock_trade.status.deal_quantity = 100
    mock_trade.status.avg_price = 600.0
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "sell"}
    result = adapter.poll_order_status("test-oid")
    assert result is not None
    assert result.status == "filled"
    # fee = round(600.0 * 100 * 0.001425); tax = round(600.0 * 100 * 0.003)
    assert result.fee == round(600.0 * 100 * 0.001425)
    assert result.tax == round(600.0 * 100 * 0.003)


def test_poll_order_status_partial():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.status = "Part_Filled"
    mock_trade.status.deal_quantity = 50
    mock_trade.status.avg_price = 600.0
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "buy"}
    result = adapter.poll_order_status("test-oid")
    assert result is not None
    assert result.status == "partially_filled"
    assert result.filled_qty == 50


def test_poll_order_status_unknown():
    adapter = _make_adapter()
    assert adapter.poll_order_status("nonexistent") is None


def test_submit_order_success():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.id = "SHIOAJI-123"
    adapter.api.place_order.return_value = mock_trade
    candidate = OrderCandidate(symbol="2330", side="buy", qty=100, price=600.0, order_type="limit", tif="ROD")
    result = adapter.submit_order("order-1", candidate)
    assert isinstance(result, BrokerSubmission)
    assert result.status == "submitted"


def test_submit_order_with_retry():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.id = "SHIOAJI-456"
    adapter.api.place_order.side_effect = [Exception("timeout"), Exception("timeout"), mock_trade]
    candidate = OrderCandidate(symbol="2330", side="buy", qty=100, price=600.0)
    with patch("time.sleep"):
        result = adapter.submit_order("order-2", candidate)
    assert result.status == "submitted"
    assert adapter.api.place_order.call_count == 3


def test_submit_order_gives_up():
    adapter = _make_adapter()
    adapter.api.place_order.side_effect = Exception("persistent failure")
    candidate = OrderCandidate(symbol="2330", side="buy", qty=100, price=600.0)
    with patch("time.sleep"):
        result = adapter.submit_order("order-3", candidate)
    assert result.status == "rejected"
    assert adapter.api.place_order.call_count == 3


# ---------------------------------------------------------------------------
# map_shioaji_error_to_reason_code tests
# ---------------------------------------------------------------------------
from openclaw.broker import map_shioaji_error_to_reason_code


def test_error_mapping_auth_by_code():
    """Auth-related error code → EXEC_BROKER_AUTH."""
    assert map_shioaji_error_to_reason_code("AUTH_FAILED", "") == "EXEC_BROKER_AUTH"


def test_error_mapping_token_expired_by_code():
    """TOKEN_EXPIRED error code → EXEC_BROKER_AUTH."""
    assert map_shioaji_error_to_reason_code("TOKEN_EXPIRED", "") == "EXEC_BROKER_AUTH"


def test_error_mapping_insufficient_balance():
    """Insufficient funds by code → EXEC_INSUFFICIENT_BALANCE."""
    assert map_shioaji_error_to_reason_code("INSUFFICIENT_BALANCE", "") == "EXEC_INSUFFICIENT_BALANCE"


def test_error_mapping_insufficient_balance_by_message():
    """Insufficient funds by message keyword → EXEC_INSUFFICIENT_BALANCE."""
    assert map_shioaji_error_to_reason_code(None, "balance too low") == "EXEC_INSUFFICIENT_BALANCE"


def test_error_mapping_insufficient_by_message_keyword():
    """'insufficient' keyword in message → EXEC_INSUFFICIENT_BALANCE."""
    assert map_shioaji_error_to_reason_code(None, "insufficient funds") == "EXEC_INSUFFICIENT_BALANCE"


def test_error_mapping_message_fallback_auth():
    """When code is None, AUTH keyword in message → EXEC_BROKER_AUTH."""
    assert map_shioaji_error_to_reason_code(None, "auth token invalid") == "EXEC_BROKER_AUTH"


def test_error_mapping_message_fallback_network():
    """When code is None, NETWORK keyword in message → EXEC_NETWORK_ERROR."""
    assert map_shioaji_error_to_reason_code(None, "network connection refused") == "EXEC_NETWORK_ERROR"


def test_error_mapping_unknown_fallback():
    """Unknown error → EXEC_BROKER_UNKNOWN."""
    assert map_shioaji_error_to_reason_code(None, "some random error") == "EXEC_BROKER_UNKNOWN"


def test_error_mapping_empty_code_and_message():
    """Both code and message empty → EXEC_BROKER_UNKNOWN."""
    assert map_shioaji_error_to_reason_code(None, "") == "EXEC_BROKER_UNKNOWN"


def test_submit_gives_up_has_correct_reason_code():
    """After 3 retries, result.reason_code should be populated."""
    adapter = _make_adapter()
    adapter.api.place_order.side_effect = Exception("persistent failure")
    candidate = OrderCandidate(symbol="2330", side="buy", qty=100, price=600.0)
    with patch("time.sleep"):
        result = adapter.submit_order("order-err", candidate)
    assert result.status == "rejected"
    assert result.reason_code != ""  # Should have a reason code
    assert "persistent failure" in result.reason


# ---------------------------------------------------------------------------
# cancel_order tests
# ---------------------------------------------------------------------------


def test_cancel_order_not_found():
    """Cancel nonexistent order → rejected with EXEC_BROKER_UNKNOWN."""
    adapter = _make_adapter()
    result = adapter.cancel_order("nonexistent")
    assert result.status == "rejected"
    assert result.reason_code == "EXEC_BROKER_UNKNOWN"


def test_cancel_order_success():
    """Cancel existing order → submitted."""
    adapter = _make_adapter()
    mock_trade = MagicMock()
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "sell"}
    result = adapter.cancel_order("test-oid")
    assert result.status == "submitted"
    adapter.api.cancel_order.assert_called_once_with(mock_trade)


def test_cancel_order_api_exception():
    """Cancel API throws → rejected with reason_code."""
    adapter = _make_adapter()
    mock_trade = MagicMock()
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "sell"}
    adapter.api.cancel_order.side_effect = Exception("network error")
    result = adapter.cancel_order("test-oid")
    assert result.status == "rejected"
    assert result.reason_code != ""


# ---------------------------------------------------------------------------
# wait_for_terminal tests
# ---------------------------------------------------------------------------


def test_wait_for_terminal_filled():
    """wait_for_terminal returns early when filled."""
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.status = "Filled"
    mock_trade.status.deal_quantity = 100
    mock_trade.status.avg_price = 600.0
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "buy"}
    with patch("time.sleep"):
        result = adapter.wait_for_terminal("test-oid")
    assert result.status == "filled"


def test_wait_for_terminal_timeout():
    """wait_for_terminal returns last status on timeout (max_poll_seconds=0)."""
    adapter = _make_adapter()
    adapter.max_poll_seconds = 0  # immediate timeout
    mock_trade = MagicMock()
    mock_trade.status.status = "Submitted"
    mock_trade.status.deal_quantity = 0
    mock_trade.status.avg_price = 0.0
    adapter._trades["test-oid"] = {"trade": mock_trade, "side": "buy"}
    # With max_poll_seconds=0, the while loop never executes; returns initial "submitted"
    result = adapter.wait_for_terminal("test-oid")
    assert result.broker_order_id == "test-oid"
