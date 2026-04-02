"""test_debate_loop.py — Multi-Agent Debate Loop 單元測試。

Mock LLM 呼叫，驗證 debate loop 的資料流、risk check、DB 寫入。
"""
from __future__ import annotations

import json
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from openclaw.agents.bull_agent import BullAgent, BullThesis
from openclaw.agents.bear_agent import BearAgent, BearThesis
from openclaw.agents.arbiter_agent import ArbiterAgent, ArbiterDecision
from openclaw.debate_loop import (
    DebateRecord,
    RiskCheckResult,
    _ensure_debate_records_table,
    record_shadow_decision,
    run_debate_loop,
    validate_risk,
)
from openclaw.debate_formatter import format_debate_report, format_single_debate


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def mem_db():
    """In-memory SQLite with required tables for debate loop."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            agent TEXT, model TEXT, prompt TEXT, response TEXT,
            latency_ms INTEGER, prompt_tokens INTEGER,
            completion_tokens INTEGER, tool_calls_json TEXT,
            confidence REAL, created_at INTEGER NOT NULL
        );
        CREATE TABLE positions (
            symbol TEXT, quantity REAL, avg_price REAL,
            unrealized_pnl REAL
        );
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER, change REAL
        );
        CREATE TABLE eod_institution_flows (
            trade_date TEXT, symbol TEXT, foreign_buy REAL,
            foreign_sell REAL, net_buy REAL
        );
    """)
    _ensure_debate_records_table(conn)
    yield conn
    conn.close()


def _make_bull(symbol: str = "2330", confidence: float = 0.7) -> BullThesis:
    return BullThesis(
        symbol=symbol,
        thesis="技術面看多，MA 黃金交叉",
        confidence=confidence,
        entry_price=580.0,
        target_price=620.0,
        catalysts=["AI 需求", "法人買超"],
    )


def _make_bear(symbol: str = "2330", confidence: float = 0.5) -> BearThesis:
    return BearThesis(
        symbol=symbol,
        thesis="RSI 超買，短線有回調風險",
        confidence=confidence,
        risks=["RSI > 70", "漲幅過大"],
        stop_loss=560.0,
    )


def _make_decision(
    symbol: str = "2330", rec: str = "BUY", confidence: float = 0.65,
) -> ArbiterDecision:
    return ArbiterDecision(
        symbol=symbol,
        recommendation=rec,
        confidence=confidence,
        rationale="Bull 論點較有力，建議試單",
        bull_score=70,
        bear_score=45,
    )


# ── BullAgent tests ─────────────────────────────────────────────────────────


class TestBullAgent:
    @patch("openclaw.agents.bull_agent.call_agent_llm")
    def test_argue_success(self, mock_llm):
        mock_llm.return_value = {
            "thesis": "TSMC 技術面看多",
            "confidence": 0.75,
            "entry_price": 580,
            "target_price": 620,
            "catalysts": ["AI"],
        }
        agent = BullAgent()
        result = agent.argue("2330", {"symbol": "2330"})
        assert isinstance(result, BullThesis)
        assert result.symbol == "2330"
        assert result.confidence == 0.75
        assert result.entry_price == 580.0

    @patch("openclaw.agents.bull_agent.call_agent_llm")
    def test_argue_llm_error_fallback(self, mock_llm):
        mock_llm.return_value = {
            "_error": "timeout",
            "confidence": 0.0,
            "action_type": "observe",
        }
        agent = BullAgent()
        result = agent.argue("2330", {})
        assert result.confidence == 0.0
        assert "失敗" in result.thesis


# ── BearAgent tests ─────────────────────────────────────────────────────────


class TestBearAgent:
    @patch("openclaw.agents.bear_agent.call_agent_llm")
    def test_argue_success(self, mock_llm):
        mock_llm.return_value = {
            "thesis": "RSI 超買，回調風險高",
            "confidence": 0.6,
            "risks": ["RSI > 70"],
            "stop_loss": 555,
        }
        agent = BearAgent()
        result = agent.argue("2330", {"symbol": "2330"})
        assert isinstance(result, BearThesis)
        assert result.stop_loss == 555.0
        assert len(result.risks) == 1


