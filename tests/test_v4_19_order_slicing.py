from __future__ import annotations

from openclaw.order_slicing import (
    OrderBookLevel,
    OrderBookSnapshot,
    check_orderbook_depth,
    plan_twap_slices,
    plan_vwap_slices,
)


def test_orderbook_depth_check_buy():
    book = OrderBookSnapshot(
        ts_ms=0,
        bids=[OrderBookLevel(price=99.9, qty=1000)],
        asks=[
            OrderBookLevel(price=100.0, qty=50),
            OrderBookLevel(price=100.01, qty=40),
            OrderBookLevel(price=100.20, qty=10_000),
        ],
    )

    # With 10 bps slippage, we only include up to 100.10; so qty=50+40=90
    chk = check_orderbook_depth(side="buy", desired_qty=80, book=book, max_slippage_bps=10, min_depth_multiplier=1.0)
    assert chk.ok is True
    assert chk.available_qty == 90

    chk2 = check_orderbook_depth(side="buy", desired_qty=100, book=book, max_slippage_bps=10, min_depth_multiplier=1.0)
    assert chk2.ok is False


def test_plan_twap_slices_sum_and_count():
    plan = plan_twap_slices(total_qty=101, start_ts_ms=1000, duration_ms=4000, n_slices=5)
    assert plan.method == "twap"
    assert sum(s.qty for s in plan.slices) == 101
    assert len(plan.slices) == 5


def test_plan_vwap_slices_allocates_by_profile():
    plan = plan_vwap_slices(total_qty=100, start_ts_ms=0, duration_ms=4000, volume_profile=[1, 1, 2, 6])
    assert plan.method == "vwap"
    assert sum(s.qty for s in plan.slices) == 100

    # The last bucket should get the largest allocation
    assert plan.slices[-1].qty > plan.slices[0].qty
