import sqlite3, time, pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

_TZ_TWN = timezone(timedelta(hours=8))

@pytest.fixture
def cache_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    conn.commit()
    return conn

def test_write_and_read_global_cache(cache_db):
    """寫入全市場信號後能讀取"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None, score=0.7, source="strategy_committee",
                direction="bull", raw_json='{"summary":"bullish"}')
    result = read_cache(cache_db, symbol=None)
    assert result is not None
    assert result["score"] == 0.7
    assert result["direction"] == "bull"
    assert result["source"] == "strategy_committee"

def test_cache_miss_returns_none(cache_db):
    """無快取時回傳 None"""
    from openclaw.lm_signal_cache import read_cache
    result = read_cache(cache_db, symbol="2330")
    assert result is None

def test_expired_cache_returns_none(cache_db):
    """過期快取應視為 miss"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None, score=0.8, source="test",
                direction="bull", raw_json="{}", ttl_seconds=-1)  # 立即過期
    result = read_cache(cache_db, symbol=None)
    assert result is None

def test_symbol_specific_cache_takes_priority(cache_db):
    """個股快取優先於全市場快取（read_cache 精確查詢）"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None,   score=0.5, source="global", direction="neutral", raw_json="{}")
    write_cache(cache_db, symbol="2330", score=0.9, source="stock",  direction="bull",    raw_json="{}")
    result = read_cache(cache_db, symbol="2330")
    assert result["score"] == 0.9
    assert result["source"] == "stock"

def test_fallback_to_global_when_symbol_miss(cache_db):
    """個股 miss 時 fallback 至全市場快取"""
    from openclaw.lm_signal_cache import write_cache, read_cache_with_fallback
    write_cache(cache_db, symbol=None, score=0.6, source="global", direction="bear", raw_json="{}")
    result = read_cache_with_fallback(cache_db, symbol="9999")
    assert result["score"] == 0.6

def test_purge_expired(cache_db):
    """purge_expired 清除過期記錄，保留未過期記錄"""
    from openclaw.lm_signal_cache import write_cache, purge_expired, read_cache
    write_cache(cache_db, symbol=None, score=0.5, source="test",
                direction="neutral", raw_json="{}", ttl_seconds=-1)   # 過期
    write_cache(cache_db, symbol=None, score=0.7, source="test2",
                direction="bull", raw_json="{}", ttl_seconds=3600)    # 未過期
    purge_expired(cache_db)
    count = cache_db.execute("SELECT COUNT(*) FROM lm_signal_cache").fetchone()[0]
    assert count == 1  # 只剩未過期的

def test_write_returns_cache_id(cache_db):
    """write_cache 回傳新建的 cache_id"""
    from openclaw.lm_signal_cache import write_cache
    cid = write_cache(cache_db, symbol=None, score=0.5, source="test",
                      direction="neutral", raw_json="{}")
    assert isinstance(cid, str) and len(cid) > 0


# ---------------------------------------------------------------------------
# TTL 動態計算測試 (Issue #248)
# ---------------------------------------------------------------------------

def test_ttl_to_market_close_before_close(cache_db):
    """盤中（TWN < 13:30）TTL 應大於 0 且不超過 5 小時。"""
    from openclaw.lm_signal_cache import _ttl_to_market_close
    mock_now = datetime(2026, 3, 17, 9, 0, tzinfo=_TZ_TWN)   # 09:00 TWN
    with patch("openclaw.lm_signal_cache.datetime") as m:
        m.now.return_value = mock_now
        ttl = _ttl_to_market_close()
    # 09:00 → 13:30 = 4.5h = 16200s
    assert 16000 < ttl < 17000


def test_ttl_to_market_close_after_close_returns_min(cache_db):
    """盤後（TWN > 13:30）TTL 應回傳 _MIN_TTL_SECONDS。"""
    from openclaw.lm_signal_cache import _ttl_to_market_close, _MIN_TTL_SECONDS
    mock_now = datetime(2026, 3, 17, 14, 0, tzinfo=_TZ_TWN)   # 14:00 TWN（盤後）
    with patch("openclaw.lm_signal_cache.datetime") as m:
        m.now.return_value = mock_now
        ttl = _ttl_to_market_close()
    assert ttl == _MIN_TTL_SECONDS


def test_write_cache_default_ttl_lasts_to_market_close(cache_db):
    """預設 TTL write_cache 後，09:00 寫入應在 13:29 仍有效。"""
    from openclaw.lm_signal_cache import write_cache, read_cache

    # Simulate write at 09:00 TWN
    write_time = datetime(2026, 3, 17, 9, 0, tzinfo=_TZ_TWN)
    with patch("openclaw.lm_signal_cache.datetime") as m:
        m.now.return_value = write_time
        write_cache(cache_db, symbol=None, score=0.75, source="committee",
                    direction="bull", raw_json="{}")

    # At 13:29 TWN the entry should still be readable (expires_at > now)
    close_minus_1m = int(datetime(2026, 3, 17, 13, 29, tzinfo=_TZ_TWN).timestamp())
    row = cache_db.execute(
        "SELECT expires_at FROM lm_signal_cache ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row[0] > close_minus_1m, "cache 應在 13:29 仍有效"


def test_write_cache_explicit_ttl_not_overridden(cache_db):
    """明確傳入 ttl_seconds 時，不使用動態計算。"""
    from openclaw.lm_signal_cache import write_cache
    import time as _time
    before = int(_time.time())
    write_cache(cache_db, symbol=None, score=0.5, source="test",
                direction="neutral", raw_json="{}", ttl_seconds=60)
    row = cache_db.execute(
        "SELECT expires_at, created_at FROM lm_signal_cache ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert abs(row[0] - row[1] - 60) <= 2  # expires_at ≈ created_at + 60
