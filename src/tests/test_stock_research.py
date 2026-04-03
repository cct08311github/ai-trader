"""test_stock_research.py — 個股研究 Agent 測試"""
import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from openclaw.agents.stock_research import (
    _ensure_table,
    _sanitize_for_prompt,
    _VALID_RATINGS,
    layer1_technical,
    layer2_institutional,
    layer3_llm_synthesis,
    generate_report,
    run_stock_research,
    _MAX_STOCKS_PER_DAY,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS eod_prices (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_institution_flows (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS eod_margin_data (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            margin_balance REAL, short_balance REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE IF NOT EXISTS llm_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            component TEXT, agent TEXT, model TEXT,
            prompt_text TEXT, response_text TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            latency_ms INTEGER, confidence REAL,
            metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT, target_rule TEXT, rule_category TEXT,
            current_value TEXT, proposed_value TEXT,
            supporting_evidence TEXT, confidence REAL,
            requires_human_approval INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            proposal_json TEXT,
            created_at INTEGER
        );
    """)
    _ensure_table(conn)


def _seed_eod_prices(conn, symbol, dates_ohlcv):
    """dates_ohlcv: list of (date_str, open, high, low, close, volume)"""
    for row in dates_ohlcv:
        conn.execute(
            "INSERT INTO eod_prices (trade_date, symbol, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?)",
            (row[0], symbol, row[1], row[2], row[3], row[4], row[5]),
        )
    conn.commit()


def _seed_institution_flows(conn, symbol, rows):
    """rows: list of (date_str, foreign_net, trust_net)"""
    for r in rows:
        conn.execute(
            "INSERT INTO eod_institution_flows "
            "(trade_date, symbol, foreign_net, trust_net, dealer_net, total_net) "
            "VALUES (?,?,?,?,0,?)",
            (r[0], symbol, r[1], r[2], r[1] + r[2]),
        )
    conn.commit()


def _seed_margin_data(conn, symbol, rows):
    """rows: list of (date_str, margin_balance)"""
    for r in rows:
        conn.execute(
            "INSERT INTO eod_margin_data (trade_date, symbol, margin_balance, short_balance) "
            "VALUES (?,?,?,0)",
            (r[0], symbol, r[1]),
        )
    conn.commit()


def _make_price_series(base_date_prefix="2025-03", n=30, start_price=500.0):
    """Generate n days of OHLCV data."""
    data = []
    price = start_price
    for i in range(1, n + 1):
        d = f"{base_date_prefix}-{i:02d}"
        o = price
        h = price * 1.02
        l = price * 0.98
        c = price + (i % 3 - 1) * 2  # oscillate slightly
        v = 5000 + i * 100
        data.append((d, o, h, l, c, v))
        price = c
    return data


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    yield conn
    conn.close()


# ── Tests: _ensure_table ─────────────────────────────────────────────────────


def test_ensure_table_creates_stock_research_reports(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='stock_research_reports'"
    ).fetchone()
    assert row is not None


# ── Tests: layer1_technical ──────────────────────────────────────────────────


def test_layer1_technical_no_data(db):
    result = layer1_technical(db, "9999", "2025-03-20")
    assert result.get("error") == "no_data"


def test_layer1_technical_basic(db):
    prices = _make_price_series(n=30, start_price=500.0)
    _seed_eod_prices(db, "2330", prices)
    result = layer1_technical(db, "2330", "2025-03-30")
    assert result["symbol"] == "2330"
    assert result["close"] is not None
    assert result["ma5"] is not None
    assert result["ma20"] is not None
    assert result["rsi14"] is not None
    assert result["trend"] in ("bullish", "bearish", "neutral", "strong_bullish", "strong_bearish")
    assert "macd" in result
    assert result["support"] > 0 or result["resistance"] > 0


def test_layer1_technical_volume_ratio(db):
    prices = _make_price_series(n=10, start_price=100.0)
    # Make last day volume much higher
    last = list(prices[-1])
    last[5] = 50000  # spike volume
    prices[-1] = tuple(last)
    _seed_eod_prices(db, "TEST", prices)
    result = layer1_technical(db, "TEST", "2025-03-10")
    assert result["volume_ratio"] is not None
    assert result["volume_ratio"] > 1.0


# ── Tests: layer2_institutional ──────────────────────────────────────────────


def test_layer2_institutional_no_data(db):
    result = layer2_institutional(db, "9999", "2025-03-20")
    assert result["foreign_consecutive_buy"] == 0
    assert result["trust_consecutive_buy"] == 0


def test_layer2_institutional_consecutive(db):
    flows = [
        ("2025-03-20", 500, 200),
        ("2025-03-19", 300, 100),
        ("2025-03-18", 400, 150),
        ("2025-03-17", -100, 50),
    ]
    _seed_institution_flows(db, "2330", flows)
    result = layer2_institutional(db, "2330", "2025-03-20")
    assert result["foreign_consecutive_buy"] == 3
    assert result["recent_5d_total_net"] > 0


def test_layer2_margin_trend_decreasing(db):
    margin = [
        ("2025-03-20", 1000),
        ("2025-03-19", 1100),
        ("2025-03-18", 1200),
    ]
    _seed_margin_data(db, "2330", margin)
    result = layer2_institutional(db, "2330", "2025-03-20")
    assert result["margin_trend"] == "decreasing"


def test_layer2_margin_trend_increasing(db):
    margin = [
        ("2025-03-20", 1200),
        ("2025-03-19", 1100),
        ("2025-03-18", 1000),
    ]
    _seed_margin_data(db, "2330", margin)
    result = layer2_institutional(db, "2330", "2025-03-20")
    assert result["margin_trend"] == "increasing"


# ── Tests: layer3_llm_synthesis ──────────────────────────────────────────────


@patch("openclaw.agents.stock_research.call_agent_llm")
def test_layer3_llm_synthesis(mock_llm):
    mock_llm.return_value = {
        "rating": "B",
        "entry_price": 580.0,
        "stop_loss": 555.0,
        "target_price": 630.0,
        "confidence": 0.72,
        "rationale": "技術面多頭排列 + 外資連買",
        "risk_notes": ["半導體風險"],
    }
    tech = {"symbol": "2330", "close": 590, "trend": "bullish"}
    inst = {"symbol": "2330", "foreign_consecutive_buy": 3}
    result = layer3_llm_synthesis(tech, inst, "2330")
    assert result["rating"] == "B"
    assert result["entry_price"] == 580.0
    assert result["confidence"] == 0.72
    assert "半導體風險" in result["risk_notes"]


@patch("openclaw.agents.stock_research.call_agent_llm")
def test_layer3_llm_synthesis_fallback(mock_llm):
    mock_llm.return_value = {"summary": "LLM error", "_error": "timeout"}
    result = layer3_llm_synthesis({}, {}, "TEST")
    assert result["rating"] == "C"  # default fallback on error
    assert result["confidence"] == 0.0  # safe default on LLM error


# ── Tests: generate_report ───────────────────────────────────────────────────


def test_generate_report_basic():
    layers = {
        "technical": {"close": 590, "ma5": 585, "ma20": 570, "ma60": 550,
                       "rsi14": 62, "trend": "bullish", "volume_ratio": 1.3,
                       "support": 560, "resistance": 610},
        "institutional": {"foreign_consecutive_buy": 3, "trust_consecutive_buy": 1,
                           "recent_5d_total_net": 5000, "margin_trend": "decreasing"},
        "synthesis": {"rating": "B", "entry_price": 580, "stop_loss": 555,
                       "target_price": 630, "confidence": 0.72,
                       "rationale": "技術面多頭排列", "risk_notes": ["系統風險"]},
    }
    md = generate_report("2330", layers)
    assert "# 2330" in md
    assert "評級: B" in md
    assert "580" in md
    assert "系統風險" in md


def test_generate_report_no_prices():
    layers = {
        "technical": {"close": 100},
        "institutional": {"foreign_consecutive_buy": 0, "trust_consecutive_buy": 0,
                           "recent_5d_total_net": 0, "margin_trend": "unknown"},
        "synthesis": {"rating": "D", "confidence": 0.3, "rationale": "風險高",
                       "risk_notes": []},
    }
    md = generate_report("9999", layers)
    assert "D" in md
    assert "進場" not in md  # no entry_price → no entry line


# ── Tests: run_stock_research ────────────────────────────────────────────────


@patch("openclaw.agents.stock_research.call_agent_llm")
@patch("openclaw.agents.stock_research._load_watchlist")
def test_run_stock_research_empty_watchlist(mock_wl, mock_llm, db):
    mock_wl.return_value = []
    result = run_stock_research(trade_date="2025-03-20", conn=db)
    assert result.success is False
    assert "空" in result.summary
    mock_llm.assert_not_called()


@patch("openclaw.agents.stock_research.write_trace")
@patch("openclaw.agents.stock_research.call_agent_llm")
@patch("openclaw.agents.stock_research._load_watchlist")
def test_run_stock_research_with_data(mock_wl, mock_llm, mock_trace, db):
    mock_wl.return_value = ["2330"]
    mock_llm.return_value = {
        "rating": "B",
        "entry_price": 580.0,
        "stop_loss": 555.0,
        "target_price": 630.0,
        "confidence": 0.72,
        "rationale": "看好",
    }
    prices = _make_price_series(n=30, start_price=500.0)
    _seed_eod_prices(db, "2330", prices)
    _seed_institution_flows(db, "2330", [
        ("2025-03-30", 500, 200),
        ("2025-03-29", 300, 100),
    ])

    result = run_stock_research(trade_date="2025-03-30", conn=db)
    assert result.success is True
    assert "B級 1" in result.summary

    # Check DB write
    row = db.execute(
        "SELECT * FROM stock_research_reports WHERE symbol='2330'"
    ).fetchone()
    assert row is not None
    assert row["rating"] == "B"

    # B-rated should create proposal
    proposals = db.execute("SELECT * FROM strategy_proposals").fetchall()
    assert len(proposals) == 1


@patch("openclaw.agents.stock_research.write_trace")
@patch("openclaw.agents.stock_research.call_agent_llm")
@patch("openclaw.agents.stock_research._load_watchlist")
def test_run_stock_research_c_rated_no_proposal(mock_wl, mock_llm, mock_trace, db):
    mock_wl.return_value = ["2330"]
    mock_llm.return_value = {
        "rating": "C",
        "confidence": 0.4,
        "rationale": "中性觀察",
    }
    prices = _make_price_series(n=30, start_price=500.0)
    _seed_eod_prices(db, "2330", prices)

    result = run_stock_research(trade_date="2025-03-30", conn=db)
    assert result.success is True
    assert result.action_type == "observe"
    proposals = db.execute("SELECT * FROM strategy_proposals").fetchall()
    assert len(proposals) == 0


@patch("openclaw.agents.stock_research.write_trace")
@patch("openclaw.agents.stock_research.call_agent_llm")
@patch("openclaw.agents.stock_research._load_watchlist")
def test_run_stock_research_skips_no_data_symbol(mock_wl, mock_llm, mock_trace, db):
    mock_wl.return_value = ["NODATA", "2330"]
    mock_llm.return_value = {
        "rating": "C",
        "confidence": 0.5,
        "rationale": "ok",
    }
    prices = _make_price_series(n=30, start_price=500.0)
    _seed_eod_prices(db, "2330", prices)

    result = run_stock_research(trade_date="2025-03-30", conn=db)
    assert result.success is True
    assert len(result.raw["reports"]) == 1  # only 2330, NODATA skipped


@patch("openclaw.agents.stock_research.write_trace")
@patch("openclaw.agents.stock_research.call_agent_llm")
@patch("openclaw.agents.stock_research._load_watchlist")
def test_run_stock_research_a_rated_requires_human_approval(mock_wl, mock_llm, mock_trace, db):
    mock_wl.return_value = ["2330"]
    mock_llm.return_value = {
        "rating": "A",
        "entry_price": 580.0,
        "stop_loss": 555.0,
        "target_price": 650.0,
        "confidence": 0.85,
        "rationale": "強烈看好",
    }
    prices = _make_price_series(n=30, start_price=500.0)
    _seed_eod_prices(db, "2330", prices)

    result = run_stock_research(trade_date="2025-03-30", conn=db)
    assert result.success is True

    proposal = db.execute("SELECT * FROM strategy_proposals").fetchone()
    assert proposal is not None
    assert proposal["requires_human_approval"] == 1


def test_max_stocks_cap():
    assert _MAX_STOCKS_PER_DAY == 10

# ── Tests: _sanitize_for_prompt ─────────────────────────────────────────────


def test_sanitize_for_prompt_strips_control_chars():
    dirty = "hello\x00world\x1ftest"
    assert _sanitize_for_prompt(dirty) == "helloworldtest"


def test_sanitize_for_prompt_truncates():
    long_text = "a" * 500
    assert len(_sanitize_for_prompt(long_text, max_len=100)) == 100


def test_sanitize_for_prompt_non_string():
    assert _sanitize_for_prompt(12345) == "12345"


# ── Tests: _VALID_RATINGS ──────────────────────────────────────────────────


def test_valid_ratings_whitelist():
    assert _VALID_RATINGS == {"A", "B", "C", "D"}


@patch("openclaw.agents.stock_research.call_agent_llm")
def test_layer3_invalid_rating_defaults_to_c(mock_llm):
    mock_llm.return_value = {
        "rating": "S",  # invalid
        "confidence": 0.9,
        "rationale": "test",
    }
    result = layer3_llm_synthesis({}, {}, "TEST")
    assert result["rating"] == "C"  # whitelist fallback


@patch("openclaw.agents.stock_research.call_agent_llm")
def test_layer3_llm_error_returns_safe_defaults(mock_llm):
    mock_llm.return_value = {"_error": "rate_limit"}
    result = layer3_llm_synthesis({}, {}, "TEST")
    assert result["rating"] == "C"
    assert result["confidence"] == 0.0
    assert result["entry_price"] is None
    assert "rate_limit" in result["rationale"]
