from __future__ import annotations

from openclaw.take_profit import (
    TakeProfitPolicy,
    TakeProfitState,
    TakeProfitDecision,
    evaluate_take_profit,
    compute_target_price,
    compute_trailing_stop,
    update_trailing_extremes,
    _profit_pct,
    _crosses_target,
    _crosses_trailing_stop,
)


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


# ── Additional tests for uncovered lines ─────────────────────────────────────

def _short_state(**kwargs) -> TakeProfitState:
    defaults = dict(
        entry_ts_ms=0,
        entry_price=100.0,
        side="short",
        qty=10,
        initial_stop_price=105.0,
    )
    defaults.update(kwargs)
    return TakeProfitState(**defaults)


def test_compute_target_price_zero_risk_fallback():
    """Line 73: risk <= 0 falls back to 1% of entry_price."""
    policy = TakeProfitPolicy(target_rr=2.0)
    # entry == stop → risk = 0 → fallback to 1%
    state = TakeProfitState(
        entry_ts_ms=0, entry_price=100.0, side="long", qty=10, initial_stop_price=100.0
    )
    target = compute_target_price(state, policy)
    # risk = 100 * 0.01 = 1; target = 100 + 1 * 2 = 102
    assert target == 102.0


def test_compute_target_price_short_side():
    """Line 77: short side target = entry - risk * rr."""
    policy = TakeProfitPolicy(target_rr=2.0)
    state = _short_state(entry_price=100.0, initial_stop_price=105.0)
    target = compute_target_price(state, policy)
    # risk = |100 - 105| = 5; target = 100 - 5*2 = 90
    assert target == 90.0


def test_compute_trailing_stop_short_side():
    """Line 90: short side trailing stop = trough * (1 + pct)."""
    policy = TakeProfitPolicy(trailing_stop_pct=0.05)
    state = _short_state(entry_price=100.0, initial_stop_price=105.0)
    # Update trough to 90.0
    update_trailing_extremes(state, 90.0)
    ts = compute_trailing_stop(state, policy)
    # trough = 90; stop = 90 * 1.05 = 94.5
    assert ts == 94.5


def test_profit_pct_zero_entry_price():
    """Line 96: entry_price == 0 returns 0.0."""
    state = TakeProfitState(
        entry_ts_ms=0, entry_price=0.0, side="long", qty=10, initial_stop_price=0.0
    )
    result = _profit_pct(state, 110.0)
    assert result == 0.0


def test_profit_pct_short_side():
    """Line 100: short side profit = (entry - last) / |entry|."""
    state = _short_state(entry_price=100.0, initial_stop_price=105.0)
    result = _profit_pct(state, 90.0)
    # (100 - 90) / 100 = 0.10
    assert result == 0.10


def test_crosses_target_short_side():
    """Line 107: short side target crossed when price <= target."""
    state = _short_state(entry_price=100.0, initial_stop_price=105.0)
    policy = TakeProfitPolicy(target_rr=2.0)
    target = compute_target_price(state, policy)  # = 90.0
    assert _crosses_target(state, 89.0, target) is True
    assert _crosses_target(state, 90.0, target) is True
    assert _crosses_target(state, 91.0, target) is False


def test_crosses_trailing_stop_short_side():
    """Line 114: short side trailing stop crossed when price >= trailing_stop."""
    state = _short_state(entry_price=100.0, initial_stop_price=105.0)
    policy = TakeProfitPolicy(trailing_stop_pct=0.05)
    update_trailing_extremes(state, 90.0)
    ts = compute_trailing_stop(state, policy)  # = 94.5
    assert _crosses_trailing_stop(state, 95.0, ts) is True
    assert _crosses_trailing_stop(state, 94.0, ts) is False


def test_evaluate_take_profit_no_position():
    """Line 131: remaining_qty <= 0 returns hold with no_position reason."""
    policy = TakeProfitPolicy()
    state = TakeProfitState(
        entry_ts_ms=0, entry_price=100.0, side="long", qty=10, initial_stop_price=95.0
    )
    state.remaining_qty = 0
    d = evaluate_take_profit(state=state, last_price=110.0, now_ms=100, policy=policy)
    assert d.action == "hold"
    assert d.reason == "no_position"
    assert d.qty_to_exit == 0


def test_evaluate_take_profit_short_side_target_then_trailing():
    """Short side: target price exit then trailing stop."""
    policy = TakeProfitPolicy(target_rr=2.0, target_exit_fraction=0.5, trailing_stop_pct=0.05, max_hold_ms=999999)
    state = _short_state(entry_price=100.0, initial_stop_price=105.0, qty=10)
    # target = 100 - 5*2 = 90; price drops to 89 → target hit
    d1 = evaluate_take_profit(state=state, last_price=89.0, now_ms=10, policy=policy)
    assert d1.action == "exit"
    assert d1.reason == "target_price"
    assert d1.qty_to_exit == 5
    assert state.remaining_qty == 5

    # Price bounces back up past trailing stop
    # trough = 89; trailing_stop = 89 * 1.05 = 93.45; price 94 > 93.45 → stop triggered
    d2 = evaluate_take_profit(state=state, last_price=94.0, now_ms=20, policy=policy)
    assert d2.action == "exit"
    assert d2.reason == "trailing_stop"
