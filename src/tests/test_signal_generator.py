"""test_signal_generator.py — EOD 日線驅動信號生成器測試"""
import sqlite3
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
import random

_TZ_TWN = timezone(timedelta(hours=8))


@pytest.fixture
def db_with_eod(tmp_path):
    """建立有 eod_prices 資料的測試 DB（20 天模擬日線）"""
    conn = sqlite3.connect(str(tmp_path / "trades.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY (trade_date, symbol)
    )""")
    random.seed(1)
    price = 800.0
    for i in range(20):
        d = (date(2026, 2, 1) + timedelta(days=i)).isoformat()
        price = price * (1 + random.uniform(-0.02, 0.02))
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, "2330", price * 0.99, price * 1.01, price * 0.98, price, 1e6))
    conn.commit()
    return conn


def test_signal_generator_returns_signal(db_with_eod):
    """從 eod_prices 計算技術指標並回傳有效信號"""
    from openclaw.signal_generator import compute_signal
    result = compute_signal(db_with_eod, symbol="2330",
                            position_avg_price=None, high_water_mark=None)
    assert result in ("buy", "sell", "flat")


def test_signal_generator_returns_flat_for_unknown_symbol(db_with_eod):
    """無資料的股票應回傳 flat"""
    from openclaw.signal_generator import compute_signal
    result = compute_signal(db_with_eod, symbol="9999",
                            position_avg_price=None, high_water_mark=None)
    assert result == "flat"


def test_signal_generator_sell_when_trailing_triggered(db_with_eod):
    """Trailing Stop 觸發時回傳 sell"""
    from openclaw.signal_generator import compute_signal
    conn = db_with_eod
    latest = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol='2330' ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()[0]
    # high_water_mark 是最新收盤的兩倍，必定觸發 trailing
    result = compute_signal(conn, "2330",
                            position_avg_price=latest * 0.5,
                            high_water_mark=latest * 2.0)
    assert result == "sell"


def test_signal_generator_flat_when_insufficient_data(tmp_path):
    """資料不足（< 5 根）應回傳 flat"""
    from openclaw.signal_generator import compute_signal
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY (trade_date, symbol)
    )""")
    conn.execute("INSERT INTO eod_prices VALUES ('2026-02-01','2330',100,101,99,100,1e5)")
    conn.commit()
    result = compute_signal(conn, "2330", position_avg_price=None, high_water_mark=None)
    assert result == "flat"


def test_signal_generator_stop_loss_triggers(db_with_eod):
    """close < avg_price * (1 - stop_loss_pct) 應觸發 sell"""
    from openclaw.signal_generator import compute_signal
    conn = db_with_eod
    latest = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol='2330' ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()[0]
    # avg_price 遠高於現價（-30% 虧損）→ 止損
    result = compute_signal(conn, "2330",
                            position_avg_price=latest * 1.5,
                            high_water_mark=latest * 1.5)
    assert result == "sell"


# ---------------------------------------------------------------------------
# max_date / intraday filtering tests (Issue #247)
# ---------------------------------------------------------------------------

def _make_db_with_today(tmp_path, today_str: str):
    """建立含今日（不完整）資料的 DB，今日 close 設為異常高值以便偵測。"""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY (trade_date, symbol)
    )""")
    # 20 天歷史（正常價格）
    price = 500.0
    random.seed(42)
    for i in range(20):
        d = (date(2026, 2, 1) + timedelta(days=i)).isoformat()
        price = price * (1 + random.uniform(-0.01, 0.01))
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, "2330", price, price * 1.01, price * 0.99, price, 1e6))
    # 當日不完整資料（close = 99999 — 異常高，若混入必然失真）
    conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
        (today_str, "2330", 99999, 99999, 99999, 99999, 0))
    conn.commit()
    return conn


def test_fetch_candles_excludes_today_during_market_hours(tmp_path):
    """盤中（TWN hour < 14）_fetch_candles 應排除當日資料。"""
    from openclaw.signal_generator import _fetch_candles
    today_str = "2026-03-17"
    conn = _make_db_with_today(tmp_path, today_str)

    # 模擬 TWN 時間 10:30（盤中）
    mock_now = datetime(2026, 3, 17, 10, 30, tzinfo=_TZ_TWN)
    with patch("openclaw.signal_generator.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        candles = _fetch_candles(conn, "2330")

    assert all(c["date"] < today_str for c in candles), \
        "盤中不應包含當日 EOD 資料"
    assert all(c["close"] < 9000 for c in candles), \
        "close 不應包含異常的 99999"


def test_fetch_candles_includes_today_after_market_close(tmp_path):
    """盤後（TWN hour >= 14）_fetch_candles 應包含當日資料。"""
    from openclaw.signal_generator import _fetch_candles
    today_str = "2026-03-17"
    conn = _make_db_with_today(tmp_path, today_str)

    mock_now = datetime(2026, 3, 17, 14, 35, tzinfo=_TZ_TWN)
    with patch("openclaw.signal_generator.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        candles = _fetch_candles(conn, "2330")

    dates = [c["date"] for c in candles]
    assert today_str in dates, "盤後應包含當日資料"


def test_fetch_candles_explicit_max_date_respected(tmp_path):
    """明確傳入 max_date 時，應以該日期為上限。"""
    from openclaw.signal_generator import _fetch_candles
    today_str = "2026-03-17"
    conn = _make_db_with_today(tmp_path, today_str)

    candles = _fetch_candles(conn, "2330", max_date="2026-02-15")
    assert all(c["date"] <= "2026-02-15" for c in candles)


def test_compute_signal_passes_max_date(tmp_path):
    """compute_signal 支援明確傳入 max_date。"""
    from openclaw.signal_generator import compute_signal
    today_str = "2026-03-17"
    conn = _make_db_with_today(tmp_path, today_str)

    # 明確排除今日
    result = compute_signal(conn, "2330",
                            position_avg_price=None, high_water_mark=None,
                            max_date="2026-02-20")
    assert result in ("buy", "sell", "flat")
