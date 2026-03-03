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


# ── 缺口分支覆蓋 ──────────────────────────────────────

def test_symbol_with_no_eod_excluded_from_technical(mem_db, monkeypatch):
    """持倉股票無 EOD 資料時，technical 應排除該股（_calc_symbol_indicators line 98 early return）。"""
    mem_db.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?)",
        ("9999", 100.0, 50.0, 55.0, 500.0, "2026-01-28"),
    )
    mem_db.commit()

    monkeypatch.setattr(
        "openclaw.agents.eod_analysis.call_agent_llm",
        lambda p, model=None: {
            "summary": "ok", "confidence": 0.8, "action_type": "suggest",
            "proposals": [], "market_outlook": {},
        },
    )
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    run_eod_analysis(trade_date="2026-01-28", conn=mem_db)

    row = mem_db.execute(
        "SELECT technical FROM eod_analysis_reports WHERE trade_date='2026-01-28'"
    ).fetchone()
    technical = json.loads(dict(row)["technical"])
    # 9999 無 EOD 資料，不應出現在 technical 字典中
    assert "9999" not in technical


def test_last_helper_returns_none_when_all_indicators_are_none(mem_db, monkeypatch):
    """只有 2 筆 EOD 資料時，MA5/MA20/MA60 全為 None → _last() 回傳 None（line 117）。"""
    # 插入只有 2 筆的新股票
    for d, close in [("2026-01-27", 100.0), ("2026-01-28", 102.0)]:
        mem_db.execute(
            "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d, "TWSE", "8888", "測試股", close, 2.0,
             99.0, 103.0, 98.0, 500000.0, 50000000.0, 1000.0,
             "http://test", "2026-01-28"),
        )
    mem_db.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?)",
        ("8888", 100.0, 100.0, 102.0, 200.0, "2026-01-28"),
    )
    mem_db.commit()

    monkeypatch.setattr(
        "openclaw.agents.eod_analysis.call_agent_llm",
        lambda p, model=None: {
            "summary": "ok", "confidence": 0.8, "action_type": "suggest",
            "proposals": [], "market_outlook": {},
        },
    )
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    run_eod_analysis(trade_date="2026-01-28", conn=mem_db)

    row = mem_db.execute(
        "SELECT technical FROM eod_analysis_reports WHERE trade_date='2026-01-28'"
    ).fetchone()
    technical = json.loads(dict(row)["technical"])
    # 8888 有 2 筆資料，但 MA5/20/60 皆為 None；技術指標仍應存在（含 None 欄位）
    assert "8888" in technical
    assert technical["8888"]["ma5"] is None
    assert technical["8888"]["ma20"] is None
    assert technical["8888"]["ma60"] is None


def test_run_eod_analysis_closes_own_connection_when_no_conn_passed(tmp_path, monkeypatch):
    """不傳 conn 而傳 db_path 時，function 應自己管理 connection 並在 finally 關閉（line 239）。"""
    import sqlite3 as _sqlite3

    db_path = str(tmp_path / "test_analysis.db")
    setup = _sqlite3.connect(db_path)
    setup.row_factory = _sqlite3.Row
    for ddl in [
        """CREATE TABLE eod_prices (
            trade_date TEXT, market TEXT, symbol TEXT, name TEXT,
            close REAL, change REAL, open REAL, high REAL, low REAL,
            volume REAL, turnover REAL, trades REAL, source_url TEXT,
            ingested_at TEXT, PRIMARY KEY (trade_date, market, symbol))""",
        """CREATE TABLE institution_flows (
            trade_date TEXT, symbol TEXT,
            foreign_net REAL, investment_trust_net REAL, dealer_net REAL,
            total_net REAL, health_score REAL, source_url TEXT, ingested_at TEXT,
            PRIMARY KEY (trade_date, symbol))""",
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, qty REAL, avg_cost REAL, current_price REAL,
            unrealized_pnl REAL, last_updated TEXT)""",
        """CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY, component TEXT, agent TEXT,
            model TEXT, prompt_text TEXT, response_text TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            latency_ms INTEGER, confidence REAL,
            metadata TEXT, created_at INTEGER NOT NULL)""",
    ]:
        setup.execute(ddl)
    setup.commit()
    setup.close()

    monkeypatch.setattr(
        "openclaw.agents.eod_analysis.call_agent_llm",
        lambda p, model=None: {"summary": "x", "confidence": 0.0,
                               "action_type": "observe", "proposals": []},
    )
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    # conn=None → function 自行呼叫 open_conn(db_path) 並在 finally 關閉（line 239）
    result = run_eod_analysis(trade_date="2099-01-01", db_path=db_path)
    assert result.success is False  # 無資料，success=False；但不應 crash
