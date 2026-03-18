"""test_wash_sale.py — Wash Sale / Churning 防護測試

涵蓋：
- 同日已成交 symbol 阻止 buy re-entry (RISK_WASH_SALE)
- 不同 symbol 不受影響
- wash_sale_prevention_enabled=0 可關閉
- sell 信號不受 wash sale 防護影響
"""
from __future__ import annotations

import time

import pytest

from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _base_limits(**overrides) -> dict:
    lim = default_limits()
    lim["pm_review_required"] = 0  # bypass PM gate in unit tests
    lim.update(overrides)
    return lim


def _normal_market(bid: float = 100.0, ask: float = 100.5) -> MarketState:
    return MarketState(
        best_bid=bid,
        best_ask=ask,
        volume_1m=100_000,
        feed_delay_ms=0,
    )


def _normal_system(now_ms: int | None = None) -> SystemState:
    return SystemState(
        now_ms=now_ms or _now_ms(),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
        reduce_only_mode=False,
    )


def _portfolio(same_day_fill_symbols: set | None = None) -> PortfolioState:
    return PortfolioState(
        nav=1_000_000.0,
        cash=1_000_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions={},
        consecutive_losses=0,
        same_day_fill_symbols=same_day_fill_symbols or set(),
    )


def _decision(side: str, symbol: str = "2330", now: int | None = None) -> Decision:
    ts = now or _now_ms()
    return Decision(
        decision_id="test-wash-sale",
        ts_ms=ts,
        symbol=symbol,
        strategy_id="test",
        signal_side=side,
        signal_score=0.8,
        signal_ttl_ms=30_000,
        confidence=1.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWashSaleBlocking:
    """RISK_WASH_SALE: 同日已成交 symbol 阻止 buy re-entry"""

    def test_wash_sale_blocks_same_day_reentry(self):
        """同日已有成交記錄的 symbol，buy 應被拒絕（RISK_WASH_SALE）"""
        portfolio = _portfolio(same_day_fill_symbols={"2330"})
        result = evaluate_and_build_order(
            _decision("buy", "2330"),
            _normal_market(),
            portfolio,
            _base_limits(),
            _normal_system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_WASH_SALE"

    def test_wash_sale_allows_different_symbol(self):
        """不同 symbol 不受 wash sale 防護影響，buy 應通過"""
        portfolio = _portfolio(same_day_fill_symbols={"2330"})
        result = evaluate_and_build_order(
            _decision("buy", "2317"),  # 不同 symbol
            _normal_market(),
            portfolio,
            _base_limits(),
            _normal_system(),
        )
        # 不應因 wash sale 被拒（可能因其他原因被拒，但非 RISK_WASH_SALE）
        assert result.reject_code != "RISK_WASH_SALE"

    def test_wash_sale_allows_buy_when_no_same_day_fill(self):
        """今日無成交記錄時，buy 不應被 wash sale 阻擋"""
        portfolio = _portfolio(same_day_fill_symbols=set())
        result = evaluate_and_build_order(
            _decision("buy", "2330"),
            _normal_market(),
            portfolio,
            _base_limits(),
            _normal_system(),
        )
        assert result.reject_code != "RISK_WASH_SALE"

    def test_wash_sale_allows_sell_on_same_day(self):
        """sell 信號不受 wash sale 防護影響，即使今日已有成交"""
        portfolio = _portfolio(same_day_fill_symbols={"2330"})
        result = evaluate_and_build_order(
            _decision("sell", "2330"),
            _normal_market(),
            portfolio,
            _base_limits(),
            _normal_system(),
        )
        assert result.reject_code != "RISK_WASH_SALE"


class TestWashSaleToggle:
    """wash_sale_prevention_enabled 開關測試"""

    def test_wash_sale_allows_when_disabled(self):
        """wash_sale_prevention_enabled=0 時，同日已成交 symbol 的 buy 不應被阻擋"""
        portfolio = _portfolio(same_day_fill_symbols={"2330"})
        result = evaluate_and_build_order(
            _decision("buy", "2330"),
            _normal_market(),
            portfolio,
            _base_limits(wash_sale_prevention_enabled=0),
            _normal_system(),
        )
        assert result.reject_code != "RISK_WASH_SALE"

    def test_wash_sale_enabled_by_default(self):
        """default_limits() 應包含 wash_sale_prevention_enabled=1"""
        limits = default_limits()
        assert int(limits.get("wash_sale_prevention_enabled", 0)) == 1

    def test_wash_sale_blocks_multiple_symbols(self):
        """多個 symbol 在 same_day_fill_symbols 中，各自均應被阻擋"""
        portfolio = _portfolio(same_day_fill_symbols={"2330", "2317", "0050"})
        for symbol in ["2330", "2317", "0050"]:
            result = evaluate_and_build_order(
                _decision("buy", symbol),
                _normal_market(),
                portfolio,
                _base_limits(),
                _normal_system(),
            )
            assert result.reject_code == "RISK_WASH_SALE", f"Expected RISK_WASH_SALE for {symbol}"


# ---------------------------------------------------------------------------
# Integration: _get_today_buy_filled_symbols populates same_day_fill_symbols
# ---------------------------------------------------------------------------

class TestGetTodayBuyFilledSymbols:
    """驗證 ticker_watcher._get_today_buy_filled_symbols 能正確從 DB 回傳今日 buy 成交 symbol。"""

    def _setup_db(self, conn):
        conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
               order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, status TEXT,
               ts_submit TEXT, qty INTEGER, price REAL)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS fills (
               fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
               order_id TEXT, qty INTEGER, price REAL, fee REAL, tax REAL)"""
        )
        conn.commit()

    def test_returns_today_buy_symbols(self):
        import sqlite3
        from openclaw.ticker_watcher import _get_today_buy_filled_symbols

        conn = sqlite3.connect(":memory:")
        self._setup_db(conn)
        # 今日 buy 訂單 + fill
        conn.execute("INSERT INTO orders VALUES ('o1','2330','buy','filled',datetime('now','+8 hours'),1000,100.0)")
        conn.execute("INSERT INTO fills VALUES (NULL,'o1',1000,100.0,0,0)")
        conn.commit()

        result = _get_today_buy_filled_symbols(conn)
        assert "2330" in result

    def test_excludes_sell_orders(self):
        import sqlite3
        from openclaw.ticker_watcher import _get_today_buy_filled_symbols

        conn = sqlite3.connect(":memory:")
        self._setup_db(conn)
        conn.execute("INSERT INTO orders VALUES ('o2','2317','sell','filled',datetime('now','+8 hours'),500,80.0)")
        conn.execute("INSERT INTO fills VALUES (NULL,'o2',500,80.0,0,0)")
        conn.commit()

        result = _get_today_buy_filled_symbols(conn)
        assert "2317" not in result

    def test_excludes_orders_without_fills(self):
        import sqlite3
        from openclaw.ticker_watcher import _get_today_buy_filled_symbols

        conn = sqlite3.connect(":memory:")
        self._setup_db(conn)
        conn.execute("INSERT INTO orders VALUES ('o3','0050','buy','pending',datetime('now','+8 hours'),1000,50.0)")
        conn.commit()

        result = _get_today_buy_filled_symbols(conn)
        assert "0050" not in result

    def test_returns_empty_set_on_db_error(self):
        import sqlite3
        from openclaw.ticker_watcher import _get_today_buy_filled_symbols

        conn = sqlite3.connect(":memory:")
        # 故意不建 orders/fills 表 → OperationalError
        result = _get_today_buy_filled_symbols(conn)
        assert result == set()
