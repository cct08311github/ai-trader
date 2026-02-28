from openclaw.broker import map_shioaji_error_to_reason_code, map_shioaji_exec_status


def test_map_known_code():
    assert map_shioaji_error_to_reason_code("TOKEN_EXPIRED", "token expired") == "EXEC_BROKER_AUTH"


def test_map_message_fallback():
    assert map_shioaji_error_to_reason_code(None, "network connection reset") == "EXEC_NETWORK_ERROR"


def test_map_price_error():
    assert map_shioaji_error_to_reason_code(None, "invalid price tick") == "RISK_PRICE_DEVIATION_LIMIT"


def test_map_exec_status_partial():
    assert map_shioaji_exec_status("part_filled") == "partially_filled"
