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
    adapter._trades["test-oid"] = mock_trade
    result = adapter.poll_order_status("test-oid")
    assert result is not None
    assert result.status == "filled"
    assert result.filled_qty == 100


def test_poll_order_status_partial():
    adapter = _make_adapter()
    mock_trade = MagicMock()
    mock_trade.status.status = "Part_Filled"
    mock_trade.status.deal_quantity = 50
    mock_trade.status.avg_price = 600.0
    adapter._trades["test-oid"] = mock_trade
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
