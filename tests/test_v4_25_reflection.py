"""Test Three-Stage Reflection Mechanism (v4 #25)."""

import pytest
import tempfile
import os
import json
import sqlite3
from datetime import datetime


def test_reflection_output_structure():
    """Test that reflection output contains all three stages."""
    from openclaw.reflection_loop import ReflectionOutput, validate_reflection_output
    
    # Valid output
    valid_payload = {
        "stage1_diagnosis": {"root_cause_code": "test", "issues": []},
        "stage2_abstraction": {"rule_text": "test rule", "confidence": 0.8},
        "stage3_refinement": {"decision": {"action": "propose"}}
    }
    
    result = validate_reflection_output(valid_payload)
    assert isinstance(result, ReflectionOutput)
    assert "root_cause_code" in result.stage1_diagnosis
    assert "rule_text" in result.stage2_abstraction
    assert "decision" in result.stage3_refinement


def test_reflection_output_missing_stage():
    """Test that missing stage raises error."""
    from openclaw.reflection_loop import validate_reflection_output
    
    # Missing stage2
    invalid_payload = {
        "stage1_diagnosis": {"root_cause_code": "test"},
        "stage3_refinement": {"decision": {}}
    }
    
    with pytest.raises(ValueError, match="stage2_abstraction"):
        validate_reflection_output(invalid_payload)


def test_check_threshold():
    """Test threshold checking."""
    from openclaw.reflection_loop import check_reflection_threshold
    
    # Above threshold
    high_confidence = {"confidence": 0.85, "rule_text": "test"}
    assert check_reflection_threshold(high_confidence) is True
    
    # Below threshold
    low_confidence = {"confidence": 0.5, "rule_text": "test"}
    assert check_reflection_threshold(low_confidence) is False
    
    # Exactly at threshold
    threshold = {"confidence": 0.7, "rule_text": "test"}
    assert check_reflection_threshold(threshold) is True
    
    # Missing confidence (defaults to 0.0)
    missing = {"rule_text": "test"}
    assert check_reflection_threshold(missing) is False


def test_insert_reflection_run():
    """Test inserting reflection run into database."""
    from openclaw.reflection_loop import ReflectionOutput, insert_reflection_run
    
    # Create in-memory database
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE reflection_runs (
            run_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            stage1_diagnosis_json TEXT NOT NULL,
            stage2_abstraction_json TEXT NOT NULL,
            stage3_refinement_json TEXT NOT NULL,
            candidate_semantic_rules INTEGER,
            semantic_memory_size INTEGER
        )
    """)
    
    # Create semantic_memory table for the function
    conn.execute("""
        CREATE TABLE semantic_memory (
            id INTEGER PRIMARY KEY,
            status TEXT
        )
    """)
    conn.execute("INSERT INTO semantic_memory (status) VALUES ('active')")
    
    # Create reflection output
    result = ReflectionOutput(
        stage1_diagnosis={"root_cause_code": "test"},
        stage2_abstraction={"rule_text": "test", "confidence": 0.8},
        stage3_refinement={"decision": {"action": "propose"}}
    )
    
    # Insert
    run_id = insert_reflection_run(conn, "2026-02-28", result)
    
    # Verify insertion
    row = conn.execute("SELECT * FROM reflection_runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row is not None
    assert row[1] == "2026-02-28"
    
    # Parse JSON
    stage1 = json.loads(row[2])
    assert stage1["root_cause_code"] == "test"


def test_record_day_episode():
    """Test recording day episode."""
    from openclaw.reflection_loop import record_day_episode
    
    # Create in-memory database
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            reflection_id TEXT,
            recorded_at TEXT NOT NULL
        )
    """)
    
    # Record episode
    episode_id = record_day_episode(conn, "2026-02-28", "ref_test_123")
    
    assert episode_id.startswith("day_2026-02-28_ref_test")
    
    # Verify insertion
    row = conn.execute("SELECT * FROM episodic_memory WHERE episode_id = ?", (episode_id,)).fetchone()
    assert row is not None
    assert row[1] == "day"
    assert row[2] == "2026-02-28"


def test_record_day_episode_missing_table():
    """Test that missing episodic_memory table doesn't crash."""
    from openclaw.reflection_loop import record_day_episode
    
    # Database without episodic_memory table
    conn = sqlite3.connect(":memory:")
    
    # Should not raise error
    episode_id = record_day_episode(conn, "2026-02-28", "test_123")
    
    assert episode_id.startswith("day_")


def test_run_daily_reflection_integration():
    """Test integration of daily reflection flow."""
    from openclaw.reflection_loop import run_daily_reflection
    
    # Create test database with all required tables
    conn = sqlite3.connect(":memory:")
    
    # Create reflection_runs table
    conn.execute("""
        CREATE TABLE reflection_runs (
            run_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            stage1_diagnosis_json TEXT NOT NULL,
            stage2_abstraction_json TEXT NOT NULL,
            stage3_refinement_json TEXT NOT NULL,
            candidate_semantic_rules INTEGER,
            semantic_memory_size INTEGER
        )
    """)
    
    # Create semantic_memory table
    conn.execute("""
        CREATE TABLE semantic_memory (
            id INTEGER PRIMARY KEY,
            status TEXT
        )
    """)
    conn.execute("INSERT INTO semantic_memory (status) VALUES ('active')")
    
    # Create episodic_memory table
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            reflection_id TEXT,
            recorded_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    
    # Run reflection
    result = run_daily_reflection(conn, "2026-02-28")
    
    # Verify result structure
    assert "run_id" in result
    assert "episode_id" in result
    assert "proposal_id" in result
    assert "threshold_passed" in result
    
    # Should pass threshold (confidence 0.85 in mock)
    assert result["threshold_passed"] is True
    
    # Verify data was inserted
    runs = conn.execute("SELECT COUNT(*) FROM reflection_runs").fetchone()[0]
    assert runs == 1
    
    episodes = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    assert episodes == 1


def test_create_proposal_from_reflection_missing_module():
    """Test that missing proposal_engine doesn't crash."""
    from openclaw.reflection_loop import ReflectionOutput, create_proposal_from_reflection
    
    conn = sqlite3.connect(":memory:")
    
    # Create a mock reflection result
    result = ReflectionOutput(
        stage1_diagnosis={},
        stage2_abstraction={"rule_text": "test", "confidence": 0.8},
        stage3_refinement={"decision": {}}
    )
    
    # This should return None without crashing
    proposal_id = create_proposal_from_reflection(conn, result, "2026-02-28")
    
    # Should be None because proposal_engine not available in test
    assert proposal_id is None


# Integration test with proposal_engine would require actual proposal_engine module
# This is tested in separate integration tests

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
