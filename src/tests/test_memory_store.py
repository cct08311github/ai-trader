import sqlite3
import json

from openclaw.memory_store import (
    EpisodicRecord,
    SemanticRule,
    apply_episodic_decay,
    apply_layered_decay,
    apply_semantic_decay,
    clear_working_memory,
    fetch_recent_episodic_by_symbol,
    get_memory_stats,
    get_working_memory,
    insert_episodic_memory,
    list_working_memory,
    retrieve_by_priority,
    run_memory_hygiene,
    upsert_semantic_rule,
    upsert_working_memory,
    _column_exists,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE working_memory(mem_key TEXT PRIMARY KEY, mem_value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE episodic_memory(
          episode_id TEXT PRIMARY KEY, trade_date TEXT NOT NULL, symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
          market_regime TEXT NOT NULL, entry_reason TEXT NOT NULL, outcome_pnl REAL NOT NULL, pm_score REAL,
          root_cause_code TEXT, decay_score REAL NOT NULL DEFAULT 1.0, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE semantic_memory(
          rule_id TEXT PRIMARY KEY, rule_text TEXT NOT NULL, confidence REAL NOT NULL, source_episodes_json TEXT NOT NULL,
          sample_count INTEGER NOT NULL, last_validated_date TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_insert_and_decay_episodic():
    conn = _conn()
    insert_episodic_memory(
        conn,
        EpisodicRecord(
            trade_date="2026-02-27",
            symbol="2330",
            strategy_id="breakout",
            market_regime="trending",
            entry_reason="test",
            outcome_pnl=-500,
            pm_score=0.4,
            root_cause_code="timing",
        ),
    )
    for _ in range(30):
        apply_episodic_decay(conn, decay_lambda=0.9, archive_threshold=0.1)
    archived = conn.execute("SELECT archived FROM episodic_memory LIMIT 1").fetchone()[0]
    assert archived == 1


def test_upsert_semantic():
    conn = _conn()
    rid = upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="rule",
            confidence=0.7,
            source_episodes=["e1", "e2"],
            sample_count=2,
            last_validated_date="2026-02-27",
        ),
    )
    row = conn.execute("SELECT confidence FROM semantic_memory WHERE rule_id = ?", (rid,)).fetchone()
    assert row[0] == 0.7


def test_apply_episodic_decay_no_episodes():
    """邊界測試：無情節記憶時應用衰減。"""
    conn = _conn()
    apply_episodic_decay(conn, decay_lambda=0.9, archive_threshold=0.1)
    # 僅確認無錯誤


def test_insert_episodic_memory_minimal():
    """正向測試：插入最簡情節記錄。"""
    conn = _conn()
    record = EpisodicRecord(
        trade_date="2026-02-27",
        symbol="2330",
        strategy_id="breakout",
        market_regime="trending",
        entry_reason="test",
        outcome_pnl=100,
        pm_score=0.8,
        root_cause_code="",
    )
    insert_episodic_memory(conn, record)
    count = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    assert count == 1


def test_upsert_semantic_rule_minimal():
    """正向測試：插入最簡語義規則。"""
    conn = _conn()
    rid = upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="test rule",
            confidence=0.5,
            source_episodes=[],
            sample_count=0,
            last_validated_date=None,
        ),
    )
    assert rid is not None


# ──────────────────────────────────────────────────────────────────────────────
# _column_exists  (lines 14-23)
# ──────────────────────────────────────────────────────────────────────────────

def test_column_exists_returns_true():
    conn = _conn()
    assert _column_exists(conn, "working_memory", "mem_key") is True


def test_column_exists_returns_false_unknown_column():
    conn = _conn()
    assert _column_exists(conn, "working_memory", "nonexistent_column") is False


def test_column_exists_returns_false_on_exception():
    """Pass a broken connection-like object to trigger the except branch (line 18-19)."""
    class BrokenConn:
        def execute(self, *a, **k):
            raise RuntimeError("broken")
    assert _column_exists(BrokenConn(), "any_table", "any_col") is False


# ──────────────────────────────────────────────────────────────────────────────
# insert_episodic_memory WITHOUT created_at column  (line 94 branch)
# ──────────────────────────────────────────────────────────────────────────────

