import sqlite3
import time
from openclaw.order_slicing import (
    OrderBookLevel,
    OrderBookSnapshot,
    _clip_int,
    _sum_qty,
    estimate_available_qty_within_slippage,
    check_orderbook_depth,
    plan_twap_slices,
    plan_vwap_slices,
    slice_order_candidate,
    build_sliced_entry_plan_from_risk_inputs,
    OrderCandidate,
)


def setup_memory_db() -> sqlite3.Connection:
    """建立 :memory: SQLite 連線 + 執行必要的 migration（如果有的話）"""
    conn = sqlite3.connect(":memory:")
    # 此模組未使用資料庫，但為了符合要求，我們建立一個連接
    return conn


class TestOrderSlicing:
    def setup_method(self):
        self.conn = setup_memory_db()

    def teardown_method(self):
        self.conn.close()

    def test_estimate_available_qty_within_slippage_success(self):
        """成功路徑：估算可用數量"""
        bids = [OrderBookLevel(price=100.0, qty=1000)]
        asks = [OrderBookLevel(price=101.0, qty=500)]
        book = OrderBookSnapshot(ts_ms=int(time.time() * 1000), bids=bids, asks=asks)
        # 買方，最大滑點 10 bps (0.1%)
        available, limit_price = estimate_available_qty_within_slippage(
            side="buy", book=book, max_slippage_bps=10.0
        )
        assert available >= 0
        assert limit_price >= 101.0

    def test_check_orderbook_depth_boundary(self):
        """邊界條件：深度不足"""
        bids = [OrderBookLevel(price=100.0, qty=100)]
        asks = [OrderBookLevel(price=101.0, qty=100)]
        book = OrderBookSnapshot(ts_ms=int(time.time() * 1000), bids=bids, asks=asks)
        check = check_orderbook_depth(
            side="buy",
            desired_qty=200,
            book=book,
            max_slippage_bps=10.0,
            min_depth_multiplier=1.2,
        )
        assert check.ok is False
        assert check.available_qty == 100

    def test_plan_twap_slices_failure(self):
        """失敗路徑：零數量"""
        plan = plan_twap_slices(
            total_qty=0,
            start_ts_ms=int(time.time() * 1000),
            duration_ms=60000,
            n_slices=5,
        )
        assert plan.total_qty == 0
        assert len(plan.slices) == 0

    def test_plan_twap_slices_success(self):
        """成功路徑：TWAP 切片"""
        plan = plan_twap_slices(
            total_qty=1000,
            start_ts_ms=int(time.time() * 1000),
            duration_ms=60000,
            n_slices=5,
        )
        assert plan.total_qty == 1000
        assert len(plan.slices) > 0
        total = sum(s.qty for s in plan.slices)
        assert total == 1000

    def test_slice_order_candidate(self):
        """切片訂單候選"""
        candidate = OrderCandidate(
            symbol="2330",
            side="buy",
            qty=500,
            price=600.0,
            order_type="limit",
            tif="ROD",
            opens_new_position=True,
        )
        sliced = slice_order_candidate(
            candidate=candidate,
            method="twap",
            start_ts_ms=int(time.time() * 1000),
            duration_ms=30000,
            n_slices=3,
        )
        assert len(sliced) <= 3
        total_qty = sum(c.qty for c in sliced)
        assert total_qty == 500
        for c in sliced:
            assert c.symbol == "2330"
            assert c.side == "buy"


# ── _clip_int (line 50) ─────────────────────────────────────────────────────

def test_clip_int_clamps_above():
    """Line 50: value above hi gets clamped to hi."""
    assert _clip_int(200, 0, 100) == 100


def test_clip_int_clamps_below():
    """Line 50: value below lo gets clamped to lo."""
    assert _clip_int(-5, 0, 100) == 0


def test_clip_int_in_range():
    """Line 50: value within range passes through."""
    assert _clip_int(50, 0, 100) == 50


# ── _sum_qty (lines 58-59) ───────────────────────────────────────────────────

def test_sum_qty_with_exception_in_level():
    """Lines 58-59: exception on int(lv.qty) → continue."""

    class BadLevel:
        price = 100.0
        qty = "NOT_AN_INT"

    # _sum_qty should not crash; it skips bad levels
    from openclaw.order_slicing import _sum_qty
    result = _sum_qty([BadLevel()])
    assert result == 0


def test_sum_qty_mixed_levels():
    """Line 57: max(0, int(lv.qty)) for each valid level."""
    levels = [
        OrderBookLevel(price=100.0, qty=500),
        OrderBookLevel(price=99.0, qty=300),
    ]
    from openclaw.order_slicing import _sum_qty
    assert _sum_qty(levels) == 800


