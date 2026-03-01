from openclaw.broker import (
    map_shioaji_error_to_reason_code, 
    map_shioaji_exec_status,
    SimBrokerAdapter,
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
    
    # First poll: partially filled
    status1 = adapter.poll_order_status(submission.broker_order_id)
    assert isinstance(status1, BrokerOrderStatus)
    assert status1.status == "partially_filled"
    assert status1.filled_qty == 500  # half of 1000
    assert status1.avg_fill_price == 580.0
    assert status1.fee == 20.0
    assert status1.tax == 30.0
    
    # Second poll: filled
    status2 = adapter.poll_order_status(submission.broker_order_id)
    assert status2.status == "filled"
    assert status2.filled_qty == 1000
    assert status2.fee == 40.0
    assert status2.tax == 60.0
    
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
