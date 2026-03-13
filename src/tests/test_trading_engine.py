# src/tests/test_trading_engine.py
"""Tests for trading_engine.py — 持倉狀態機 + 時間止損

覆蓋目標：tick() 全路徑、_create_time_stop_proposal、_record_event、
虧損 10 日 auto-approved、獲利 30 日 pending、原子寫入兩種模式。
"""
import sqlite3
import time
import pytest

from openclaw.trading_engine import (
    tick,
    _get_latest_trading_day,
    _count_hold_days,
    _LOSING_THRESHOLD_DAYS,
    _PROFIT_THRESHOLD_DAYS,
)


def _make_db():
    """建立 in-memory DB 並建必要表格。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY,
        quantity INTEGER,
        avg_price REAL,
        current_price REAL,
        unrealized_pnl REAL,
        state TEXT,
        entry_trading_day TEXT
    )""")
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT,
        symbol TEXT,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        PRIMARY KEY (trade_date, symbol)
    )""")
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY,
        generated_by TEXT,
        target_rule TEXT,
        rule_category TEXT,
        proposed_value TEXT,
        current_value TEXT,
        supporting_evidence TEXT,
        confidence REAL,
        requires_human_approval INTEGER,
        status TEXT,
        proposal_json TEXT,
        created_at INTEGER
    )""")
    conn.execute("""CREATE TABLE position_events (
        event_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        from_state TEXT,
        to_state TEXT NOT NULL,
        reason TEXT,
        trading_day TEXT NOT NULL,
        ts INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE position_candidates (
        symbol TEXT PRIMARY KEY,
        trading_day TEXT NOT NULL,
        reason TEXT,
        created_at INTEGER NOT NULL
    )""")
    return conn


def _insert_eod_days(conn, symbol, start_date, num_days):
    """插入 num_days 天的 eod_prices（從 start_date 之後）。"""
    # 簡化：每天用遞增日期 (YYYY-MM-DD 格式)
    year, month, day = map(int, start_date.split("-"))
    for i in range(1, num_days + 1):
        d = day + i
        m = month + (d - 1) // 28
        d = ((d - 1) % 28) + 1
        date_str = f"{year}-{m:02d}-{d:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO eod_prices VALUES (?,?,100,105,95,100,1000)",
            (date_str, symbol),
        )
    conn.commit()


class TestGetLatestTradingDay:
    def test_returns_max_date(self):
        conn = _make_db()
        conn.execute("INSERT INTO eod_prices VALUES ('2026-03-10','2330',100,105,95,100,1000)")
        conn.execute("INSERT INTO eod_prices VALUES ('2026-03-11','2330',101,106,96,101,1100)")
        assert _get_latest_trading_day(conn) == "2026-03-11"

    def test_returns_none_when_empty(self):
        conn = _make_db()
        assert _get_latest_trading_day(conn) is None


class TestCountHoldDays:
    def test_counts_days_after_entry(self):
        conn = _make_db()
        for i in range(5):
            conn.execute(
                "INSERT INTO eod_prices VALUES (?,?,100,105,95,100,1000)",
                (f"2026-03-{10+i:02d}", "2330"),
            )
        assert _count_hold_days(conn, "2330", "2026-03-10") == 4  # 11,12,13 = after 10
        assert _count_hold_days(conn, "2330", "2026-03-13") == 1  # only 14

    def test_returns_zero_when_no_data(self):
        conn = _make_db()
        assert _count_hold_days(conn, "2330", "2026-03-10") == 0


class TestTickSkipCases:
    """tick() 應早退的各種 case。"""

    def test_no_position(self):
        conn = _make_db()
        tick(conn, "2330")  # no position → no-op

    def test_zero_quantity(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 0, 100, 100, 0, "HOLDING", "2026-03-01"),
        )
        tick(conn, "2330")  # qty=0 → skip

    def test_exiting_state_skipped(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 100, 100, 90, -1000, "EXITING", "2026-03-01"),
        )
        tick(conn, "2330")  # EXITING → skip

    def test_no_entry_day_skipped(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 100, 100, 90, -1000, "HOLDING", None),
        )
        tick(conn, "2330")

    def test_below_threshold_no_action(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 100, 100, 90, -1000, "HOLDING", "2026-03-01"),
        )
        # 只有 5 天 < 10 天門檻
        for i in range(5):
            conn.execute(
                "INSERT INTO eod_prices VALUES (?,?,100,105,95,90,1000)",
                (f"2026-03-{2+i:02d}", "2330"),
            )
        tick(conn, "2330")
        # 確認沒產生 proposal
        assert conn.execute("SELECT COUNT(*) FROM strategy_proposals").fetchone()[0] == 0

    def test_avg_price_zero_skipped(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 100, 0, 90, 0, "HOLDING", "2026-03-01"),
        )
        _insert_eod_days(conn, "2330", "2026-03-01", 15)
        tick(conn, "2330")
        assert conn.execute("SELECT COUNT(*) FROM strategy_proposals").fetchone()[0] == 0


