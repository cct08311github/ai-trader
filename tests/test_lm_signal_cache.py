import sqlite3, time, pytest

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
