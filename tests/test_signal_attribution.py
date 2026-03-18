"""tests/test_signal_attribution.py — 信號來源歸因測試

測試案例：
1. AggregatedSignal 包含 dominant_source 欄位
2. dominant_source 為加權貢獻最大的信號來源
3. SQL migration 可正常加入 signal_source 欄位
4. get_signal_attribution_report 回傳正確統計
5. get_signal_attribution_report 空表回傳空列表
"""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from openclaw.signal_aggregator import (
    AggregatedSignal,
    aggregate,
    get_signal_attribution_report,
)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE lm_signal_cache (
            cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
            source TEXT NOT NULL, direction TEXT, raw_json TEXT,
            created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            strategy_version TEXT NOT NULL,
            signal_side TEXT NOT NULL,
            signal_score REAL NOT NULL,
            signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
            llm_ref TEXT,
            reason_json TEXT NOT NULL,
            signal_source TEXT
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            status TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            qty INTEGER,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


# ─── Test 1: AggregatedSignal 有 dominant_source 欄位 ────────────────────────

def test_aggregated_signal_has_dominant_source():
    sig = AggregatedSignal(
        action="buy",
        score=0.7,
        regime="bull",
        weights_used={"technical": 0.5, "llm": 0.2, "risk_adj": 0.3},
        dominant_source="technical",
    )
    assert sig.dominant_source == "technical"


def test_aggregated_signal_default_dominant_source():
    """預設值應為 technical（向後相容）。"""
    sig = AggregatedSignal(
        action="flat",
        score=0.5,
        regime="range",
        weights_used={"technical": 0.4, "llm": 0.2, "risk_adj": 0.4},
    )
    assert sig.dominant_source == "technical"


# ─── Test 2: dominant_source 為加權貢獻最大項 ─────────────────────────────────

@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
@patch("openclaw.signal_aggregator.compute_signal")
@patch("openclaw.signal_aggregator.read_cache_with_fallback")
def test_dominant_source_technical(
    mock_cache, mock_compute, mock_candles, mock_regime
):
    """技術面分數最高時，dominant_source = technical。"""
    # bull regime: technical=0.50, llm=0.20, risk_adj=0.30
    mock_regime.return_value = MagicMock(regime=MagicMock(value="bull"), volatility_multiplier=1.0)
    mock_candles.return_value = [{"close": 100.0, "volume": 1000}] * 25
    mock_compute.return_value = "buy"    # tech_score = 0.8 → contribution = 0.50 * 0.8 = 0.40
    mock_cache.return_value = {"score": 0.5, "source": "llm"}  # llm contrib = 0.20 * 0.5 = 0.10

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}
    result = aggregate(conn, "2330", snap, None, None)

    # technical contribution (0.40) > llm (0.10) > risk_adj (0.50 * 0.30 = 0.15)
    # wait: risk_adj = max(0.1, min(0.9, 0.5/1.0)) = 0.5, risk_adj contribution = 0.30 * 0.5 = 0.15
    # technical = 0.40 > risk_adj = 0.15 > llm = 0.10
    assert result.dominant_source == "technical"


@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
@patch("openclaw.signal_aggregator.compute_signal")
@patch("openclaw.signal_aggregator.read_cache_with_fallback")
def test_dominant_source_llm(
    mock_cache, mock_compute, mock_candles, mock_regime
):
    """LLM 分數最高時，dominant_source = llm。"""
    # bear regime: technical=0.30, llm=0.20, risk_adj=0.50
    mock_regime.return_value = MagicMock(regime=MagicMock(value="bear"), volatility_multiplier=0.1)
    mock_candles.return_value = [{"close": 100.0, "volume": 1000}] * 25
    mock_compute.return_value = "flat"   # tech_score = 0.5 → contrib = 0.30 * 0.5 = 0.15
    # vol_mult=0.1 → risk_adj = min(0.9, 0.5/0.1)=0.9 → contrib = 0.50 * 0.9 = 0.45 (最大)
    # llm contrib = 0.20 * 0.9 = 0.18
    # Actually risk_adj would be highest here, let me use a scenario where llm wins
    # Use range regime: technical=0.40, llm=0.20, risk_adj=0.40
    # With vol_mult=5.0: risk_adj = max(0.1, 0.5/5) = 0.1 → contrib = 0.40*0.1=0.04
    # tech flat: 0.40 * 0.5 = 0.20, llm = 0.9: 0.20 * 0.9 = 0.18
    # Still tech wins. Let's use: tech=sell(0.2), llm=buy(1.0), high volatility
    mock_regime.return_value = MagicMock(regime=MagicMock(value="range"), volatility_multiplier=10.0)
    mock_compute.return_value = "sell"   # tech_score=0.2 → contrib=0.40*0.2=0.08
    mock_cache.return_value = {"score": 0.95, "source": "llm"}  # contrib=0.20*0.95=0.19
    # risk_adj=max(0.1,0.5/10)=0.1 → contrib=0.40*0.1=0.04

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}
    result = aggregate(conn, "2330", snap, None, None)

    # llm=0.19 > technical=0.08 > risk_adj=0.04
    assert result.dominant_source == "llm"


