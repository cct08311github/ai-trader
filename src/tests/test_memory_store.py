import sqlite3

from openclaw.memory_store import EpisodicRecord, SemanticRule, apply_episodic_decay, insert_episodic_memory, upsert_semantic_rule


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
