"""test_proposal_executor.py — approved 提案自動執行測試"""
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


def test_executor_creates_sell_order_for_approved_proposal(db_with_proposal):
    """approved POSITION_REBALANCE proposal 應產生 sell 訂單"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=False)
    orders = db_with_proposal.execute("SELECT symbol, side, qty FROM orders").fetchall()
    assert len(orders) == 1
    assert orders[0][0] == "3008"
    assert orders[0][1] == "sell"
    assert orders[0][2] == 300  # 1000 * 30%，取整


def test_executor_marks_proposal_as_executed(db_with_proposal):
    """執行後 proposal status 應更新為 executed"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=False)
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "executed"


def test_executor_dry_run_does_not_create_orders(db_with_proposal):
    """dry_run=True 時不建立訂單"""
    from openclaw.proposal_executor import execute_pending_proposals
    execute_pending_proposals(db_with_proposal, dry_run=True)
    count = db_with_proposal.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 0


def test_executor_skips_expired_proposal(tmp_path):
    """已過期的 proposal 不應執行"""
    from openclaw.proposal_executor import execute_pending_proposals
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

    execute_pending_proposals(conn, dry_run=False)
    count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 0  # 過期 proposal 不執行


def test_executor_skips_no_position(db_with_proposal):
    """無持倉的 symbol proposal 標記為 skipped"""
    from openclaw.proposal_executor import execute_pending_proposals
    # 刪除持倉
    db_with_proposal.execute("DELETE FROM positions WHERE symbol='3008'")
    db_with_proposal.commit()
    execute_pending_proposals(db_with_proposal, dry_run=False)
    status = db_with_proposal.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id='p1'"
    ).fetchone()[0]
    assert status == "skipped"
    count = db_with_proposal.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert count == 0