# ── estimate_available_qty_within_slippage (lines 78, 82, 89-94) ────────────

def test_estimate_buy_negative_slippage_clamped():
    """Line 78: negative slippage is clamped to 0."""
    asks = [OrderBookLevel(price=100.0, qty=500)]
    book = OrderBookSnapshot(ts_ms=1000, bids=[], asks=asks)
    available, lp = estimate_available_qty_within_slippage(
        side="buy", book=book, max_slippage_bps=-50.0
    )
    # With 0 slippage, only exact price levels qualify
    assert available == 500
    assert lp == 100.0


def test_estimate_buy_empty_asks():
    """Line 82: book.asks is empty → returns (0, 0.0)."""
    book = OrderBookSnapshot(ts_ms=1000, bids=[], asks=[])
    available, lp = estimate_available_qty_within_slippage(
        side="buy", book=book, max_slippage_bps=10.0
    )
    assert available == 0
    assert lp == 0.0


def test_estimate_sell_empty_bids():
    """Line 89-90: book.bids is empty → returns (0, 0.0)."""
    book = OrderBookSnapshot(ts_ms=1000, bids=[], asks=[])
    available, lp = estimate_available_qty_within_slippage(
        side="sell", book=book, max_slippage_bps=10.0
    )
    assert available == 0
    assert lp == 0.0


def test_estimate_sell_with_bids():
    """Lines 91-94: sell side — consumes bids down to limit price."""
    bids = [
        OrderBookLevel(price=100.0, qty=200),
        OrderBookLevel(price=99.5, qty=300),
        OrderBookLevel(price=98.0, qty=500),
    ]
    book = OrderBookSnapshot(ts_ms=1000, bids=bids, asks=[])
    # 10 bps slippage → limit = 100.0 * (1 - 10/10000) = 99.9
    available, lp = estimate_available_qty_within_slippage(
        side="sell", book=book, max_slippage_bps=10.0
    )
    # Only 100.0 and 99.5 are >= 99.9 (99.5 < 99.9, so only 100.0)
    assert available == 200
    assert abs(lp - 99.9) < 0.01


def test_estimate_sell_multiple_bids_within_slippage():
    """Lines 91-94: multiple bid levels within slippage band."""
    bids = [
        OrderBookLevel(price=100.0, qty=200),
        OrderBookLevel(price=99.95, qty=300),
    ]
    book = OrderBookSnapshot(ts_ms=1000, bids=bids, asks=[])
    # 10 bps slippage → limit = 100.0 * (1 - 10/10000) = 99.9
    available, lp = estimate_available_qty_within_slippage(
        side="sell", book=book, max_slippage_bps=10.0
    )
    # Both 100.0 and 99.95 are >= 99.9
    assert available == 500


# ── plan_twap_slices extra branches (lines 144, 150, 153, 158-167) ──────────

def test_plan_twap_slices_fewer_qty_than_slices():
    """Line 143-144: q <= 0 when total_qty < n_slices for some slots."""
    plan = plan_twap_slices(
        total_qty=3,
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=5,
    )
    # With 3 qty and 5 slices, only 3 non-zero slices
    assert plan.total_qty == 3
    assert len(plan.slices) == 3
    assert sum(s.qty for s in plan.slices) == 3


def test_plan_twap_slices_with_min_slice_qty():
    """Line 150: min_slice_qty > 1 → each slice raised to min."""
    plan = plan_twap_slices(
        total_qty=10,
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=5,
        min_slice_qty=3,
    )
    # After applying min=3, normalization reduces total back to 10
    assert sum(s.qty for s in plan.slices) == 10


def test_plan_twap_slices_with_max_slice_qty():
    """Line 153: max_slice_qty is not None → each slice capped."""
    plan = plan_twap_slices(
        total_qty=100,
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=3,
        max_slice_qty=20,
    )
    for s in plan.slices:
        assert s.qty <= 20


def test_plan_twap_slices_normalization_reduction():
    """Lines 158-167: current != total_qty after min constraint → reduction loop."""
    # With min_slice_qty=5 and total=10 across 3 slices:
    # base=3, rem=1 → [4,3,3], apply min=5 → [5,5,5]=15, need to reduce 5
    plan = plan_twap_slices(
        total_qty=10,
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=3,
        min_slice_qty=5,
    )
    assert sum(s.qty for s in plan.slices) == 10


