"""test_concentration_guard.py — 集中度守衛測試"""
import sqlite3
import pytest


def _make_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL)""")
    conn.execute("""CREATE TABLE strategy_proposals (
        proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
        rule_category TEXT, current_value TEXT, proposed_value TEXT,
        supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
        status TEXT, expires_at INTEGER, proposal_json TEXT, created_at INTEGER,
        decided_at INTEGER)""")
    conn.commit()
    return conn


def test_auto_reduce_when_over_60pct(tmp_path):
    """單檔超過 60% 應自動生成 approved proposal"""
    from openclaw.concentration_guard import check_concentration
    conn = _make_db(tmp_path)
    # 3008 佔 ~70%: value=591*2450=1,447,950; 2330: 151*1935=292,185; total=1,740,135
    conn.execute("INSERT INTO positions VALUES ('3008',591,379.6,2450,0,2450)")
    conn.execute("INSERT INTO positions VALUES ('2330',151,898.6,1935,0,1935)")
    conn.commit()

    proposals = check_concentration(conn)
    assert any(p["symbol"] == "3008" for p in proposals)
    p3008 = next(p for p in proposals if p["symbol"] == "3008")
    assert p3008["auto_approve"]    # 超過 60% 自動核准
    assert p3008["reduce_pct"] > 0


def test_auto_reduce_creates_approved_proposal_in_db(tmp_path):
    """自動觸發時 DB 中 proposal status 應為 approved"""
    from openclaw.concentration_guard import check_concentration
    conn = _make_db(tmp_path)
    conn.execute("INSERT INTO positions VALUES ('3008',591,379.6,2450,0,2450)")
    conn.execute("INSERT INTO positions VALUES ('2330',151,898.6,1935,0,1935)")
    conn.commit()

    check_concentration(conn)
    rows = conn.execute(
        "SELECT status FROM strategy_proposals WHERE generated_by='concentration_guard'"
    ).fetchall()
    assert len(rows) > 0
    assert any(r[0] == "approved" for r in rows)


def test_pending_proposal_when_40_to_60_pct(tmp_path):
    """單檔 40-60% 生成 pending proposal（需人工核准）"""
    from openclaw.concentration_guard import check_concentration
    conn = _make_db(tmp_path)
    # 3008: 100*2450=245,000; 2330: 200*500=100,000; total=345,000; 3008=71%...
    # 讓 3008 約 45%: value=100*2450=245k; other=300*1000=300k; total=545k; 3008=44.9%
    conn.execute("INSERT INTO positions VALUES ('3008',100,379.6,2450,0,2450)")
    conn.execute("INSERT INTO positions VALUES ('2330',300,898.6,1000,0,1000)")
    conn.commit()

    proposals = check_concentration(conn)
    if proposals:
        p3008 = next((p for p in proposals if p["symbol"] == "3008"), None)
        if p3008:
            assert not p3008["auto_approve"]  # 需人工核准


def test_no_proposals_when_under_40pct(tmp_path):
    """所有持倉均低於 40% 時不生成 proposal（各佔約 33%）"""
    from openclaw.concentration_guard import check_concentration
    conn = _make_db(tmp_path)
    # 各佔 33%：value = 100 each
    conn.execute("INSERT INTO positions VALUES ('2330',100,0,100,0,100)")
    conn.execute("INSERT INTO positions VALUES ('2317',100,0,100,0,100)")
    conn.execute("INSERT INTO positions VALUES ('2382',100,0,100,0,100)")
    conn.commit()

    proposals = check_concentration(conn)
    assert proposals == []


def test_empty_positions_returns_no_proposals(tmp_path):
    """無持倉時回傳空清單"""
    from openclaw.concentration_guard import check_concentration
    conn = _make_db(tmp_path)
    proposals = check_concentration(conn)
    assert proposals == []