@patch("openclaw.signal_aggregator.classify_market_regime")
@patch("openclaw.signal_aggregator.fetch_candles")
@patch("openclaw.signal_aggregator.compute_signal")
@patch("openclaw.signal_aggregator.read_cache_with_fallback")
def test_dominant_source_risk_adj(
    mock_cache, mock_compute, mock_candles, mock_regime
):
    """risk_adj 貢獻最高時，dominant_source = risk_adj。"""
    # bear regime: risk_adj weight=0.50; vol_mult=0.1 → risk_adj=min(0.9,5.0)=0.9
    # risk_adj contrib = 0.50 * 0.9 = 0.45
    # tech flat: 0.30 * 0.5 = 0.15; llm neutral: 0.20 * 0.5 = 0.10
    mock_regime.return_value = MagicMock(regime=MagicMock(value="bear"), volatility_multiplier=0.1)
    mock_candles.return_value = [{"close": 100.0, "volume": 1000}] * 25
    mock_compute.return_value = "flat"
    mock_cache.return_value = None  # llm_score=0.5 (cache miss)

    conn = _make_db()
    snap = {"close": 100.0, "reference": 100.0}
    result = aggregate(conn, "2330", snap, None, None)

    assert result.dominant_source == "risk_adj"


# ─── Test 3: SQL migration 正常執行 ──────────────────────────────────────────

def test_migration_adds_signal_source_column(tmp_path):
    """migration_v1_3_1_signal_attribution.sql 成功加入 signal_source 欄位。"""
    import sqlite3 as _sql
    from pathlib import Path

    db_path = tmp_path / "test.db"
    conn = _sql.connect(str(db_path))
    conn.execute("""
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY, ts TEXT NOT NULL,
            symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
            strategy_version TEXT NOT NULL, signal_side TEXT NOT NULL,
            signal_score REAL NOT NULL, signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
            llm_ref TEXT, reason_json TEXT NOT NULL
        )
    """)
    conn.commit()

    # 執行 migration
    migration_path = Path("src/sql/migration_v1_3_1_signal_attribution.sql")
    conn.executescript(migration_path.read_text(encoding="utf-8"))
    conn.commit()

    # 確認欄位存在
    cols = {row[1] for row in conn.execute("PRAGMA table_info(decisions)").fetchall()}
    assert "signal_source" in cols
    conn.close()


# ─── Test 4: get_signal_attribution_report 空表 ───────────────────────────────

def test_attribution_report_empty_db():
    conn = _make_db()
    result = get_signal_attribution_report(conn, days=30)
    assert result == []


# ─── Test 5: get_signal_attribution_report 基本統計 ──────────────────────────

def test_attribution_report_counts():
    """有 decisions 資料時，按 signal_source 分組計數。"""
    conn = _make_db()
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    def _insert_decision(source: str, side: str, score: float):
        did = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO decisions
               (decision_id, ts, symbol, strategy_id, strategy_version,
                signal_side, signal_score, signal_ttl_ms, reason_json, signal_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (did, now, "2330", "v4", "4.0", side, score, 30000, "{}", source),
        )
        return did

    _insert_decision("technical", "buy", 0.8)
    _insert_decision("technical", "buy", 0.75)
    _insert_decision("llm", "sell", 0.3)
    conn.commit()

    result = get_signal_attribution_report(conn, days=30)

    # 應有兩組：technical(2) 和 llm(1)
    by_source = {r["source"]: r for r in result}
    assert "technical" in by_source
    assert "llm" in by_source
    assert by_source["technical"]["count"] == 2
    assert by_source["llm"]["count"] == 1
    # 無 filled orders → win_rate = None
    assert by_source["technical"]["win_rate"] is None
    assert by_source["llm"]["win_rate"] is None
