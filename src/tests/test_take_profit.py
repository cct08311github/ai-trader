from __future__ import annotations

from openclaw.take_profit import TakeProfitPolicy, TakeProfitState, evaluate_take_profit


def test_target_price_partial_then_trailing_stop_exit():
    policy = TakeProfitPolicy(target_rr=2.0, target_exit_fraction=0.5, trailing_stop_pct=0.10, max_hold_ms=999999)
    state = TakeProfitState(
        entry_ts_ms=0,
        entry_price=100.0,
        side="long",
        qty=10,
        initial_stop_price=95.0,
    )

    # Target price: entry + (100-95)*2 = 110
    d1 = evaluate_take_profit(state=state, last_price=111.0, now_ms=10, policy=policy)
    assert d1.action == "exit"
    assert d1.reason == "target_price"
    assert d1.qty_to_exit == 5
    assert state.remaining_qty == 5

    # Price keeps rising -> update peak to 120
    d_hold = evaluate_take_profit(state=state, last_price=120.0, now_ms=20, policy=policy)
    assert d_hold.action == "hold"

    # Trailing stop for peak=120, pct=10% => 108
    d2 = evaluate_take_profit(state=state, last_price=107.0, now_ms=30, policy=policy)
    assert d2.action == "exit"
    assert d2.reason == "trailing_stop"
    assert d2.qty_to_exit == 5
    assert state.remaining_qty == 0


def test_time_decay_exit_when_held_too_long_and_profit_floor_met():
    policy = TakeProfitPolicy(target_rr=10.0, trailing_stop_pct=0.50, max_hold_ms=1000, time_decay_profit_floor_pct=0.0)
    state = TakeProfitState(
        entry_ts_ms=0,
        entry_price=100.0,
        side="long",
        qty=3,
        initial_stop_price=90.0,
    )

    d = evaluate_take_profit(state=state, last_price=100.0, now_ms=1500, policy=policy)
    assert d.action == "exit"
    assert d.reason == "time_decay"
    assert d.qty_to_exit == 3
