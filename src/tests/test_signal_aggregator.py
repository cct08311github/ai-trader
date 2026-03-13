# src/tests/test_signal_aggregator.py
"""Tests for signal_aggregator.py — Regime-based 動態權重信號融合

覆蓋目標：aggregate() 三種 regime、漲停/跌停過濾、LLM cache miss、
action 閾值判斷（buy/sell/flat）。
"""
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from openclaw.signal_aggregator import (
    aggregate,
    AggregatedSignal,
    REGIME_WEIGHTS,
    SIGNAL_TO_SCORE,
    _BUY_ACTION_THRESHOLD,
    _SELL_ACTION_THRESHOLD,
    _BUY_SCORE_LIMIT_UP,
    _SELL_SCORE_LIMIT_DOWN,
)
from openclaw.market_regime import MarketRegimeResult, MarketRegime


def _mock_regime(regime_str, vol_mult=1.0):
    """建立 mock MarketRegimeResult。"""
    return MarketRegimeResult(
        regime=MarketRegime(regime_str),
        confidence=0.8,
        features={},
        volatility_multiplier=vol_mult,
    )


def _make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume INTEGER, PRIMARY KEY (trade_date, symbol)
    )""")
    conn.execute("""CREATE TABLE lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lm_cache_lookup ON lm_signal_cache (symbol, expires_at)")
    return conn


# ── Bull regime tests ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="buy")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_bull_buy_signal(mock_candles, mock_regime, mock_signal):
    """Bull regime + buy tech signal + no LLM cache → should produce buy action."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 1.0)

    conn = _make_db()
    snap = {"close": 105.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=105.0)

    assert isinstance(result, AggregatedSignal)
    assert result.regime == "bull"
    assert result.weights_used == REGIME_WEIGHTS["bull"]
    # tech=0.8(buy)*0.5 + llm=0.5*0.2 + risk_adj=0.5*0.3 = 0.4+0.1+0.15 = 0.65 → buy
    assert result.action == "buy"
    assert result.score >= _BUY_ACTION_THRESHOLD


@patch("openclaw.signal_aggregator.compute_signal", return_value="sell")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_bull_sell_signal(mock_candles, mock_regime, mock_signal):
    """Bull regime + sell tech signal + no LLM → should produce sell or flat."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 1.0)

    conn = _make_db()
    snap = {"close": 95.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=105.0)

    # tech=0.2(sell)*0.5 + llm=0.5*0.2 + risk=0.5*0.3 = 0.1+0.1+0.15 = 0.35 → sell
    assert result.action == "sell"
    assert result.score <= _SELL_ACTION_THRESHOLD


# ── Bear regime tests ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="flat")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_bear_flat_signal(mock_candles, mock_regime, mock_signal):
    """Bear regime + flat tech → risk_adj dominates → flat."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bear", 0.7)

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    assert result.regime == "bear"
    assert result.weights_used == REGIME_WEIGHTS["bear"]
    # Bear: tech=0.3, llm=0.2, risk=0.5
    # risk_adj = 0.5 / 0.7 ≈ 0.714
    # score = 0.5*0.3 + 0.5*0.2 + 0.714*0.5 = 0.15+0.1+0.357 = 0.607 → flat
    assert result.action == "flat"


# ── Range regime tests ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="buy")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_range_regime(mock_candles, mock_regime, mock_signal):
    """Range regime uses correct weights."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("range", 0.85)

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    assert result.regime == "range"
    assert result.weights_used == REGIME_WEIGHTS["range"]