def _conn_no_created_at() -> sqlite3.Connection:
    """Schema without created_at so the else-branch in insert_episodic_memory fires."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE working_memory(mem_key TEXT PRIMARY KEY, mem_value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE episodic_memory(
          episode_id TEXT PRIMARY KEY, trade_date TEXT NOT NULL, symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
          market_regime TEXT NOT NULL, entry_reason TEXT NOT NULL, outcome_pnl REAL NOT NULL, pm_score REAL,
          root_cause_code TEXT, decay_score REAL NOT NULL DEFAULT 1.0, archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE semantic_memory(
          rule_id TEXT PRIMARY KEY, rule_text TEXT NOT NULL, confidence REAL NOT NULL, source_episodes_json TEXT NOT NULL,
          sample_count INTEGER NOT NULL, last_validated_date TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_insert_episodic_without_created_at_column():
    """Exercises the else-branch (line 94) in insert_episodic_memory."""
    conn = _conn_no_created_at()
    rec = EpisodicRecord(
        trade_date="2026-01-01",
        symbol="2330",
        strategy_id="s1",
        market_regime="bull",
        entry_reason="gap",
        outcome_pnl=100.0,
        pm_score=0.9,
        root_cause_code="ok",
    )
    eid = insert_episodic_memory(conn, rec)
    assert eid is not None
    row = conn.execute("SELECT episode_id FROM episodic_memory").fetchone()
    assert row[0] == eid


# ──────────────────────────────────────────────────────────────────────────────
# upsert_working_memory / clear_working_memory  (lines 49-63)
# ──────────────────────────────────────────────────────────────────────────────

def test_upsert_and_clear_working_memory():
    conn = _conn()
    upsert_working_memory(conn, "key1", {"x": 1})
    upsert_working_memory(conn, "key2", {"y": 2})
    count = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
    assert count == 2

    # Upsert again (ON CONFLICT branch)
    upsert_working_memory(conn, "key1", {"x": 99})
    row = conn.execute("SELECT mem_value_json FROM working_memory WHERE mem_key='key1'").fetchone()
    assert json.loads(row[0])["x"] == 99

    clear_working_memory(conn)
    count2 = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()[0]
    assert count2 == 0


# ──────────────────────────────────────────────────────────────────────────────
# fetch_recent_episodic_by_symbol  (lines 200-211)
# ──────────────────────────────────────────────────────────────────────────────

def test_fetch_recent_episodic_by_symbol():
    conn = _conn()
    rec = EpisodicRecord(
        trade_date="2026-02-01",
        symbol="2330",
        strategy_id="strat",
        market_regime="bull",
        entry_reason="test",
        outcome_pnl=50.0,
        pm_score=0.8,
        root_cause_code="ok",
    )
    insert_episodic_memory(conn, rec)
    results = fetch_recent_episodic_by_symbol(conn, "2330", limit=5)
    assert len(results) == 1
    # The function selects: episode_id, trade_date, market_regime, outcome_pnl, decay_score, root_cause_code
    assert results[0]["market_regime"] == "bull"
    assert results[0]["outcome_pnl"] == 50.0


def test_fetch_recent_episodic_by_symbol_empty():
    conn = _conn()
    results = fetch_recent_episodic_by_symbol(conn, "9999", limit=5)
    assert results == []


# ──────────────────────────────────────────────────────────────────────────────
# get_working_memory  (lines 218-229)
# ──────────────────────────────────────────────────────────────────────────────

def test_get_working_memory_existing():
    conn = _conn()
    upsert_working_memory(conn, "my_key", {"val": 42})
    val = get_working_memory(conn, "my_key")
    assert val == {"val": 42}


def test_get_working_memory_missing():
    conn = _conn()
    val = get_working_memory(conn, "nonexistent")
    assert val is None


def test_get_working_memory_invalid_json():
    """Covers the except branch in get_working_memory (lines 228-229)."""
    conn = _conn()
    # Insert raw invalid JSON directly
    conn.execute(
        "INSERT INTO working_memory(mem_key, mem_value_json, updated_at) VALUES (?, ?, datetime('now'))",
        ("bad_key", "NOT_VALID_JSON{{")
    )
    val = get_working_memory(conn, "bad_key")
    assert val is None


# ──────────────────────────────────────────────────────────────────────────────
# list_working_memory  (lines 234-258)
# ──────────────────────────────────────────────────────────────────────────────

def test_list_working_memory():
    conn = _conn()
    upsert_working_memory(conn, "a_key", {"a": 1})
    upsert_working_memory(conn, "b_key", {"b": 2})
    rows = list_working_memory(conn)
    assert len(rows) == 2
    keys = {r["key"] for r in rows}
    assert "a_key" in keys
    assert "b_key" in keys


def test_list_working_memory_with_pattern():
    conn = _conn()
    upsert_working_memory(conn, "prefix_x", {"v": 1})
    upsert_working_memory(conn, "other_y", {"v": 2})
    rows = list_working_memory(conn, pattern="prefix%")
    assert len(rows) == 1
    assert rows[0]["key"] == "prefix_x"


def test_list_working_memory_invalid_json():
    """Covers the except branch inside list_working_memory."""
    conn = _conn()
    conn.execute(
        "INSERT INTO working_memory(mem_key, mem_value_json, updated_at) VALUES (?, ?, datetime('now'))",
        ("bad", "{{INVALID")
    )
    rows = list_working_memory(conn)
    assert len(rows) == 1
    assert rows[0]["value"] is None


# ──────────────────────────────────────────────────────────────────────────────
# apply_semantic_decay  (lines 267-289)
# ──────────────────────────────────────────────────────────────────────────────

def test_apply_semantic_decay():
    conn = _conn()
    rid = upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="some rule",
            confidence=0.05,  # below 0.1 after decay
            source_episodes=["e1"],
            sample_count=1,
            last_validated_date="2026-01-01",
        ),
    )
    count = apply_semantic_decay(conn, decay_lambda=0.97, archive_threshold=0.1)
    # confidence 0.05 * 0.97 = 0.0485, already below 0.1 → archived
    row = conn.execute("SELECT status FROM semantic_memory WHERE rule_id=?", (rid,)).fetchone()
    assert row[0] == "archived"


def test_apply_semantic_decay_high_confidence_stays_active():
    conn = _conn()
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="strong rule",
            confidence=0.9,
            source_episodes=[],
            sample_count=5,
            last_validated_date="2026-01-01",
        ),
    )
    apply_semantic_decay(conn, decay_lambda=0.97, archive_threshold=0.1)
    row = conn.execute("SELECT status FROM semantic_memory").fetchone()
    assert row[0] == "active"


# ──────────────────────────────────────────────────────────────────────────────
# apply_layered_decay  (lines 295-316)
# ──────────────────────────────────────────────────────────────────────────────

def test_apply_layered_decay():
    conn = _conn()
    upsert_working_memory(conn, "k", {"v": 1})
    rec = EpisodicRecord(
        trade_date="2026-01-01",
        symbol="2330",
        strategy_id="s1",
        market_regime="bull",
        entry_reason="e",
        outcome_pnl=10.0,
        pm_score=0.8,
        root_cause_code="ok",
    )
    insert_episodic_memory(conn, rec)
    result = apply_layered_decay(conn)
    assert "working_deleted" in result
    assert "episodic_archived" in result
    assert "semantic_archived" in result


# ──────────────────────────────────────────────────────────────────────────────
# retrieve_by_priority  (lines 331-405)
# ──────────────────────────────────────────────────────────────────────────────

def test_retrieve_by_priority_all_sources():
    conn = _conn()
    # Insert working memory with key matching query
    upsert_working_memory(conn, "breakout", {"strategy": "break"})

    # Insert semantic rule with matching text
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="buy on breakout above MA",
            confidence=0.85,
            source_episodes=["ep1", "ep2"],
            sample_count=10,
            last_validated_date="2026-01-01",
        ),
    )

    # Insert episodic record with matching symbol
    rec = EpisodicRecord(
        trade_date="2026-01-01",
        symbol="breakout_test",
        strategy_id="s1",
        market_regime="bull",
        entry_reason="breakout",
        outcome_pnl=100.0,
        pm_score=0.9,
        root_cause_code="ok",
    )
    insert_episodic_memory(conn, rec)

    results = retrieve_by_priority(conn, "breakout", limit=10)
    assert len(results) >= 1
    sources = {r["source"] for r in results}
    assert "working" in sources


def test_retrieve_by_priority_semantic_invalid_json():
    """Covers the except branch for bad source_episodes_json."""
    conn = _conn()
    # Insert a semantic rule with bad source_episodes_json directly
    conn.execute(
        """
        INSERT INTO semantic_memory(rule_id, rule_text, confidence, source_episodes_json, sample_count,
          last_validated_date, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        ("r1", "test query rule", 0.8, "INVALID_JSON{{", 5, "2026-01-01", "active")
    )
    results = retrieve_by_priority(conn, "test query", limit=5)
    # Should still return the result, with empty source_episodes
    assert any(r["source"] == "semantic" for r in results)
    sem = next(r for r in results if r["source"] == "semantic")
    assert sem["source_episodes"] == []


