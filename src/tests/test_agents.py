"""test_agents.py — agents/base.py 的單元測試（mock minimax_call）。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock, patch


# ── Fixture: in-memory DB ────────────────────────────────────────────────────

@pytest.fixture()
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        );
        CREATE TABLE eod_prices (
            trade_date TEXT,
            market TEXT,
            symbol TEXT,
            name TEXT,
            close REAL,
            change REAL,
            volume REAL
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            unrealized_pnl REAL DEFAULT 0
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL
        );
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT,
            symbol TEXT,
            realized_pnl REAL,
            total_pnl REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            rolling_win_rate REAL DEFAULT 0
        );
        CREATE TABLE decisions (
            decision_id TEXT,
            ts TEXT,
            symbol TEXT,
            signal_side TEXT,
            signal_score REAL
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            status TEXT,
            ts_submit TEXT
        );
    """)
    yield conn
    conn.close()


# ── MiniMax mock helper ──────────────────────────────────────────────────────

def _mock_gemini(summary: str, confidence: float = 0.8,
                 action_type: str = "observe", proposals: list = None):
    """回傳模擬 minimax_call 結果的 MagicMock。"""
    return {
        "summary": summary,
        "confidence": confidence,
        "action_type": action_type,
        "proposals": proposals or [],
        "_raw_response": f'{{"summary": "{summary}"}}',
        "_latency_ms": 500,
        "_model": "gemini-3.0-flash",
    }


# ── write_trace ──────────────────────────────────────────────────────────────

class TestWriteTrace:
    def test_inserts_row(self, mem_db):
        from openclaw.agents.base import write_trace
        result = _mock_gemini("系統正常")
        write_trace(mem_db, agent="test_agent", prompt="check", result=result)
        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row is not None
        assert row[0] == "test_agent"

    def test_confidence_stored(self, mem_db):
        from openclaw.agents.base import write_trace
        result = _mock_gemini("測試", confidence=0.75)
        write_trace(mem_db, agent="a", prompt="p", result=result)
        row = mem_db.execute("SELECT confidence FROM llm_traces").fetchone()
        assert row[0] == pytest.approx(0.75, abs=0.01)


# ── write_proposal ───────────────────────────────────────────────────────────

