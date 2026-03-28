"""tests/test_execution_quality_report.py — 執行品質比對報告測試

測試案例：
1. SlippagePair.slippage_bps 買單計算正確
2. SlippagePair.slippage_bps 賣單計算正確
3. compute_execution_quality 空 DB 回傳空報告
4. compute_execution_quality 有配對時正確計算滑點
5. compute_execution_quality 無實盤時 sim_only 計數正確
6. format_telegram_report 無資料時輸出合理訊息
7. format_telegram_report 有資料時包含必要欄位
8. SQL migration 正常加入 account_mode 欄位
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from openclaw.execution_quality_report import (
    ExecutionQualityReport,
    SlippagePair,
    compute_execution_quality,
    format_telegram_report,
)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL DEFAULT 'test-decision',
            broker_order_id TEXT,
            ts_submit TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL,
            order_type TEXT NOT NULL DEFAULT 'limit',
            tif TEXT NOT NULL DEFAULT 'IOC',
            status TEXT NOT NULL DEFAULT 'filled',
            strategy_version TEXT NOT NULL DEFAULT '4.0',
            settlement_date TEXT,
            account_mode TEXT NOT NULL DEFAULT 'simulation'
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            ts_fill TEXT NOT NULL DEFAULT (datetime('now')),
            qty INTEGER NOT NULL,
            price REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            tax REAL NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


def _today_trade_date() -> str:
    """Return today's date as trade_date (ensures tests stay within the 7-day window)."""
    from datetime import datetime, timezone, timedelta
    return datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _insert_order_fill(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    side: str,
    account_mode: str,
    fill_price: float,
    qty: int = 1000,
    trade_date: str = "",
    status: str = "filled",
) -> str:
    """插入一筆訂單 + 成交，ts_submit 用 UTC 時間（+8h 後對應 trade_date）。"""
    if not trade_date:
        trade_date = _today_trade_date()
    oid = str(uuid.uuid4())
    ts = f"{trade_date}T08:00:00+00:00"  # 台北 16:00 = UTC 08:00，仍屬同日
    conn.execute(
        """INSERT INTO orders
           (order_id, ts_submit, symbol, side, qty, price, status, account_mode)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (oid, ts, symbol, side, qty, fill_price, status, account_mode),
    )
    conn.execute(
        """INSERT INTO fills (fill_id, order_id, qty, price)
           VALUES (?, ?, ?, ?)""",
        (str(uuid.uuid4()), oid, qty, fill_price),
    )
    conn.commit()
    return oid


# ─── Test 1 & 2: SlippagePair.slippage_bps ───────────────────────────────────

def test_slippage_bps_buy_positive_when_live_more_expensive():
    """買單：實盤比模擬貴 → 正值滑點。"""
    pair = SlippagePair(
        symbol="2330", trade_date="2026-03-18", side="buy",
        sim_avg_price=100.0, live_avg_price=101.0,
        sim_qty=1000, live_qty=1000,
    )
    # (101/100 - 1) * 10000 = 100 bps
    assert abs(pair.slippage_bps - 100.0) < 0.01


def test_slippage_bps_sell_positive_when_live_gets_less():
    """賣單：實盤成交價比模擬低 → 正值滑點（實盤回收較少）。"""
    pair = SlippagePair(
        symbol="2330", trade_date="2026-03-18", side="sell",
        sim_avg_price=100.0, live_avg_price=99.0,
        sim_qty=1000, live_qty=1000,
    )
    # (100/99 - 1) * 10000 ≈ 101 bps
    assert pair.slippage_bps > 0


def test_slippage_bps_zero_when_prices_equal():
    pair = SlippagePair(
        symbol="0050", trade_date="2026-03-18", side="buy",
        sim_avg_price=150.0, live_avg_price=150.0,
        sim_qty=1000, live_qty=1000,
    )
    assert pair.slippage_bps == 0.0


# ─── Test 3: 空 DB ───────────────────────────────────────────────────────────

def test_empty_db_returns_empty_report():
    conn = _make_db()
    report = compute_execution_quality(conn, days=7)
    assert not report.has_data
    assert report.pairs == []
    assert report.avg_slippage_bps is None


# ─── Test 4: 有配對時正確計算 ────────────────────────────────────────────────

def test_paired_orders_compute_slippage():
    """模擬 100 實盤 101 → 買單滑點 100bps。"""
    conn = _make_db()
    _insert_order_fill(conn, symbol="2330", side="buy",
                       account_mode="simulation", fill_price=100.0)
    _insert_order_fill(conn, symbol="2330", side="buy",
                       account_mode="live", fill_price=101.0)

    report = compute_execution_quality(conn, days=7)

    assert report.has_data
    assert len(report.pairs) == 1
    pair = report.pairs[0]
    assert pair.symbol == "2330"
    assert pair.side == "buy"
    assert abs(pair.slippage_bps - 100.0) < 0.1
    assert abs(report.avg_slippage_bps - 100.0) < 0.1


def test_sell_pair_slippage():
    """賣單：模擬 100 實盤 99 → 滑點約 101bps。"""
    conn = _make_db()
    _insert_order_fill(conn, symbol="0050", side="sell",
                       account_mode="simulation", fill_price=100.0)
    _insert_order_fill(conn, symbol="0050", side="sell",
                       account_mode="live", fill_price=99.0)

    report = compute_execution_quality(conn, days=7)

    assert report.has_data
    assert report.pairs[0].slippage_bps > 0


# ─── Test 5: sim_only 計數 ────────────────────────────────────────────────────

def test_sim_only_count_when_no_live():
    """只有模擬訂單，無實盤 → sim_only > 0，pairs 為空。"""
    conn = _make_db()
    _insert_order_fill(conn, symbol="2330", side="buy",
                       account_mode="simulation", fill_price=100.0)

    report = compute_execution_quality(conn, days=7)

    assert not report.has_data
    assert report.sim_only_trades >= 1
    assert report.live_only_trades == 0


# ─── Test 6 & 7: format_telegram_report ─────────────────────────────────────

def test_format_no_data():
    report = ExecutionQualityReport(period_days=7)
    msg = format_telegram_report(report)
    assert "無實盤" in msg or "無法計算" in msg
    assert "7" in msg


def test_format_with_data():
    report = ExecutionQualityReport(
        period_days=7,
        pairs=[
            SlippagePair(
                symbol="2330", trade_date="2026-03-18", side="buy",
                sim_avg_price=100.0, live_avg_price=101.0,
                sim_qty=1000, live_qty=1000,
            )
        ],
    )
    msg = format_telegram_report(report)
    assert "2330" in msg
    assert "bps" in msg
    assert "100" in msg  # slippage value


# ─── Test 8: SQL migration ───────────────────────────────────────────────────

def test_migration_adds_account_mode_column(tmp_path):
    from pathlib import Path
    import sqlite3 as _sql

    db = tmp_path / "test.db"
    conn = _sql.connect(str(db))
    conn.execute("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL,
            broker_order_id TEXT,
            ts_submit TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty INTEGER NOT NULL,
            price REAL,
            order_type TEXT NOT NULL DEFAULT 'limit',
            tif TEXT NOT NULL DEFAULT 'IOC',
            status TEXT NOT NULL,
            strategy_version TEXT NOT NULL
        )
    """)
    conn.commit()

    migration = Path("src/sql/migration_v1_3_2_order_account_mode.sql")
    conn.executescript(migration.read_text(encoding="utf-8"))
    conn.commit()

    cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    assert "account_mode" in cols
    conn.close()