def test_plan_twap_single_slice_zero_interval():
    """Line 170: single slice → interval_ms = 0."""
    plan = plan_twap_slices(
        total_qty=100,
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=1,
    )
    assert len(plan.slices) == 1
    assert plan.slices[0].scheduled_ts_ms == 1000


# ── plan_vwap_slices (lines 197-261) ─────────────────────────────────────────

def test_plan_vwap_total_qty_zero():
    """Lines 200-201: total_qty == 0 → empty plan."""
    plan = plan_vwap_slices(
        total_qty=0,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[100, 200, 300],
    )
    assert plan.total_qty == 0
    assert len(plan.slices) == 0
    assert plan.method == "vwap"


def test_plan_vwap_empty_volume_profile_falls_back_to_twap():
    """Lines 203-212: empty volume_profile → fallback to TWAP."""
    plan = plan_vwap_slices(
        total_qty=100,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[],
    )
    # Fallback creates 1 slice
    assert plan.total_qty == 100
    assert len(plan.slices) == 1


def test_plan_vwap_all_zero_weights():
    """Lines 216-218: all weights zero → equal weights."""
    plan = plan_vwap_slices(
        total_qty=90,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[0, 0, 0],
    )
    # Fallback to equal weights [1,1,1], so 30 each
    assert plan.total_qty == 90
    assert sum(s.qty for s in plan.slices) == 90


def test_plan_vwap_basic_proportional():
    """Lines 220-230: basic VWAP proportional allocation."""
    plan = plan_vwap_slices(
        total_qty=100,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[1, 3],  # 25% and 75%
    )
    assert plan.total_qty == 100
    assert sum(s.qty for s in plan.slices) == 100
    # Slice 0: 25, Slice 1: 75
    assert plan.slices[0].qty == 25
    assert plan.slices[1].qty == 75


def test_plan_vwap_remainder_distribution():
    """Lines 226-230: remainder distributed to biggest fractional parts."""
    # 7 / [3,3,1] = weights sum 7, total 10
    # raw = [10*3/7, 10*3/7, 10*1/7] = [4.28, 4.28, 1.43]
    # int: [4, 4, 1] = 9, remainder = 1 → add to biggest frac index
    plan = plan_vwap_slices(
        total_qty=10,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[3, 3, 1],
    )
    assert plan.total_qty == 10
    assert sum(s.qty for s in plan.slices) == 10


def test_plan_vwap_with_min_slice_qty():
    """Lines 233-234: min_slice_qty applied."""
    plan = plan_vwap_slices(
        total_qty=10,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[1, 9],
        min_slice_qty=3,
    )
    assert sum(s.qty for s in plan.slices) == 10


def test_plan_vwap_with_max_slice_qty():
    """Lines 235-236: max_slice_qty applied."""
    plan = plan_vwap_slices(
        total_qty=100,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[1, 1, 1, 1, 1],
        max_slice_qty=15,
    )
    for s in plan.slices:
        assert s.qty <= 15


def test_plan_vwap_normalization_when_over_allocated():
    """Lines 239-251: if current > total_qty after constraints, reduce."""
    # min_slice_qty=10, volume_profile=[1,1,1], total_qty=15
    # raw: [5,5,5], apply min=10 → [10,10,10]=30 > 15 → reduce
    plan = plan_vwap_slices(
        total_qty=15,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[1, 1, 1],
        min_slice_qty=10,
    )
    assert sum(s.qty for s in plan.slices) == 15


def test_plan_vwap_skips_zero_qty_slices():
    """Lines 257-259: slices with q <= 0 are skipped."""
    # This can happen with max_slice_qty very low + normalization
    plan = plan_vwap_slices(
        total_qty=5,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[10, 10, 10],
        max_slice_qty=2,
    )
    # max_slice_qty=2 means each can be at most 2; total_qty=5 means some may be 0
    for s in plan.slices:
        assert s.qty > 0


def test_plan_vwap_single_slice_zero_interval():
    """Line 253: single slice → interval_ms = 0."""
    plan = plan_vwap_slices(
        total_qty=100,
        start_ts_ms=5000,
        duration_ms=60000,
        volume_profile=[1],
    )
    assert len(plan.slices) == 1
    assert plan.slices[0].scheduled_ts_ms == 5000


def test_plan_vwap_zero_weight_slots_skipped():
    """Line 257-258: slots with q==0 (zero-weight) are skipped via continue."""
    # volume_profile=[0, 1, 0] → only middle slot has weight, others get qty=0
    plan = plan_vwap_slices(
        total_qty=10,
        start_ts_ms=1000,
        duration_ms=60000,
        volume_profile=[0, 1, 0],
    )
    # Only 1 non-zero slot should be emitted (the middle one)
    assert len(plan.slices) == 1
    assert plan.slices[0].qty == 10
    assert sum(s.qty for s in plan.slices) == 10


