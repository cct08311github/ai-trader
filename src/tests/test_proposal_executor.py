"""test_proposal_executor.py — approved 提案執行測試（intent-based API）"""
import json
import sqlite3
import time
import pytest


@pytest.fixture
def db_with_proposal(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER
    )""")
    conn.execute("""CREATE TABLE orders (
        order_id TEXT PRIMARY KEY, decision_id TEXT, broker_order_id TEXT,
        ts_submit TEXT, symbol TEXT, side TEXT, qty INTEGER, price REAL,
        order_type TEXT, tif TEXT, status TEXT, strategy_version TEXT
    )""")
    conn.execute("""CREATE TABLE fills (
        fill_id TEXT PRIMARY KEY, order_id TEXT, ts_fill TEXT,
        qty INTEGER, price REAL, fee REAL, tax REAL
    )""")
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL
    )""")
    # 插入一個 POSITION_REBALANCE approved proposal
    conn.execute("""INSERT INTO strategy_proposals VALUES (
        'p1','portfolio_review','POSITION_REBALANCE','portfolio',
        NULL,'減少 3008 持倉 30%','evidence',0.8,0,
        'approved',NULL,?,?,NULL
    )""", (json.dumps({"symbol": "3008", "reduce_pct": 0.3, "type": "rebalance"}),
           int(time.time())))
    conn.execute("INSERT INTO positions VALUES ('3008',1000,379.6,2450.0,0,2450.0)")
    conn.commit()
    return conn


def test_executor_returns_sell_intent_for_approved_proposal(db_with_proposal):
    """approved POSITION_REBALANCE proposal 應回傳 SellIntent"""
    from openclaw.proposal_executor import execute_pending_proposals
    intents, n_noted = execute_pending_proposals(db_with_proposal)
    assert len(intents) == 1
    assert intents[0].symbol == "3008"
    assert intents[0].qty == 300  # 1000 * 30%
    assert intents[0].price == 2450.0
    assert intents[0].proposal_id == "p1"
    assert intents[0].execution_key
    # proposal 進入 queued，等待 broker 執行
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "queued"
    journal = db_with_proposal.execute(
        "SELECT state, attempt_count FROM proposal_execution_journal WHERE proposal_id='p1'"
    ).fetchone()
    assert journal[0] == "prepared"
    assert journal[1] == 0


def test_mark_intent_executed(db_with_proposal):
    """broker 成交後 mark_intent_executed 應更新為 executed"""
    from openclaw.proposal_executor import execute_pending_proposals, mark_intent_executed
    intents, _ = execute_pending_proposals(db_with_proposal)
    mark_intent_executed(
        db_with_proposal,
        intents[0].proposal_id,
        execution_key=intents[0].execution_key,
        order_id="o1",
    )
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "executed"
    journal = db_with_proposal.execute(
        "SELECT state, last_order_id FROM proposal_execution_journal WHERE proposal_id='p1'"
    ).fetchone()
    assert journal[0] == "completed"
    assert journal[1] == "o1"


