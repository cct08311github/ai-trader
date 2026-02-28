"""Test Layered Memory System (v4 #24)."""

import pytest
import tempfile
import os
import json
import sqlite3
from datetime import datetime, timedelta


def test_working_memory_operations():
    """Test working memory upsert and retrieve."""
    from openclaw.memory_store import upsert_working_memory, get_working_memory, clear_working_memory
    
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE working_memory (
            mem_key TEXT PRIMARY KEY,
            mem_value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Upsert
    test_value = {"key": "value", "number": 42}
    upsert_working_memory(conn, "test_key", test_value)
    
    # Retrieve
    retrieved = get_working_memory(conn, "test_key")
    assert retrieved is not None
    assert retrieved["key"] == "value"
    assert retrieved["number"] == 42
    
    # Update
    upsert_working_memory(conn, "test_key", {"updated": True})
    updated = get_working_memory(conn, "test_key")
    assert updated["updated"] is True
    
    # Clear
    clear_working_memory(conn)
    cleared = get_working_memory(conn, "test_key")
    assert cleared is None


def test_episodic_memory_decay():
    """Test episodic memory decay mechanism."""
    from openclaw.memory_store import EpisodicRecord, insert_episodic_memory, apply_episodic_decay
    
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy_id TEXT,
            market_regime TEXT,
            entry_reason TEXT,
            outcome_pnl REAL,
            pm_score REAL,
            root_cause_code TEXT,
            decay_score REAL DEFAULT 1.0,
            archived INTEGER DEFAULT 0
        )
    """)
    
    # Insert records
    for i in range(3):
        rec = EpisodicRecord(
            trade_date=f"2026-02-{28-i}",
            symbol="2330",
            strategy_id=f"strategy_{i}",
            market_regime="bull",
            entry_reason=f"reason_{i}",
            outcome_pnl=0.01 * i,
            pm_score=0.7 + i * 0.1,
            root_cause_code=f"code_{i}"
        )
        insert_episodic_memory(conn, rec)
    
    # Apply decay
    archived_count = apply_episodic_decay(conn, decay_lambda=0.5, archive_threshold=0.6)
    
    # First decay: 1.0 * 0.5 = 0.5 (not archived)
    # Second decay: 0.5 * 0.5 = 0.25 (archived)
    # Should archive records with decay_score < 0.6
    assert archived_count == 1
    
    # Verify decay scores
    rows = conn.execute("SELECT decay_score FROM episodic_memory ORDER BY trade_date").fetchall()
    assert len(rows) == 3
    
    # Check that archived flag is set
    archived = conn.execute("SELECT COUNT(*) FROM episodic_memory WHERE archived = 1").fetchone()[0]
    assert archived == 1


def test_semantic_memory_operations():
    """Test semantic memory operations."""
    from openclaw.memory_store import SemanticRule, upsert_semantic_rule, apply_semantic_decay
    
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE semantic_memory (
            rule_id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_episodes_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            last_validated_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Insert rule
    rule = SemanticRule(
        rule_text="test rule",
        confidence=0.8,
        source_episodes=["ep1", "ep2"],
        sample_count=10,
        last_validated_date="2026-02-28"
    )
    
    rule_id = upsert_semantic_rule(conn, rule)
    assert rule_id is not None
    
    # Update rule
    rule.rule_id = rule_id
    rule.confidence = 0.9
    rule.rule_text = "updated rule"
    
    updated_id = upsert_semantic_rule(conn, rule)
    assert updated_id == rule_id
    
    # Verify update
    row = conn.execute(
        "SELECT rule_text, confidence FROM semantic_memory WHERE rule_id = ?",
        (rule_id,)
    ).fetchone()
    
    assert row[0] == "updated rule"
    assert row[1] == 0.9


def test_semantic_decay():
    """Test semantic memory decay."""
    from openclaw.memory_store import SemanticRule, upsert_semantic_rule, apply_semantic_decay
    
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE semantic_memory (
            rule_id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_episodes_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            last_validated_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Insert rules with different confidence levels
    rule_high = SemanticRule(
        rule_text="high confidence rule",
        confidence=0.9,
        source_episodes=["ep1"],
        sample_count=20,
        last_validated_date="2026-02-28"
    )
    
    rule_low = SemanticRule(
        rule_text="low confidence rule",
        confidence=0.2,
        source_episodes=["ep2"],
        sample_count=5,
        last_validated_date="2026-02-28"
    )
    
    upsert_semantic_rule(conn, rule_high)
    upsert_semantic_rule(conn, rule_low)
    
    # Apply decay with threshold 0.25
    archived = apply_semantic_decay(conn, decay_lambda=0.8, archive_threshold=0.25)
    
    # Low confidence rule: 0.2 * 0.8 = 0.16 (<0.25) should be archived
    # High confidence rule: 0.9 * 0.8 = 0.72 (>0.25) should remain active
    assert archived == 1
    
    # Verify statuses
    active = conn.execute(
        "SELECT COUNT(*) FROM semantic_memory WHERE status = 'active'"
    ).fetchone()[0]
    
    archived_count = conn.execute(
        "SELECT COUNT(*) FROM semantic_memory WHERE status = 'archived'"
    ).fetchone()[0]
    
    assert active == 1
    assert archived_count == 1


def test_retrieve_by_priority():
    """Test retrieval by priority order."""
    from openclaw.memory_store import (
        upsert_working_memory, EpisodicRecord, insert_episodic_memory,
        SemanticRule, upsert_semantic_rule, retrieve_by_priority
    )
    
    conn = sqlite3.connect(":memory:")
    
    # Create tables
    conn.execute("""
        CREATE TABLE working_memory (
            mem_key TEXT PRIMARY KEY,
            mem_value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy_id TEXT,
            market_regime TEXT,
            entry_reason TEXT,
            outcome_pnl REAL,
            pm_score REAL,
            root_cause_code TEXT,
            decay_score REAL DEFAULT 1.0,
            archived INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE semantic_memory (
            rule_id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_episodes_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            last_validated_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Add test data
    # 1. Working memory
    upsert_working_memory(conn, "breakout_strategy", {"action": "buy", "threshold": 0.02})
    
    # 2. Episodic memory
    rec = EpisodicRecord(
        trade_date="2026-02-28",
        symbol="2330",
        strategy_id="breakout_v1",
        market_regime="bull",
        entry_reason="breakout above resistance",
        outcome_pnl=0.015,
        pm_score=0.8,
        root_cause_code="breakout_success"
    )
    insert_episodic_memory(conn, rec)
    
    # 3. Semantic memory
    rule = SemanticRule(
        rule_text="buy on breakout with volume confirmation",
        confidence=0.85,
        source_episodes=["ep1", "ep2"],
        sample_count=12,
        last_validated_date="2026-02-28"
    )
    upsert_semantic_rule(conn, rule)
    
    # Retrieve
    results = retrieve_by_priority(conn, "breakout", limit=5)
    
    # Should have results from all three layers
    assert len(results) >= 1
    
    # Check sources
    sources = [r["source"] for r in results]
    assert "working" in sources or "semantic" in sources or "episodic" in sources


def test_get_memory_stats():
    """Test memory statistics."""
    from openclaw.memory_store import (
        upsert_working_memory, EpisodicRecord, insert_episodic_memory,
        SemanticRule, upsert_semantic_rule, get_memory_stats
    )
    
    conn = sqlite3.connect(":memory:")
    
    # Create tables
    conn.execute("""
        CREATE TABLE working_memory (
            mem_key TEXT PRIMARY KEY,
            mem_value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy_id TEXT,
            market_regime TEXT,
            entry_reason TEXT,
            outcome_pnl REAL,
            pm_score REAL,
            root_cause_code TEXT,
            decay_score REAL DEFAULT 1.0,
            archived INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE semantic_memory (
            rule_id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_episodes_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            last_validated_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Add some data
    upsert_working_memory(conn, "key1", {"test": "data"})
    
    rec = EpisodicRecord(
        trade_date="2026-02-28",
        symbol="2330",
        strategy_id="test",
        market_regime="bull",
        entry_reason="test",
        outcome_pnl=0.01,
        pm_score=0.7,
        root_cause_code="test"
    )
    insert_episodic_memory(conn, rec)
    
    rule = SemanticRule(
        rule_text="test rule",
        confidence=0.8,
        source_episodes=["ep1"],
        sample_count=5,
        last_validated_date="2026-02-28"
    )
    upsert_semantic_rule(conn, rule)
    
    # Get stats
    stats = get_memory_stats(conn)
    
    assert "working_count" in stats
    assert "episodic_active" in stats
    assert "semantic_active" in stats
    assert stats["working_count"] == 1
    assert stats["episodic_active"] == 1
    assert stats["semantic_active"] == 1


def test_run_memory_hygiene():
    """Test memory hygiene task."""
    from openclaw.memory_store import (
        SemanticRule, upsert_semantic_rule, run_memory_hygiene
    )
    
    conn = sqlite3.connect(":memory:")
    
    # Create tables
    conn.execute("""
        CREATE TABLE working_memory (
            mem_key TEXT PRIMARY KEY,
            mem_value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            strategy_id TEXT,
            market_regime TEXT,
            entry_reason TEXT,
            outcome_pnl REAL,
            pm_score REAL,
            root_cause_code TEXT,
            decay_score REAL DEFAULT 1.0,
            archived INTEGER DEFAULT 0
        )
    """)
    
    conn.execute("""
        CREATE TABLE semantic_memory (
            rule_id TEXT PRIMARY KEY,
            rule_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_episodes_json TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            last_validated_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Add old semantic rule
    old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
    rule = SemanticRule(
        rule_text="old rule",
        confidence=0.5,
        source_episodes=["ep1"],
        sample_count=3,
        last_validated_date=old_date
    )
    upsert_semantic_rule(conn, rule)
    
    # Run hygiene
    results = run_memory_hygiene(conn)
    
    assert "semantic_expired" in results
    # Should expire the old rule
    assert results["semantic_expired"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