# ── ArbiterAgent tests ──────────────────────────────────────────────────────


class TestArbiterAgent:
    @patch("openclaw.agents.arbiter_agent.call_agent_llm")
    def test_decide_buy(self, mock_llm):
        mock_llm.return_value = {
            "recommendation": "BUY",
            "confidence": 0.7,
            "rationale": "Bull case stronger",
            "bull_score": 75,
            "bear_score": 40,
        }
        arbiter = ArbiterAgent()
        bull = _make_bull()
        bear = _make_bear()
        result = arbiter.decide(bull, bear, {"rsi_14": 55})
        assert result.recommendation == "BUY"
        assert result.confidence == 0.7

    @patch("openclaw.agents.arbiter_agent.call_agent_llm")
    def test_decide_invalid_recommendation_defaults_hold(self, mock_llm):
        mock_llm.return_value = {
            "recommendation": "YOLO",
            "confidence": 0.5,
            "rationale": "invalid",
        }
        arbiter = ArbiterAgent()
        result = arbiter.decide(_make_bull(), _make_bear(), {})
        assert result.recommendation == "HOLD"


# ── Risk validation tests ───────────────────────────────────────────────────


class TestRiskValidation:
    def test_low_confidence_buy_rejected(self, mem_db):
        decision = _make_decision(confidence=0.2, rec="BUY")
        result = validate_risk(decision, mem_db)
        assert not result.passed
        assert "confidence" in result.reason.lower()

    def test_hold_low_confidence_passes(self, mem_db):
        decision = _make_decision(confidence=0.1, rec="HOLD")
        result = validate_risk(decision, mem_db)
        assert result.passed

    def test_concentration_risk(self, mem_db):
        # Insert positions: symbol has 50% of portfolio
        mem_db.execute(
            "INSERT INTO positions VALUES (?, ?, ?, ?)",
            ("2330", 100, 500.0, 0),
        )
        mem_db.execute(
            "INSERT INTO positions VALUES (?, ?, ?, ?)",
            ("2317", 50, 200.0, 0),
        )
        decision = _make_decision(symbol="2330", rec="BUY", confidence=0.8)
        result = validate_risk(decision, mem_db)
        assert not result.passed
        assert "concentration" in result.reason.lower()

    def test_normal_buy_passes(self, mem_db):
        decision = _make_decision(confidence=0.65, rec="BUY")
        result = validate_risk(decision, mem_db)
        assert result.passed


# ── DB record tests ──────────────────────────────────────────────────────────


class TestDebateRecordDB:
    def test_record_shadow_decision(self, mem_db):
        record = DebateRecord(
            debate_id="test-001",
            debate_date="2026-04-01",
            symbol="2330",
            bull_thesis=_make_bull(),
            bear_thesis=_make_bear(),
            arbiter_decision=_make_decision(),
            risk_check=RiskCheckResult(passed=True),
            recommendation="BUY",
            confidence=0.65,
        )
        record_shadow_decision(record, mem_db)

        row = mem_db.execute(
            "SELECT * FROM debate_records WHERE id = ?", ("test-001",)
        ).fetchone()
        assert row is not None
        assert row["symbol"] == "2330"
        assert row["recommendation"] == "BUY"

        bull_data = json.loads(row["bull_thesis_json"])
        assert bull_data["symbol"] == "2330"


# ── Full loop integration test ───────────────────────────────────────────────


