import json
import sqlite3
from datetime import date, timedelta
import pytest
from openclaw.agents.eod_analysis import run_eod_analysis


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE eod_prices (
            trade_date TEXT, market TEXT, symbol TEXT, name TEXT,
            close REAL, change REAL, open REAL, high REAL, low REAL,
            volume REAL, turnover REAL, trades REAL, source_url TEXT,
            ingested_at TEXT,
            PRIMARY KEY (trade_date, market, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE institution_flows (
            trade_date TEXT, symbol TEXT,
            foreign_net REAL, investment_trust_net REAL,
            dealer_net REAL, total_net REAL, health_score REAL,
            source_url TEXT, ingested_at TEXT,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            qty REAL, avg_cost REAL, current_price REAL,
            unrealized_pnl REAL, last_updated TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY, component TEXT, agent TEXT,
            model TEXT, prompt_text TEXT, response_text TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            latency_ms INTEGER, confidence REAL,
            metadata TEXT, created_at INTEGER NOT NULL
        )
    """)
    # 插入持倉，使 _calc_symbol_indicators 有目標股票
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?)",
        ("2330", 1000.0, 500.0, 559.0, 59000.0, "2026-01-28")
    )
    # 插入 60 天假資料（唯一日期，從 2025-11-30 起算，使 i=59 落在 2026-01-28）
    base = date(2025, 11, 30)
    for i in range(60):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, "TWSE", "2330", "台積電",
             500.0 + i, float(i % 5 - 2), 498.0 + i,
             505.0 + i, 495.0 + i, 1000000.0, 500000000.0, 5000.0,
             "http://test", "2026-01-01")
        )
    conn.commit()
    return conn


def test_run_eod_analysis_creates_report(mem_db, monkeypatch):
    """run_eod_analysis 應建立 eod_analysis_reports 表並寫入一筆資料。"""
    def mock_call_agent_llm(prompt, model=None):
        return {
            "summary": "mock summary",
            "confidence": 0.8,
            "action_type": "suggest",
            "market_outlook": {"sentiment": "neutral", "sector_focus": [], "confidence": 0.8},
            "position_actions": [],
            "watchlist_opportunities": [],
            "risk_notes": [],
            "proposals": [],
        }

    monkeypatch.setattr("openclaw.agents.eod_analysis.call_agent_llm", mock_call_agent_llm)
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    result = run_eod_analysis(trade_date="2026-01-28", conn=mem_db)

    assert result.success is True
    rows = mem_db.execute("SELECT * FROM eod_analysis_reports WHERE trade_date='2026-01-28'").fetchall()
    assert len(rows) == 1
    report = dict(rows[0])
    assert json.loads(report["technical"])  # 應有技術指標
    assert json.loads(report["strategy"])   # 應有 Gemini 策略


def test_run_eod_analysis_no_eod_data(mem_db, monkeypatch):
    """無 EOD 資料時應回傳 success=False 不崩潰。"""
    monkeypatch.setattr("openclaw.agents.eod_analysis.call_agent_llm",
                        lambda p, model=None: {"summary": "x", "confidence": 0.0,
                                               "action_type": "observe", "proposals": []})
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    result = run_eod_analysis(trade_date="2099-01-01", conn=mem_db)
    assert result.success is False or result.summary  # 不應 crash
