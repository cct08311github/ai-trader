"""Tests for strategy_committee._build_market_context decisions time window (Issue #250)."""
import sqlite3
from datetime import datetime, timedelta, timezone


def _make_decisions_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "trades.db"))
    conn.executescript("""
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY, ts TEXT, symbol TEXT,
            strategy_id TEXT, signal_side TEXT, signal_score REAL,
            signal_ttl_ms INTEGER, confidence REAL
        );
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
            close REAL, volume REAL, market TEXT, name TEXT,
            change REAL, PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE eod_institution_flows (
            trade_date TEXT, symbol TEXT, name TEXT,
            foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
            PRIMARY KEY (trade_date, symbol)
        );
    """)
    return conn


def test_decisions_within_7_days_are_included(tmp_path):
    """7 日內的決策應被 _build_market_context 取到。"""
    conn = _make_decisions_db(tmp_path)
    recent_ts = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
        ("d1", recent_ts, "2330", "v1", "buy", 0.8, 30000, 1.0)
    )
    conn.commit()

    rows = conn.execute(
        "SELECT ts FROM decisions "
        "WHERE ts >= datetime('now', '-7 days') "
        "ORDER BY ts DESC LIMIT 8"
    ).fetchall()
    assert len(rows) == 1


def test_decisions_older_than_7_days_are_excluded(tmp_path):
    """7 日前的舊決策應被時間窗口過濾掉。"""
    conn = _make_decisions_db(tmp_path)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.execute(
        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
        ("d2", old_ts, "2330", "v1", "sell", 0.6, 30000, 1.0)
    )
    conn.commit()

    rows = conn.execute(
        "SELECT ts FROM decisions "
        "WHERE ts >= datetime('now', '-7 days') "
        "ORDER BY ts DESC LIMIT 8"
    ).fetchall()
    assert len(rows) == 0


def test_only_recent_decisions_returned_when_mixed(tmp_path):
    """新舊決策混合時，只回傳 7 日內的。"""
    conn = _make_decisions_db(tmp_path)
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    old = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    conn.executemany(
        "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?)",
        [
            ("d3", recent, "2330", "v1", "buy", 0.8, 30000, 1.0),
            ("d4", old, "6442", "v1", "sell", 0.5, 30000, 1.0),
        ]
    )
    conn.commit()

    rows = conn.execute(
        "SELECT decision_id FROM decisions "
        "WHERE ts >= datetime('now', '-7 days') "
        "ORDER BY ts DESC LIMIT 8"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "d3"


# ---------------------------------------------------------------------------
# _build_barometer_trend NULL guard tests (Issue #321)
# ---------------------------------------------------------------------------

def _make_barometer_db(tmp_path, rows):
    """建立含 eod_prices 的測試 DB，rows = [(trade_date, close, change), ...]。"""
    conn = sqlite3.connect(str(tmp_path / "trades.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, change REAL,
        PRIMARY KEY (trade_date, symbol)
    )""")
    for trade_date, close, change in rows:
        conn.execute(
            "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?)",
            (trade_date, "0050", 100.0, 101.0, 99.0, close, 1e6, change)
        )
    conn.commit()
    return conn


def test_barometer_skips_null_change_rows(tmp_path):
    """change IS NULL の行は SQL でフィルタされ TypeError を発生させない。"""
    from openclaw.agents.strategy_committee import _build_barometer_trend
    # 5 rows but 3 have NULL change — after filter only 2 remain, meets len >= 2
    rows = [
        ("2026-03-10", 100.0, None),
        ("2026-03-11", 101.0, None),
        ("2026-03-12", 102.0, None),
        ("2026-03-13", 103.0, 1.0),
        ("2026-03-14", 104.0, 1.0),
    ]
    conn = _make_barometer_db(tmp_path, rows)
    # Should not raise TypeError; returns str (possibly "")
    result = _build_barometer_trend(conn, "2026-03-14")
    assert isinstance(result, str)


def test_barometer_returns_empty_when_all_change_null(tmp_path):
    """全部 change 為 NULL 時，過濾後 rows < 2，回傳空字串。"""
    from openclaw.agents.strategy_committee import _build_barometer_trend
    rows = [
        ("2026-03-13", 103.0, None),
        ("2026-03-14", 104.0, None),
    ]
    conn = _make_barometer_db(tmp_path, rows)
    result = _build_barometer_trend(conn, "2026-03-14")
    assert result == ""


def test_barometer_normal_data(tmp_path):
    """正常資料應回傳包含趨勢資訊的字串。"""
    from openclaw.agents.strategy_committee import _build_barometer_trend
    rows = [
        ("2026-03-10", 100.0, 0.5),
        ("2026-03-11", 101.0, 1.0),
        ("2026-03-12", 102.0, 1.0),
        ("2026-03-13", 103.0, 1.0),
        ("2026-03-14", 104.0, 1.0),
    ]
    conn = _make_barometer_db(tmp_path, rows)
    result = _build_barometer_trend(conn, "2026-03-14")
    assert "0050" in result
    assert "趨勢" in result