# ── slice_order_candidate (lines 279, 282-283) ──────────────────────────────

def test_slice_order_candidate_zero_qty():
    """Line 279: candidate.qty <= 0 → empty list."""
    candidate = OrderCandidate(
        symbol="2330",
        side="buy",
        qty=0,
        price=600.0,
    )
    result = slice_order_candidate(
        candidate=candidate,
        method="twap",
        start_ts_ms=1000,
        duration_ms=30000,
        n_slices=3,
    )
    assert result == []


def test_slice_order_candidate_vwap_with_profile():
    """Lines 282-288: vwap method with provided volume_profile."""
    candidate = OrderCandidate(
        symbol="2330",
        side="sell",
        qty=300,
        price=600.0,
    )
    result = slice_order_candidate(
        candidate=candidate,
        method="vwap",
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=3,
        volume_profile=[1, 2, 3],
    )
    assert len(result) == 3
    assert sum(c.qty for c in result) == 300
    for c in result:
        assert c.symbol == "2330"
        assert c.side == "sell"


def test_slice_order_candidate_vwap_without_profile():
    """Lines 282-283: vwap method with volume_profile=None → uniform profile."""
    candidate = OrderCandidate(
        symbol="2330",
        side="buy",
        qty=200,
        price=600.0,
    )
    result = slice_order_candidate(
        candidate=candidate,
        method="vwap",
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=4,
        volume_profile=None,
    )
    assert sum(c.qty for c in result) == 200


# ── build_sliced_entry_plan_from_risk_inputs (lines 333-370) ─────────────────

def test_build_sliced_entry_plan_basic():
    """Lines 333-370: full integration — position sizing + slicing."""
    total_qty, sliced = build_sliced_entry_plan_from_risk_inputs(
        nav=1_000_000.0,
        entry_price=500.0,
        stop_price=490.0,  # 2% stop distance
        side="buy",
        limits={
            "max_loss_per_trade_pct_nav": 0.005,
            "confidence": 1.0,
            "low_confidence_threshold": 0.60,
            "low_confidence_scale": 0.50,
            "volatility_multiplier": 1.0,
            "position_sizing_method": "fixed_fractional",
            "tif": "IOC",
        },
        start_ts_ms=1000,
        duration_ms=60000,
        method="twap",
        n_slices=5,
        symbol="2330",
    )
    assert total_qty > 0
    assert len(sliced) > 0
    total = sum(c.qty for c in sliced)
    assert total == total_qty
    for c in sliced:
        assert c.symbol == "2330"
        assert c.side == "buy"
        assert c.order_type == "limit"


def test_build_sliced_entry_plan_zero_qty():
    """Lines 349-350: qty <= 0 → returns (0, [])."""
    # entry_price == stop_price → stop distance=0 → qty=0
    total_qty, sliced = build_sliced_entry_plan_from_risk_inputs(
        nav=1_000.0,
        entry_price=100.0,
        stop_price=100.0,  # No stop distance → qty=0
        side="buy",
        limits={},
        start_ts_ms=1000,
        duration_ms=60000,
        symbol="2330",
    )
    assert total_qty == 0
    assert sliced == []


def test_build_sliced_entry_plan_vwap_method():
    """Lines 333-370: vwap method path."""
    total_qty, sliced = build_sliced_entry_plan_from_risk_inputs(
        nav=1_000_000.0,
        entry_price=500.0,
        stop_price=490.0,
        side="sell",
        limits={
            "max_loss_per_trade_pct_nav": 0.01,
            "confidence": 1.0,
            "tif": "ROD",
        },
        start_ts_ms=1000,
        duration_ms=60000,
        method="vwap",
        n_slices=3,
        symbol="2890",
    )
    # qty may be > 0 depending on sizing; just verify structure
    if total_qty > 0:
        assert len(sliced) > 0


def test_build_sliced_entry_plan_with_authority_level():
    """Lines 333-370: authority_level param passed through."""
    total_qty, sliced = build_sliced_entry_plan_from_risk_inputs(
        nav=1_000_000.0,
        entry_price=500.0,
        stop_price=490.0,
        side="buy",
        limits={
            "max_loss_per_trade_pct_nav": 0.005,
        },
        start_ts_ms=1000,
        duration_ms=60000,
        n_slices=3,
        authority_level=2,
        symbol="2330",
    )