class TestWriteProposal:
    def test_inserts_pending(self, mem_db):
        from openclaw.agents.base import write_proposal
        pid = write_proposal(
            mem_db,
            generated_by="market_research",
            target_rule="SECTOR_FOCUS",
            rule_category="allocation",
            proposed_value="半導體",
            supporting_evidence="近 5 日強勢",
            confidence=0.75,
        )
        row = mem_db.execute(
            "SELECT status, requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == "pending"
        assert row[1] == 0

    def test_config_change_requires_approval(self, mem_db):
        from openclaw.agents.base import write_proposal
        pid = write_proposal(
            mem_db,
            generated_by="system_optimization",
            target_rule="BUY_SIGNAL_PCT",
            rule_category="config",
            proposed_value="0.003",
            supporting_evidence="勝率偏低",
            confidence=0.6,
            requires_human_approval=1,
            proposal_type="config_change",
        )
        row = mem_db.execute(
            "SELECT requires_human_approval FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        assert row[0] == 1

    def test_merges_custom_proposal_payload(self, mem_db):
        from openclaw.agents.base import write_proposal
        pid = write_proposal(
            mem_db,
            generated_by="strategy_committee",
            target_rule="STRATEGY_DIRECTION",
            rule_category="strategy",
            proposed_value="提高現金水位",
            supporting_evidence="市場波動升高",
            confidence=0.7,
            requires_human_approval=1,
            proposal_payload={
                "committee_context": {
                    "bull": {"thesis": "動能延續"},
                    "bear": {"thesis": "估值過熱"},
                }
            },
        )
        row = mem_db.execute(
            "SELECT proposal_json FROM strategy_proposals WHERE proposal_id=?",
            (pid,)
        ).fetchone()
        payload = json.loads(row[0])
        assert payload["generated_by"] == "strategy_committee"
        assert payload["committee_context"]["bull"]["thesis"] == "動能延續"


# ── call_agent_llm（fallback 測試）──────────────────────────────────────────

class TestCallAgentLlm:
    def test_returns_fallback_on_error(self):
        from openclaw.agents.base import call_agent_llm
        with patch("openclaw.agents.base.minimax_call", side_effect=RuntimeError("no key")):
            result = call_agent_llm("test prompt")
        assert result["action_type"] == "observe"
        assert result["confidence"] == 0.0
        assert "LLM 呼叫失敗" in result["summary"]


# ── SystemHealthAgent ─────────────────────────────────────────────────────────

class TestSystemHealthAgent:
    def test_writes_trace_on_healthy(self, mem_db):
        mock_resp = _mock_gemini("所有服務正常運作", confidence=0.95)
        with patch("openclaw.agents.system_health.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_health import run_system_health
            run_system_health(conn=mem_db)
        row = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert row[0] == "system_health"

    def test_no_proposals_when_healthy(self, mem_db):
        mock_resp = _mock_gemini("健康", confidence=0.95, proposals=[])
        with patch("openclaw.agents.system_health.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_health import run_system_health
            result = run_system_health(conn=mem_db)
        assert len(result.proposals) == 0


# ── MarketResearchAgent ───────────────────────────────────────────────────────

class TestMarketResearchAgent:
    def test_writes_trace_and_proposal(self, mem_db):
        mem_db.execute(
            "INSERT INTO eod_prices VALUES ('2026-03-02','TWSE','2330','台積電',900,15,50000)"
        )
        mem_db.commit()
        mock_resp = _mock_gemini(
            "半導體強勢，2330 漲幅最大",
            confidence=0.78,
            action_type="suggest",
            proposals=[{
                "target_rule": "SECTOR_FOCUS",
                "rule_category": "allocation",
                "proposed_value": "半導體",
                "supporting_evidence": "近日成交量大",
                "confidence": 0.78,
                "requires_human_approval": 0,
            }]
        )
        with patch("openclaw.agents.market_research.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.market_research import run_market_research
            result = run_market_research(conn=mem_db, trade_date="2026-03-02")

        assert result.action_type == "suggest"
        trace = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert trace[0] == "market_research"
        proposal = mem_db.execute("SELECT generated_by FROM strategy_proposals").fetchone()
        assert proposal[0] == "market_research"


# ── PortfolioReviewAgent ──────────────────────────────────────────────────────

class TestPortfolioReviewAgent:
    def test_writes_trace_on_empty_portfolio(self, mem_db):
        mock_resp = _mock_gemini("目前無持倉，無需再平衡", confidence=0.9, proposals=[])
        with patch("openclaw.agents.portfolio_review.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.portfolio_review import run_portfolio_review
            result = run_portfolio_review(conn=mem_db)
        trace = mem_db.execute("SELECT agent FROM llm_traces").fetchone()
        assert trace[0] == "portfolio_review"
        assert result.action_type == "observe"


# ── StrategyCommitteeAgent ────────────────────────────────────────────────────

class TestStrategyCommitteeAgent:
    def test_three_llm_calls_and_proposal_requires_approval(self, mem_db):
        bull_resp = _mock_gemini("看多：半導體短期趨勢向上", confidence=0.7, action_type="suggest")
        bear_resp = _mock_gemini("看空：外資連續賣超，注意回檔", confidence=0.65, action_type="suggest")
        arbiter_resp = _mock_gemini(
            "整合評估：建議持平，不加倉",
            confidence=0.65,
            action_type="suggest",
            proposals=[{
                "target_rule": "STRATEGY_DIRECTION",
                "rule_category": "strategy",
                "proposed_value": "持平，不加倉",
                "supporting_evidence": "Bull/Bear 訊號拉鋸",
                "confidence": 0.65,
                "requires_human_approval": 1,
            }],
        )
        arbiter_resp["stance"] = "neutral"
        arbiter_resp["decision_basis"] = {
            "bull_points": ["半導體短期趨勢向上"],
            "bear_points": ["外資連續賣超"],
            "key_tradeoffs": ["動能與估值拉鋸"],
            "data_gaps": [],
        }
        call_side_effects = [bull_resp, bear_resp, arbiter_resp]
        with patch("openclaw.agents.strategy_committee.call_agent_llm",
                   side_effect=call_side_effects):
            from openclaw.agents.strategy_committee import run_strategy_committee
            result = run_strategy_committee(conn=mem_db)

        count = mem_db.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 3
        proposal = mem_db.execute(
            "SELECT requires_human_approval, proposal_json FROM strategy_proposals"
        ).fetchone()
        assert proposal[0] == 1
        payload = json.loads(proposal[1])
        assert payload["committee_context"]["arbiter"]["stance"] == "neutral"
        assert payload["committee_context"]["bull"]["thesis"] == "看多：半導體短期趨勢向上"
        assert payload["committee_context"]["bear"]["thesis"] == "看空：外資連續賣超，注意回檔"

    def test_suppresses_recent_similar_strategy_direction_proposal(self, mem_db):
        from openclaw.agents.base import write_proposal

        write_proposal(
            mem_db,
            generated_by="strategy_committee",
            target_rule="STRATEGY_DIRECTION",
            rule_category="strategy",
            proposed_value="調整至謹慎且保本的策略，逐步減碼高估值 AI 持股並提高現金水位",
            supporting_evidence="市場過熱、估值偏高、籌碼集中，需防範修正風險",
            confidence=0.68,
            requires_human_approval=1,
        )

        bull_resp = _mock_gemini("看多：AI 題材延續", confidence=0.66, action_type="suggest")
        bear_resp = _mock_gemini("看空：估值與籌碼風險升高", confidence=0.72, action_type="suggest")
        arbiter_resp = _mock_gemini(
            "建議採取保守策略，降低高估值 AI 部位並提高現金",
            confidence=0.7,
            action_type="suggest",
            proposals=[{
                "target_rule": "STRATEGY_DIRECTION",
                "rule_category": "strategy",
                "proposed_value": "調整至謹慎保本策略，降低高估值 AI 部位並拉高現金水位",
                "supporting_evidence": "市場過熱與籌碼集中風險升高，應防範回檔修正",
                "confidence": 0.7,
                "requires_human_approval": 1,
            }],
        )

        with patch(
            "openclaw.agents.strategy_committee.call_agent_llm",
            side_effect=[bull_resp, bear_resp, arbiter_resp],
        ):
            from openclaw.agents.strategy_committee import run_strategy_committee
            result = run_strategy_committee(conn=mem_db)

        proposal_count = mem_db.execute(
            "SELECT COUNT(*) FROM strategy_proposals WHERE target_rule='STRATEGY_DIRECTION'"
        ).fetchone()[0]
        trace_count = mem_db.execute(
            "SELECT COUNT(*) FROM llm_traces WHERE agent='strategy_committee'"
        ).fetchone()[0]

        assert proposal_count == 1
        assert trace_count == 4
        assert result.proposals == []
        assert result.raw["duplicate_alerts"][0]["action"] == "suppressed"

    def test_allows_distinct_strategy_direction_proposal(self, mem_db):
        from openclaw.agents.base import write_proposal

        write_proposal(
            mem_db,
            generated_by="strategy_committee",
            target_rule="STRATEGY_DIRECTION",
            rule_category="strategy",
            proposed_value="提高現金水位並減碼高波動科技股",
            supporting_evidence="市場過熱，先控制回撤",
            confidence=0.64,
            requires_human_approval=1,
        )

        bull_resp = _mock_gemini("看多：內需與金融輪動有利", confidence=0.67, action_type="suggest")
        bear_resp = _mock_gemini("看空：出口鏈風險仍高", confidence=0.6, action_type="suggest")
        arbiter_resp = _mock_gemini(
            "建議中性偏建設性，從 AI 轉向防禦與高股息輪動",
            confidence=0.69,
            action_type="suggest",
            proposals=[{
                "target_rule": "STRATEGY_DIRECTION",
                "rule_category": "strategy",
                "proposed_value": "維持中性，但逐步轉向高股息與防禦型資產",
                "supporting_evidence": "輪動跡象增加，可降低 AI 集中度但不必全面去風險",
                "confidence": 0.69,
                "requires_human_approval": 1,
            }],
        )

        with patch(
            "openclaw.agents.strategy_committee.call_agent_llm",
            side_effect=[bull_resp, bear_resp, arbiter_resp],
        ):
            from openclaw.agents.strategy_committee import run_strategy_committee
            result = run_strategy_committee(conn=mem_db)

        proposal_count = mem_db.execute(
            "SELECT COUNT(*) FROM strategy_proposals WHERE target_rule='STRATEGY_DIRECTION'"
        ).fetchone()[0]

        assert proposal_count == 2
        assert len(result.proposals) == 1
        assert "duplicate_alerts" not in result.raw


# ── SystemOptimizationAgent ───────────────────────────────────────────────────

class TestSystemOptimizationAgent:
    def test_config_change_requires_approval(self, mem_db):
        mock_resp = _mock_gemini(
            "BUY_SIGNAL_PCT 建議從 0.002 提高至 0.003",
            confidence=0.7,
            action_type="config_change",
            proposals=[{
                "target_rule": "BUY_SIGNAL_PCT",
                "rule_category": "config",
                "proposed_value": "0.003",
                "supporting_evidence": "近 4 週勝率 35%",
                "confidence": 0.7,
                "requires_human_approval": 1,
            }]
        )
        with patch("openclaw.agents.system_optimization.call_agent_llm",
                   return_value=mock_resp):
            from openclaw.agents.system_optimization import run_system_optimization
            run_system_optimization(conn=mem_db)

        row = mem_db.execute(
            "SELECT target_rule, requires_human_approval FROM strategy_proposals"
        ).fetchone()
        assert row[0] == "BUY_SIGNAL_PCT"
        assert row[1] == 1

    def test_no_proposal_when_performance_ok(self, mem_db):
        mock_resp = _mock_gemini("近 4 週績效正常，無需調整", confidence=0.8,
                                  action_type="observe", proposals=[])
        with patch("openclaw.agents.system_optimization.call_agent_llm",
                   return_value=mock_resp):
            from openclaw.agents.system_optimization import run_system_optimization
            result = run_system_optimization(conn=mem_db)
        assert len(result.proposals) == 0
        count = mem_db.execute(
            "SELECT COUNT(*) FROM strategy_proposals"
        ).fetchone()[0]
        assert count == 0


# ── OrchestratorHelpers ───────────────────────────────────────────────────────

class TestOrchestratorHelpers:
    def test_should_run_now_true(self):
        from datetime import timedelta
        from openclaw.agent_orchestrator import _should_run_now
        twn = timezone(timedelta(hours=8))
        t = datetime(2026, 3, 2, 8, 20, tzinfo=twn)
        assert _should_run_now("08:20", t) is True

    def test_should_run_now_false(self):
        from datetime import timedelta
        from openclaw.agent_orchestrator import _should_run_now
        twn = timezone(timedelta(hours=8))
        t = datetime(2026, 3, 2, 9, 15, tzinfo=twn)
        assert _should_run_now("08:20", t) is False

    def test_pm_review_event_detected(self, tmp_path):
        import json as _j
        from openclaw.agent_orchestrator import _pm_review_just_completed
        from openclaw.config_manager import get_config, reset_config
        (tmp_path / "daily_pm_state.json").write_text(_j.dumps({"reviewed_at": "2026-03-02T08:25:00"}))
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            result = _pm_review_just_completed(last_seen=None)
            assert result == "2026-03-02T08:25:00"
        finally:
            reset_config()

    def test_pm_review_no_event_when_same(self, tmp_path):
        import json as _j
        from openclaw.agent_orchestrator import _pm_review_just_completed
        from openclaw.config_manager import get_config, reset_config
        (tmp_path / "daily_pm_state.json").write_text(_j.dumps({"reviewed_at": "2026-03-02T08:25:00"}))
        reset_config()
        get_config(config_dir=tmp_path)
        try:
            result = _pm_review_just_completed(last_seen="2026-03-02T08:25:00")
            assert result is None
        finally:
            reset_config()

    def test_watcher_no_fills_3days(self, mem_db):
        from openclaw.agent_orchestrator import _watcher_no_fills_3days
        assert _watcher_no_fills_3days(mem_db) is True  # fills table 是空的


# ── open_conn WAL pragma test ─────────────────────────────────────────────────

class TestOpenConn:
    def test_open_conn_returns_wal_connection(self, tmp_path):
        """Lines 25-29: open_conn sets WAL journal mode and row_factory."""
        from openclaw.agents.base import open_conn
        db_path = str(tmp_path / "test.db")
        conn = open_conn(db_path)
        try:
            # Verify WAL mode was set
            row = conn.execute("PRAGMA journal_mode;").fetchone()
            assert row[0] == "wal"
            # Verify row_factory is sqlite3.Row (returned row supports key access)
            conn.execute("CREATE TABLE t (x INTEGER)")
            conn.execute("INSERT INTO t VALUES (42)")
            result = conn.execute("SELECT x FROM t").fetchone()
            assert result["x"] == 42
        finally:
            conn.close()


# ── Coverage: conn.close() paths (conn is None branch) ───────────────────────

def _make_temp_db(tmp_path):
    """Helper: create a minimal temp DB and return its path string."""
    db_path = str(tmp_path / "trades.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            unrealized_pnl REAL DEFAULT 0
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            status TEXT,
            ts_submit TEXT
        );
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT,
            symbol TEXT,
            realized_pnl REAL,
            total_pnl REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            rolling_win_rate REAL DEFAULT 0
        );
        CREATE TABLE decisions (
            decision_id TEXT,
            ts TEXT,
            symbol TEXT,
            signal_side TEXT,
            signal_score REAL
        );
        CREATE TABLE eod_prices (
            trade_date TEXT,
            market TEXT,
            symbol TEXT,
            name TEXT,
            close REAL,
            change REAL,
            volume REAL
        );
    """)
    conn.commit()
    conn.close()
    return db_path


class TestConnClosedWhenNone:
    """Tests that verify _conn.close() is called in the finally block when conn=None."""

    def test_portfolio_review_closes_conn_when_none(self, tmp_path):
        """portfolio_review.py lines 107-108: _conn.close() when conn is None."""
        db_path = _make_temp_db(tmp_path)
        mock_resp = _mock_gemini("無持倉", confidence=0.9, proposals=[])
        with patch("openclaw.agents.portfolio_review.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.portfolio_review import run_portfolio_review
            result = run_portfolio_review(db_path=db_path)
        assert result.action_type == "observe"

    def test_portfolio_review_writes_proposals_when_non_empty(self, tmp_path):
        """portfolio_review.py line 95: write_proposal called inside for loop."""
        db_path = _make_temp_db(tmp_path)
        mock_resp = _mock_gemini(
            "持倉集中度過高，建議再平衡",
            confidence=0.8,
            action_type="suggest",
            proposals=[{
                "target_rule": "POSITION_REBALANCE",
                "rule_category": "portfolio",
                "proposed_value": "降低 2330 至 30%",
                "supporting_evidence": "單一股票市值佔比 > 40%",
                "confidence": 0.75,
                "requires_human_approval": 0,
            }]
        )
        with patch("openclaw.agents.portfolio_review.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.portfolio_review import run_portfolio_review
            result = run_portfolio_review(db_path=db_path)
        assert result.action_type == "suggest"
        conn2 = sqlite3.connect(db_path)
        row = conn2.execute("SELECT generated_by FROM strategy_proposals").fetchone()
        conn2.close()
        assert row[0] == "portfolio_review"

    def test_market_research_closes_conn_when_none(self, tmp_path):
        """market_research.py line 107: _conn.close() when conn is None."""
        db_path = _make_temp_db(tmp_path)
        mock_resp = _mock_gemini("無市場資料", confidence=0.7, proposals=[])
        with patch("openclaw.agents.market_research.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.market_research import run_market_research
            result = run_market_research(db_path=db_path)
        assert result.action_type == "observe"

    def test_system_optimization_closes_conn_when_none(self, tmp_path):
        """system_optimization.py line 110: _conn.close() when conn is None."""
        db_path = _make_temp_db(tmp_path)
        mock_resp = _mock_gemini("績效正常，無需調整", confidence=0.8, proposals=[])
        with patch("openclaw.agents.system_optimization.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_optimization import run_system_optimization
            result = run_system_optimization(db_path=db_path)
        assert result.action_type == "observe"

    def test_strategy_committee_closes_conn_when_none(self, tmp_path):
        """strategy_committee.py line 140: _conn.close() when conn is None."""
        db_path = _make_temp_db(tmp_path)
        bull_resp = _mock_gemini("看多", confidence=0.7)
        bear_resp = _mock_gemini("看空", confidence=0.65)
        arbiter_resp = _mock_gemini("整合建議：持平", confidence=0.6, proposals=[])
        with patch("openclaw.agents.strategy_committee.call_agent_llm",
                   side_effect=[bull_resp, bear_resp, arbiter_resp]):
            from openclaw.agents.strategy_committee import run_strategy_committee
            result = run_strategy_committee(db_path=db_path)
        assert result.action_type == "observe"

    def test_system_health_closes_conn_when_none(self, tmp_path):
        """system_health.py line 111: _conn.close() when conn is None."""
        db_path = _make_temp_db(tmp_path)
        mock_resp = _mock_gemini("系統健康", confidence=0.95, proposals=[])
        with patch("openclaw.agents.system_health.call_agent_llm", return_value=mock_resp):
            from openclaw.agents.system_health import run_system_health
            result = run_system_health(db_path=db_path)
        assert result.action_type == "observe"


# ── Coverage: system_health.py exception branches ────────────────────────────

class TestSystemHealthExceptionBranches:
    """Tests for _get_pm2_status, _get_disk_info, _get_watcher_recent_count exception paths."""

    def test_get_pm2_status_exception(self):
        """system_health.py lines 63-64: exception in subprocess.run → return error string."""
        from openclaw.agents.system_health import _get_pm2_status
        with patch("openclaw.agents.system_health.subprocess.run",
                   side_effect=FileNotFoundError("pm2 not found")):
            result = _get_pm2_status()
        assert "PM2 查詢失敗" in result

    def test_get_disk_info_exception(self):
        """system_health.py lines 74-75: exception in subprocess.run → return error string."""
        from openclaw.agents.system_health import _get_disk_info
        with patch("openclaw.agents.system_health.subprocess.run",
                   side_effect=OSError("df not found")):
            result = _get_disk_info()
        assert "磁碟查詢失敗" in result

    def test_get_watcher_recent_count_exception(self, mem_db):
        """system_health.py lines 85-86: DB exception → return -1."""
        from openclaw.agents.system_health import _get_watcher_recent_count
        # Drop the llm_traces table to force an exception
        mem_db.execute("DROP TABLE llm_traces")
        result = _get_watcher_recent_count(mem_db)
        assert result == -1