def test_retrieve_by_priority_no_match():
    conn = _conn()
    results = retrieve_by_priority(conn, "zzz_no_match_zzz", limit=5)
    assert results == []


def test_retrieve_by_priority_limit_applied():
    conn = _conn()
    for i in range(5):
        upsert_semantic_rule(
            conn,
            SemanticRule(
                rule_text=f"query rule {i}",
                confidence=0.8,
                source_episodes=[],
                sample_count=1,
                last_validated_date="2026-01-01",
            ),
        )
    results = retrieve_by_priority(conn, "query rule", limit=3)
    assert len(results) <= 3


# ──────────────────────────────────────────────────────────────────────────────
# get_memory_stats  (lines 410-448)
# ──────────────────────────────────────────────────────────────────────────────

def test_get_memory_stats():
    conn = _conn()
    upsert_working_memory(conn, "k1", {"a": 1})
    rec = EpisodicRecord(
        trade_date="2026-01-01",
        symbol="2330",
        strategy_id="s",
        market_regime="bull",
        entry_reason="e",
        outcome_pnl=10.0,
        pm_score=0.8,
        root_cause_code="ok",
    )
    insert_episodic_memory(conn, rec)
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="rule",
            confidence=0.7,
            source_episodes=[],
            sample_count=1,
            last_validated_date="2026-01-01",
        ),
    )
    stats = get_memory_stats(conn)
    assert stats["working_count"] == 1
    assert stats["episodic_active"] == 1
    assert stats["episodic_archived"] == 0
    assert stats["semantic_active"] == 1
    assert stats["semantic_archived"] == 0
    assert isinstance(stats["episodic_avg_decay"], float)
    assert isinstance(stats["semantic_avg_confidence"], float)