class TestDebateLoopIntegration:
    @patch("openclaw.debate_loop._check_emergency_stop", return_value=False)
    @patch("openclaw.agents.arbiter_agent.call_agent_llm")
    @patch("openclaw.agents.bear_agent.call_agent_llm")
    @patch("openclaw.agents.bull_agent.call_agent_llm")
    def test_full_loop(self, mock_bull, mock_bear, mock_arbiter, mock_estop, mem_db):
        mock_bull.return_value = {
            "thesis": "bullish", "confidence": 0.7,
            "entry_price": 580, "target_price": 620, "catalysts": [],
        }
        mock_bear.return_value = {
            "thesis": "bearish", "confidence": 0.5,
            "risks": ["risk1"], "stop_loss": 550,
        }
        mock_arbiter.return_value = {
            "recommendation": "BUY", "confidence": 0.65,
            "rationale": "bull wins", "bull_score": 70, "bear_score": 40,
        }

        debates = run_debate_loop(
            conn=mem_db,
            watchlist=["2330"],
            debate_date="2026-04-01",
        )

        assert len(debates) == 1
        assert debates[0].symbol == "2330"
        assert debates[0].recommendation == "BUY"

        # Verify DB record
        row = mem_db.execute("SELECT COUNT(*) FROM debate_records").fetchone()
        assert row[0] == 1

    @patch("openclaw.debate_loop._check_emergency_stop", return_value=True)
    def test_emergency_stop_aborts(self, mock_estop, mem_db):
        debates = run_debate_loop(conn=mem_db, watchlist=["2330"])
        assert len(debates) == 0

    @patch("openclaw.debate_loop._check_emergency_stop", return_value=False)
    @patch("openclaw.agents.arbiter_agent.call_agent_llm")
    @patch("openclaw.agents.bear_agent.call_agent_llm")
    @patch("openclaw.agents.bull_agent.call_agent_llm")
    def test_risk_veto_skips_record(self, mock_bull, mock_bear, mock_arbiter, mock_estop, mem_db):
        mock_bull.return_value = {
            "thesis": "bullish", "confidence": 0.7,
            "entry_price": 580, "target_price": 620, "catalysts": [],
        }
        mock_bear.return_value = {
            "thesis": "bearish", "confidence": 0.5,
            "risks": [], "stop_loss": 550,
        }
        # Arbiter returns BUY with very low confidence -> risk veto
        mock_arbiter.return_value = {
            "recommendation": "BUY", "confidence": 0.1,
            "rationale": "unsure", "bull_score": 40, "bear_score": 40,
        }

        debates = run_debate_loop(
            conn=mem_db, watchlist=["2330"], debate_date="2026-04-01",
        )

        assert len(debates) == 1
        assert debates[0].recommendation == "VETOED"
        # Vetoed records should NOT be in DB
        row = mem_db.execute("SELECT COUNT(*) FROM debate_records").fetchone()
        assert row[0] == 0


# ── Formatter tests ──────────────────────────────────────────────────────────


class TestDebateFormatter:
    def test_format_single_debate(self):
        record = DebateRecord(
            debate_id="fmt-001",
            debate_date="2026-04-01",
            symbol="2330",
            bull_thesis=_make_bull(),
            bear_thesis=_make_bear(),
            arbiter_decision=_make_decision(),
            risk_check=RiskCheckResult(passed=True),
            recommendation="BUY",
            confidence=0.65,
            elapsed_ms=1234,
        )
        text = format_single_debate(record)
        assert "2330" in text
        assert "BUY" in text
        assert "Bull" in text
        assert "Bear" in text

    def test_format_empty_report(self):
        text = format_debate_report([])
        assert "No debates" in text

    def test_format_full_report(self):
        records = [
            DebateRecord(
                debate_id=f"fmt-{i}",
                debate_date="2026-04-01",
                symbol=sym,
                bull_thesis=_make_bull(sym),
                bear_thesis=_make_bear(sym),
                arbiter_decision=_make_decision(sym),
                risk_check=RiskCheckResult(passed=True),
                recommendation="BUY",
                confidence=0.65,
            )
            for i, sym in enumerate(["2330", "2317"])
        ]
        text = format_debate_report(records)
        assert "Hedge Fund Debate Report" in text
        assert "2330" in text
        assert "2317" in text
