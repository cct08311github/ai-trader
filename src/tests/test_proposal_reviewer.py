import json
import sqlite3

from openclaw.proposal_reviewer import auto_review_pending_proposals


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT NULL,
            proposed_value TEXT NULL,
            supporting_evidence TEXT NULL,
            confidence REAL NULL,
            requires_human_approval INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            expires_at INTEGER NULL,
            proposal_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            decided_at INTEGER NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            avg_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            state TEXT,
            high_water_mark REAL,
            entry_trading_day TEXT
        )"""
    )
    return conn


def test_auto_review_skips_non_rebalance_proposal(monkeypatch):
    conn = _make_conn()
    conn.execute(
        """INSERT INTO strategy_proposals (
            proposal_id, generated_by, target_rule, rule_category, proposed_value,
            supporting_evidence, confidence, requires_human_approval, status,
            proposal_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "p-strategy",
            "strategy_committee",
            "STRATEGY_DIRECTION",
            "strategy",
            "DEFENSIVE",
            "generic strategy note",
            0.8,
            1,
            "pending",
            json.dumps({"type": "suggest", "proposed_value": "DEFENSIVE"}),
            9999999999999,
        ),
    )
    conn.commit()

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called for STRATEGY_DIRECTION")

    sent_messages = []
    monkeypatch.setattr("openclaw.proposal_reviewer._gemini_review", _boom)
    monkeypatch.setattr("openclaw.tg_notify.send_message", sent_messages.append)

    reviewed = auto_review_pending_proposals(conn)

    assert reviewed == 0
    row = conn.execute(
        "SELECT status, decided_at FROM strategy_proposals WHERE proposal_id='p-strategy'"
    ).fetchone()
    assert row["status"] == "pending"
    assert row["decided_at"] is None
    assert sent_messages == []


def test_auto_review_skips_rebalance_without_live_position(monkeypatch):
    conn = _make_conn()
    conn.execute(
        """INSERT INTO strategy_proposals (
            proposal_id, generated_by, target_rule, rule_category, proposed_value,
            supporting_evidence, confidence, requires_human_approval, status,
            proposal_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "p-invalid",
            "concentration_guard",
            "POSITION_REBALANCE",
            "portfolio",
            "reduce 2317",
            "stale concentration suggestion",
            0.9,
            0,
            "pending",
            json.dumps({"symbol": "2317", "reduce_pct": 0.387}),
            9999999999999,
        ),
    )
    conn.commit()

    def _boom(*args, **kwargs):
        raise AssertionError("LLM should not be called without live position")

    sent_messages = []
    monkeypatch.setattr("openclaw.proposal_reviewer._gemini_review", _boom)
    monkeypatch.setattr("openclaw.tg_notify.send_message", sent_messages.append)

    reviewed = auto_review_pending_proposals(conn)

    assert reviewed == 0
    row = conn.execute(
        "SELECT status, decided_at FROM strategy_proposals WHERE proposal_id='p-invalid'"
    ).fetchone()
    assert row["status"] == "skipped"
    assert row["decided_at"] is not None
    assert sent_messages == []


def test_auto_review_uses_live_weight_for_rebalance(monkeypatch):
    conn = _make_conn()
    conn.execute(
        "INSERT INTO positions VALUES ('2317', 100, 0, 200, 0, 'HOLDING', NULL, '2026-03-19')"
    )
    conn.execute(
        "INSERT INTO positions VALUES ('2382', 100, 0, 800, 0, 'HOLDING', NULL, '2026-03-19')"
    )
    conn.execute(
        """INSERT INTO strategy_proposals (
            proposal_id, generated_by, target_rule, rule_category, proposed_value,
            supporting_evidence, confidence, requires_human_approval, status,
            proposal_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "p-valid",
            "concentration_guard",
            "POSITION_REBALANCE",
            "portfolio",
            "reduce 2317",
            "2317 overweight",
            0.9,
            0,
            "pending",
            json.dumps({"symbol": "2317", "reduce_pct": 0.387}),
            9999999999999,
        ),
    )
    conn.commit()

    calls = []
    sent_messages = []

    def _fake_review(symbol, weight, reduce_pct, evidence, position_summary):
        calls.append(
            {
                "symbol": symbol,
                "weight": weight,
                "reduce_pct": reduce_pct,
                "evidence": evidence,
                "position_summary": position_summary,
            }
        )
        return {
            "decision": "approve",
            "confidence": 0.85,
            "reason": "集中度過高，建議減持以降低風險",
        }

    monkeypatch.setattr("openclaw.proposal_reviewer._gemini_review", _fake_review)
    monkeypatch.setattr("openclaw.tg_notify.send_message", sent_messages.append)
    monkeypatch.setattr("openclaw.tg_approver._fmt_symbol", lambda conn, symbol: f"{symbol} 測試股")

    reviewed = auto_review_pending_proposals(conn)

    assert reviewed == 1
    assert len(calls) == 1
    assert calls[0]["symbol"] == "2317"
    assert round(calls[0]["weight"], 1) == 0.2
    assert calls[0]["reduce_pct"] == 0.387
    row = conn.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p-valid'"
    ).fetchone()
    assert row["status"] == "approved"
    assert len(sent_messages) == 1
    assert "目前比重：20.0%" in sent_messages[0]