def test_get_memory_stats_empty():
    conn = _conn()
    stats = get_memory_stats(conn)
    assert stats["working_count"] == 0
    assert stats["episodic_active"] == 0
    assert stats["episodic_avg_decay"] == 0.0
    assert stats["semantic_avg_confidence"] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# run_memory_hygiene  (lines 454-469)
# ──────────────────────────────────────────────────────────────────────────────

def test_run_memory_hygiene():
    conn = _conn()
    upsert_working_memory(conn, "k", {"v": 1})
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="old rule",
            confidence=0.9,
            source_episodes=[],
            sample_count=1,
            last_validated_date="2020-01-01",  # very old → will expire
        ),
    )
    result = run_memory_hygiene(conn)
    assert "working_deleted" in result
    assert "episodic_archived" in result
    assert "semantic_archived" in result
    assert "semantic_expired" in result
    # The rule is old enough (>90 days) to be expired
    assert result["semantic_expired"] >= 1


def test_run_memory_hygiene_no_expiry():
    conn = _conn()
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="fresh rule",
            confidence=0.9,
            source_episodes=[],
            sample_count=1,
            last_validated_date="2026-01-01",
        ),
    )
    result = run_memory_hygiene(conn)
    assert result["semantic_expired"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# test_layered_memory function at module level  (lines 478-570)
# ──────────────────────────────────────────────────────────────────────────────

def test_test_layered_memory_function():
    """Directly calls the development helper function to cover lines 478-570."""
    from openclaw.memory_store import test_layered_memory
    # Should not raise; covers the entire function body
    test_layered_memory()
