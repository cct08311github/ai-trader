"""Test Authority Boundary (v4 #29)."""

import pytest
import sqlite3
import tempfile
import os
from datetime import datetime, timedelta


def test_authority_level_enum():
    """Test AuthorityLevel enum values."""
    from openclaw.authority import AuthorityLevel
    
    assert AuthorityLevel.LEVEL_0.value == 0
    assert AuthorityLevel.LEVEL_1.value == 1
    assert AuthorityLevel.LEVEL_2.value == 2
    assert AuthorityLevel.LEVEL_3.value == 3


def test_level3_forbidden_categories():
    """Test Level 3 forbidden categories match proposal engine."""
    from openclaw.authority import LEVEL3_FORBIDDEN_CATEGORIES
    
    forbidden = {"stop_loss_logic", "position_sizing", "symbol_universe", 
                 "live_mode_switch", "monthly_drawdown_limit", "risk_parameters"}
    assert LEVEL3_FORBIDDEN_CATEGORIES == forbidden


def test_engine_init():
    """Test authority engine initialization."""
    from openclaw.authority import AuthorityEngine
    
    engine = AuthorityEngine()
    assert engine.db_path == "data/sqlite/trades.db"
    
    # Test with custom path
    engine2 = AuthorityEngine(":memory:")
    assert engine2.db_path == ":memory:"


def test_get_current_level_default():
    """Test getting default authority level when no table exists."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    
    # Use temporary file
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        engine = AuthorityEngine(db_path)
        level = engine.get_current_level()
        
        # Default should be LEVEL_2
        assert level == AuthorityLevel.LEVEL_2
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_set_and_get_level():
    """Test setting and getting authority level."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    import sqlite3
    
    # Use temporary file
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        engine = AuthorityEngine(db_path)
        
        # Initial default
        level = engine.get_current_level()
        assert level == AuthorityLevel.LEVEL_2
        
        # Insert a completed compliance item to allow LEVEL_3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT CHECK(status IN ('not_started', 'in_progress', 'completed')),
                completed_date TEXT,
                evidence_path TEXT,
                responsible_person TEXT,
                last_updated TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO compliance_status 
            (requirement_id, description, status, completed_date, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("REQ_TEST", "Test requirement", "completed", "2025-01-01", "2025-01-01")
        )
        conn.commit()
        conn.close()
        
        # Now set to LEVEL_3 should succeed
        success = engine.set_level(
            level=AuthorityLevel.LEVEL_3,
            changed_by="pm",
            reason="Testing level upgrade"
        )
        
        assert success is True
        
        # Verify new level
        new_level = engine.get_current_level()
        assert new_level == AuthorityLevel.LEVEL_3
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_can_propose():
    """Test can_propose method."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    
    engine = AuthorityEngine(":memory:")
    
    # Mock different levels
    def mock_level(level):
        engine.get_current_level = lambda: level
        return engine
    
    # Level 0 cannot propose
    engine_l0 = mock_level(AuthorityLevel.LEVEL_0)
    assert engine_l0.can_propose() is False
    
    # Level 1 cannot propose
    engine_l1 = mock_level(AuthorityLevel.LEVEL_1)
    assert engine_l1.can_propose() is False
    
    # Level 2 can propose
    engine_l2 = mock_level(AuthorityLevel.LEVEL_2)
    assert engine_l2.can_propose() is True
    
    # Level 3 can propose
    engine_l3 = mock_level(AuthorityLevel.LEVEL_3)
    assert engine_l3.can_propose() is True


def test_can_auto_approve():
    """Test can_auto_approve method."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    
    engine = AuthorityEngine(":memory:")
    
    # Mock different levels
    def mock_level(level):
        engine.get_current_level = lambda: level
        return engine
    
    # Level 2 cannot auto-approve even non-sensitive
    engine_l2 = mock_level(AuthorityLevel.LEVEL_2)
    assert engine_l2.can_auto_approve("entry_parameters") is False
    assert engine_l2.can_auto_approve("stop_loss_logic") is False
    
    # Level 3 can auto-approve non-sensitive
    engine_l3 = mock_level(AuthorityLevel.LEVEL_3)
    assert engine_l3.can_auto_approve("entry_parameters") is True
    
    # Level 3 cannot auto-approve forbidden categories
    assert engine_l3.can_auto_approve("stop_loss_logic") is False
    assert engine_l3.can_auto_approve("position_sizing") is False


def test_check_proposal_authorization():
    """Test proposal authorization checks."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    
    engine = AuthorityEngine(":memory:")
    
    # Mock level 2
    engine.get_current_level = lambda: AuthorityLevel.LEVEL_2
    
    # Level 2 with non-sensitive category
    result = engine.check_proposal_authorization({
        "rule_category": "entry_parameters"
    })
    
    assert result["allowed"] is True
    assert result["level"] == 2
    assert result["requires_human_approval"] is True
    assert result["reason_code"] == "AUTH_MANUAL_REQUIRED"
    
    # Mock level 3
    engine.get_current_level = lambda: AuthorityLevel.LEVEL_3
    
    # Level 3 with non-sensitive category
    result = engine.check_proposal_authorization({
        "rule_category": "entry_parameters"
    })
    
    assert result["allowed"] is True
    assert result["level"] == 3
    assert result["requires_human_approval"] is False
    assert result["reason_code"] == "AUTH_AUTO_APPROVE_ALLOWED"
    
    # Level 3 with forbidden category
    result = engine.check_proposal_authorization({
        "rule_category": "stop_loss_logic"
    })
    
    assert result["allowed"] is True
    assert result["level"] == 3
    assert result["requires_human_approval"] is True
    assert result["reason_code"] == "AUTH_MANUAL_REQUIRED"


def test_get_audit_log():
    """Test getting authority audit log."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    import sqlite3
    
    # Use temporary file
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        engine = AuthorityEngine(db_path)
        
        # Initially empty
        log = engine.get_audit_log()
        assert log == []
        
        # Insert a completed compliance item to allow LEVEL_3
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT CHECK(status IN ('not_started', 'in_progress', 'completed')),
                completed_date TEXT,
                evidence_path TEXT,
                responsible_person TEXT,
                last_updated TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO compliance_status 
            (requirement_id, description, status, completed_date, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("REQ_TEST", "Test requirement", "completed", "2025-01-01", "2025-01-01")
        )
        conn.commit()
        conn.close()
        
        # Set level a few times
        engine.set_level(AuthorityLevel.LEVEL_3, "pm", "Upgrade for testing")
        engine.set_level(AuthorityLevel.LEVEL_2, "critic", "Downgrade due to risk")
        
        # Get audit log
        log = engine.get_audit_log()
        
        assert len(log) == 2
        assert log[0]["new_level"] == 2  # Most recent first
        assert log[0]["changed_by"] == "critic"
        assert log[1]["new_level"] == 3
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