def test_executor_does_not_create_orders(db_with_proposal):
    """execute_pending_proposals 不應直接建立 orders（由 ticker_watcher 負責）"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal)
    count = db_with_proposal.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 0


def test_executor_skips_expired_proposal(tmp_path):
    """已過期的 proposal 不應回傳 intent"""
    from openclaw.proposal_executor import execute_pending_proposals
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER
    )""")
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL
    )""")
    # expires_at 在過去
    conn.execute("""INSERT INTO strategy_proposals VALUES (
        'p_expired','test','POSITION_REBALANCE','portfolio',
        NULL,'reduce','evidence',0.8,0,'approved',?,?,?,NULL
    )""", (int(time.time()) - 3600,
           json.dumps({"symbol": "2330", "reduce_pct": 0.1, "type": "rebalance"}),
           int(time.time())))
    conn.execute("INSERT INTO positions VALUES ('2330',100,900,950,0,950)")
    conn.commit()

    intents, _ = execute_pending_proposals(conn)
    assert len(intents) == 0


def test_executor_skips_no_position(db_with_proposal):
    """無持倉的 symbol proposal 標記為 skipped"""
    from openclaw.proposal_executor import execute_pending_proposals
    db_with_proposal.execute("DELETE FROM positions WHERE symbol='3008'")
    db_with_proposal.commit()
    intents, _ = execute_pending_proposals(db_with_proposal)
    assert len(intents) == 0
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "skipped"


def test_price_zero_skips_intent(db_with_proposal):
    """current_price=0 時不應產生 SellIntent（防止零價賣單）"""
    from openclaw.proposal_executor import execute_pending_proposals
    db_with_proposal.execute("UPDATE positions SET current_price=0 WHERE symbol='3008'")
    db_with_proposal.commit()
    intents, _ = execute_pending_proposals(db_with_proposal)
    assert len(intents) == 0


def test_price_null_skips_intent(db_with_proposal):
    """current_price=NULL 時不應產生 SellIntent"""
    from openclaw.proposal_executor import execute_pending_proposals
    db_with_proposal.execute("UPDATE positions SET current_price=NULL WHERE symbol='3008'")
    db_with_proposal.commit()
    intents, _ = execute_pending_proposals(db_with_proposal)
    assert len(intents) == 0


def test_mark_intent_failed(db_with_proposal):
    """broker 拒絕後 mark_intent_failed 應標記為 failed 並記錄原因"""
    from openclaw.proposal_executor import execute_pending_proposals, mark_intent_failed
    intents, _ = execute_pending_proposals(db_with_proposal)
    mark_intent_failed(
        db_with_proposal,
        "p1",
        "broker_rejected",
        execution_key=intents[0].execution_key,
        order_id="o2",
    )
    row = db_with_proposal.execute(
        "SELECT status, decided_at, supporting_evidence FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] is not None  # decided_at should be set
    assert "broker_reject" in row[2]
    journal = db_with_proposal.execute(
        "SELECT state, last_error, last_order_id FROM proposal_execution_journal WHERE proposal_id='p1'"
    ).fetchone()
    assert journal[0] == "failed"
    assert journal[1] == "broker_rejected"
    assert journal[2] == "o2"


def test_mark_intent_executing_increments_attempt_count(db_with_proposal):
    from openclaw.proposal_executor import execute_pending_proposals, mark_intent_executing

    intents, _ = execute_pending_proposals(db_with_proposal)
    mark_intent_executing(db_with_proposal, intents[0].proposal_id, intents[0].execution_key)

    row = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()
    assert row[0] == "executing"
    journal = db_with_proposal.execute(
        "SELECT state, attempt_count FROM proposal_execution_journal WHERE proposal_id='p1'"
    ).fetchone()
    assert journal[0] == "executing"
    assert journal[1] == 1


def test_executor_skips_duplicate_prepared_journal(db_with_proposal):
    from openclaw.proposal_executor import execute_pending_proposals

    intents1, _ = execute_pending_proposals(db_with_proposal)
    intents2, _ = execute_pending_proposals(db_with_proposal)

    assert len(intents1) == 1
    assert len(intents2) == 1
    rows = db_with_proposal.execute(
        "SELECT COUNT(*) FROM proposal_execution_journal WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert rows == 1


def test_executor_recovers_stale_executing_intent(db_with_proposal):
    from openclaw.proposal_executor import execute_pending_proposals, mark_intent_executing

    intents, _ = execute_pending_proposals(db_with_proposal)
    mark_intent_executing(db_with_proposal, intents[0].proposal_id, intents[0].execution_key)
    db_with_proposal.execute(
        "UPDATE proposal_execution_journal SET updated_at=? WHERE execution_key=?",
        (0, intents[0].execution_key),
    )
    db_with_proposal.commit()

    recovered, _ = execute_pending_proposals(db_with_proposal)
    assert len(recovered) == 1
    assert recovered[0].execution_key == intents[0].execution_key


def test_strategy_direction_marked_as_noted(tmp_path):
    """STRATEGY_DIRECTION proposal 應標記為 noted"""
    from openclaw.proposal_executor import execute_pending_proposals
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER
    )""")
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL
    )""")
    conn.execute("""INSERT INTO strategy_proposals VALUES (
        'p_dir','pm','STRATEGY_DIRECTION','strategy',
        NULL,'increase exposure','evidence',0.7,1,'approved',NULL,?,?,NULL
    )""", (json.dumps({"direction": "bullish"}), int(time.time())))
    conn.commit()

    intents, n_noted = execute_pending_proposals(conn)
    assert len(intents) == 0
    assert n_noted == 1
    status = conn.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p_dir'"
    ).fetchone()[0]
    assert status == "noted"