class TestTickLosingTimeStop:
    """虧損持倉超過 10 交易日 → auto-approved proposal。"""

    def test_losing_position_triggers_auto_approved(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 100, 100, 80, -2000, "HOLDING", "2026-03-01"),
        )
        # 插入 11 天 (> 10 門檻)
        _insert_eod_days(conn, "2330", "2026-03-01", 11)

        tick(conn, "2330")

        # 檢查 proposal
        row = conn.execute("SELECT * FROM strategy_proposals").fetchone()
        assert row is not None
        assert row["status"] == "approved"
        assert row["generated_by"] == "trading_engine"
        assert "time_stop" in row["proposal_json"]
        assert '"reduce_pct": 1.0' in row["proposal_json"]

        # 檢查 state 已更新
        pos = conn.execute("SELECT state FROM positions WHERE symbol='2330'").fetchone()
        assert pos["state"] == "EXITING"

        # 檢查 event
        evt = conn.execute("SELECT * FROM position_events WHERE symbol='2330'").fetchone()
        assert evt["from_state"] == "HOLDING"
        assert evt["to_state"] == "EXITING"
        assert "time_stop" in evt["reason"]


class TestTickProfitTimeStop:
    """獲利持倉超過 30 交易日 → pending proposal（需人工審核）。"""

    def test_profitable_position_triggers_pending(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2317", 200, 100, 120, 4000, "HOLDING", "2026-01-15"),
        )
        # 插入 31 天 (> 30 門檻)
        _insert_eod_days(conn, "2317", "2026-01-15", 31)

        tick(conn, "2317")

        row = conn.execute("SELECT * FROM strategy_proposals").fetchone()
        assert row is not None
        assert row["status"] == "pending"
        assert row["requires_human_approval"] == 1
        assert '"reduce_pct": 0.5' in row["proposal_json"]

        pos = conn.execute("SELECT state FROM positions WHERE symbol='2317'").fetchone()
        assert pos["state"] == "EXITING"


class TestTickAutocommitMode:
    """使用 isolation_level=None 模式（ticker_watcher 實際使用方式）。"""

    def test_autocommit_mode_uses_begin_commit(self):
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.row_factory = sqlite3.Row
        # 建表
        for stmt in [
            "CREATE TABLE positions (symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL, current_price REAL, unrealized_pnl REAL, state TEXT, entry_trading_day TEXT)",
            "CREATE TABLE eod_prices (trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, PRIMARY KEY (trade_date, symbol))",
            "CREATE TABLE strategy_proposals (proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT, rule_category TEXT, proposed_value TEXT, current_value TEXT, supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER, status TEXT, proposal_json TEXT, created_at INTEGER)",
            "CREATE TABLE position_events (event_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL, reason TEXT, trading_day TEXT NOT NULL, ts INTEGER NOT NULL)",
            "CREATE TABLE position_candidates (symbol TEXT PRIMARY KEY, trading_day TEXT NOT NULL, reason TEXT, created_at INTEGER NOT NULL)",
        ]:
            conn.execute(stmt)

        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("2330", 50, 200, 150, -2500, "HOLDING", "2026-02-01"),
        )
        # 12 天 > 10 天虧損門檻
        for i in range(12):
            conn.execute(
                "INSERT INTO eod_prices VALUES (?,?,200,210,190,150,500)",
                (f"2026-02-{2+i:02d}", "2330"),
            )

        tick(conn, "2330")

        # proposal 已寫入且已 commit（autocommit 模式下）
        row = conn.execute("SELECT status FROM strategy_proposals").fetchone()
        assert row["status"] == "approved"
        assert conn.execute("SELECT state FROM positions WHERE symbol='2330'").fetchone()["state"] == "EXITING"


class TestTickCandidateCleanup:
    """tick() 第一步：清理過期 CANDIDATE。"""

    def test_old_candidates_cleaned(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO eod_prices VALUES ('2026-03-12','2330',100,105,95,100,1000)"
        )
        conn.execute(
            "INSERT INTO position_candidates VALUES ('2330','2026-03-10','test',1)",
        )
        conn.execute(
            "INSERT INTO position_candidates VALUES ('2317','2026-03-12','test',1)",
        )
        conn.commit()

        tick(conn, "9999")  # 對不存在的 symbol 呼叫 — 只做清理

        rows = conn.execute("SELECT * FROM position_candidates").fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "2317"  # 當日的保留


class TestTickHoldingPartial:
    """HOLDING_PARTIAL 狀態也應觸發時間止損。"""

    def test_holding_partial_triggers(self):
        conn = _make_db()
        conn.execute(
            "INSERT INTO positions VALUES (?,?,?,?,?,?,?)",
            ("3008", 50, 300, 250, -2500, "HOLDING_PARTIAL", "2026-02-01"),
        )
        _insert_eod_days(conn, "3008", "2026-02-01", 12)

        tick(conn, "3008")

        pos = conn.execute("SELECT state FROM positions WHERE symbol='3008'").fetchone()
        assert pos["state"] == "EXITING"
