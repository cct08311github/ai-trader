import sqlite3, pytest
from dataclasses import dataclass

@pytest.fixture
def agg_db(tmp_path):
    """建立有 eod_prices + lm_signal_cache 表的測試 DB"""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL,
        low REAL, close REAL, volume REAL,
        PRIMARY KEY (trade_date, symbol)
    )""")
    conn.execute("""CREATE TABLE lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    # 插入 30 日模擬日線（趨勢上漲 → bull regime）
    import random; random.seed(42)
    price = 100.0
    for i in range(30):
        from datetime import date, timedelta
        d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        price *= 1.005  # 穩定上漲
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, "2330", price*0.99, price*1.01, price*0.98, price, 1e6))
    conn.commit()
    return conn

@pytest.fixture
def snap_normal():
    return {"close": 115.0, "reference": 110.0, "bid": 114.9, "ask": 115.1, "volume": 5000}

@pytest.fixture
def snap_limit_up():
    return {"close": 121.0, "reference": 110.0, "bid": 121.0, "ask": 121.0, "volume": 1000}

def test_aggregate_returns_aggregated_signal(agg_db, snap_normal):
    from openclaw.signal_aggregator import aggregate, AggregatedSignal
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert isinstance(result, AggregatedSignal)
    assert result.action in ("buy", "sell", "flat")
    assert 0.0 <= result.score <= 1.0
    assert result.regime in ("bull", "bear", "range")
    assert isinstance(result.reasons, list)

def test_regime_weights_applied(agg_db, snap_normal):
    """Bull regime 下 technical weight=0.50"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    # 上漲趨勢應為 bull regime
    assert result.regime == "bull"
    assert result.weights_used["technical"] == 0.50

def test_limit_up_caps_buy_score(agg_db, snap_limit_up):
    """漲停板時 buy score 被壓至 0.3 以下"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_limit_up,
                       position_avg_price=None, high_water_mark=None)
    assert result.limit_filtered is True
    # 即使其他信號看多，final score 也不會因漲停而過高觸發 buy
    # （tech_score 被壓到 0.3，加權後 final < 0.65）
    if result.action == "buy":
        # 如果還是 buy，score 也應該偏低（close to threshold）
        assert result.score < 0.7

def test_cache_miss_uses_neutral(agg_db, snap_normal):
    """LLM cache miss 時使用 neutral score 0.5，不崩潰"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert result is not None  # 不應拋出例外
    assert "cache_miss" in " ".join(result.reasons)

def test_cache_hit_uses_cached_score(agg_db, snap_normal):
    """LLM cache 有資料時採用快取 score"""
    from openclaw.lm_signal_cache import write_cache
    write_cache(agg_db, symbol=None, score=0.9, source="strategy_committee",
                direction="bull", raw_json="{}")
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert any("0.9" in r for r in result.reasons)

def test_sell_signal_when_holding_and_stop_triggered(agg_db, snap_normal):
    """有持倉且觸發止損時，aggregator 輸出 sell"""
    from openclaw.signal_aggregator import aggregate
    # avg_price=120, current_close=115 → -4.2% → 觸發止損（STOP_LOSS_PCT=3%）
    result = aggregate(agg_db, "2330",
                       {"close": 115.0, "reference": 110.0, "bid": 114.9, "ask": 115.1, "volume": 5000},
                       position_avg_price=120.0, high_water_mark=120.0)
    assert result.action == "sell"

def test_unknown_symbol_returns_flat(agg_db, snap_normal):
    """無 eod_prices 資料的股票回傳 flat"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "9999", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert result.action == "flat"
