import sqlite3
import time
from openclaw.order_slicing import (
    OrderBookLevel,
    OrderBookSnapshot,
    estimate_available_qty_within_slippage,
    check_orderbook_depth,
    plan_twap_slices,
    plan_vwap_slices,
    slice_order_candidate,
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