# ── LLM cache hit tests ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="buy")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_llm_cache_hit_boosts_score(mock_candles, mock_regime, mock_signal):
    """LLM cache with bullish score pushes final score higher."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 1.0)

    conn = _make_db()
    import time as _t
    now = int(_t.time())
    conn.execute(
        "INSERT INTO lm_signal_cache VALUES (?,?,?,?,?,?,?,?)",
        ("c1", None, 0.9, "strategy_committee", "bull", "{}", now, now + 3600),
    )

    snap = {"close": 105.0, "reference": 100.0}
    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=105.0)

    # tech=0.8*0.5 + llm=0.9*0.2 + risk=0.5*0.3 = 0.4+0.18+0.15 = 0.73 → buy
    assert result.action == "buy"
    assert result.score > 0.65
    assert "strategy_committee" in " ".join(result.reasons)


@patch("openclaw.signal_aggregator.compute_signal", return_value="sell")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_llm_cache_bearish_pushes_sell(mock_candles, mock_regime, mock_signal):
    """LLM cache with bearish score (0.1) deepens sell."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bear", 0.7)

    conn = _make_db()
    import time as _t
    now = int(_t.time())
    conn.execute(
        "INSERT INTO lm_signal_cache VALUES (?,?,?,?,?,?,?,?)",
        ("c1", None, 0.1, "strategy_committee", "bear", "{}", now, now + 3600),
    )

    # Use close=95 to avoid triggering limit-down filter (95/100 = -5% < 9.5%)
    snap = {"close": 95.0, "reference": 100.0}
    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    # Bear weights: tech=0.3, llm=0.2, risk=0.5
    # tech=0.2*0.3 + llm=0.1*0.2 + risk=(0.5/0.7)*0.5 ≈ 0.06+0.02+0.357 = 0.437
    assert result.score < 0.5
    assert result.limit_filtered is False


# ── Limit up / limit down tests ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="buy")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_limit_up_caps_buy_score(mock_candles, mock_regime, mock_signal):
    """漲停板過濾：buy score 壓低到 0.3 上限。"""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 1.0)

    conn = _make_db()
    # close >= ref * 1.095 → 漲停
    snap = {"close": 110.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=110.0)

    assert result.limit_filtered is True
    assert "limit_up" in " ".join(result.reasons)
    # tech_score capped to 0.3 → lower final score
    # Bull: 0.3*0.5 + 0.5*0.2 + 0.5*0.3 = 0.15+0.1+0.15 = 0.4 → flat (not buy)
    assert result.action != "buy"


@patch("openclaw.signal_aggregator.compute_signal", return_value="sell")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_limit_down_floors_sell_score(mock_candles, mock_regime, mock_signal):
    """跌停板過濾：sell score 壓至 0.7（不追殺）。"""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bear", 0.7)

    conn = _make_db()
    # close <= ref * (1 - 0.095) = ref * 0.905 → 跌停
    snap = {"close": 90.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    assert result.limit_filtered is True
    assert "limit_down" in " ".join(result.reasons)
    # tech_score floored to 0.7 (instead of 0.2 for sell) → higher score → prevents panic sell
    # Bear: 0.7*0.3 + 0.5*0.2 + (0.5/0.7)*0.5 = 0.21+0.1+0.357 = 0.667 → flat (not sell!)
    assert result.action != "sell"


# ── Edge cases ──

@patch("openclaw.signal_aggregator.compute_signal", return_value="buy")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_insufficient_candles_defaults_to_range(mock_candles, mock_regime, mock_signal):
    """< 20 candles → _get_regime returns range regime."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 10  # < 20

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=None, high_water_mark=None)

    assert result.regime == "range"


@patch("openclaw.signal_aggregator.compute_signal", return_value="flat")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_zero_reference_no_limit_filter(mock_candles, mock_regime, mock_signal):
    """reference=0 → 不觸發漲跌停過濾。"""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("range", 0.85)

    conn = _make_db()
    snap = {"close": 200.0, "reference": 0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    assert result.limit_filtered is False


@patch("openclaw.signal_aggregator.compute_signal", return_value="flat")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_high_volatility_lowers_risk_adj(mock_candles, mock_regime, mock_signal):
    """高波動 (vol_mult=2.0) → risk_adj = 0.5/2.0 = 0.25 → 偏保守。"""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 2.0)

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    # risk_adj = max(0.1, min(0.9, 0.5/2.0)) = 0.25
    assert "risk_adj=0.25" in " ".join(result.reasons)


@patch("openclaw.signal_aggregator.compute_signal", return_value="flat")
@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
def test_reasons_list_populated(mock_candles, mock_regime, mock_signal):
    """Verify reasons list contains all expected components."""
    mock_candles.return_value = [{"close": 100, "volume": 1000}] * 30
    mock_regime.return_value = _mock_regime("bull", 1.0)

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}

    result = aggregate(conn, "2330", snap, position_avg_price=100.0, high_water_mark=None)

    reasons_str = " ".join(result.reasons)
    assert "regime=bull" in reasons_str
    assert "technical=" in reasons_str
    assert "llm=" in reasons_str
    assert "risk_adj=" in reasons_str
