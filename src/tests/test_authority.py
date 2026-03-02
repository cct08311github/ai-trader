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


def test_get_current_level_invalid_value():
    """Test get_current_level returns LEVEL_2 when DB has invalid level value (lines 70-71)."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        # Pre-populate table with an invalid level value
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE authority_policy (
                id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL,
                changed_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO authority_policy (id, level, changed_by, reason, effective_from, updated_at) VALUES (1, 999, 'test', 'test', 'now', 'now')"
        )
        conn.commit()
        conn.close()

        engine = AuthorityEngine(db_path)
        level = engine.get_current_level()
        # 999 is not a valid AuthorityLevel → falls back to LEVEL_2
        assert level == AuthorityLevel.LEVEL_2
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_get_current_level_no_row():
    """Test get_current_level returns LEVEL_2 when table exists but has no row (line 65)."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE authority_policy (
                id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL,
                changed_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        engine = AuthorityEngine(db_path)
        level = engine.get_current_level()
        assert level == AuthorityLevel.LEVEL_2
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_set_level_blocked_when_compliance_incomplete(tmp_path):
    """Test set_level returns False when compliance not complete for LEVEL_3 (lines 80-84)."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel

    db_path = str(tmp_path / "auth.db")
    engine = AuthorityEngine(db_path)

    # compliance_status table does not exist → check_compliance_complete returns False
    result = engine.set_level(AuthorityLevel.LEVEL_3, "pm", "try level 3")
    assert result is False


def test_set_level_exception_path(tmp_path):
    """Test set_level returns False when an exception occurs during DB write (lines 112-114)."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel
    import sqlite3

    db_path = str(tmp_path / "auth.db")
    engine = AuthorityEngine(db_path)

    # Patch check_compliance_complete so it returns True without using _get_conn
    engine.check_compliance_complete = lambda: True

    # Patch _ensure_table_exists to raise so we hit the except block in set_level
    def bad_ensure(conn):
        raise RuntimeError("forced DB failure")

    engine._ensure_table_exists = bad_ensure

    result = engine.set_level(AuthorityLevel.LEVEL_2, "pm", "test failure")
    assert result is False


def test_check_proposal_authorization_level_too_low():
    """Test check_proposal_authorization returns not-allowed for Level 0/1 (line 158)."""
    from openclaw.authority import AuthorityEngine, AuthorityLevel

    engine = AuthorityEngine(":memory:")

    for level in (AuthorityLevel.LEVEL_0, AuthorityLevel.LEVEL_1):
        engine.get_current_level = lambda l=level: l
        result = engine.check_proposal_authorization({"rule_category": "entry_parameters"})
        assert result["allowed"] is False
        assert result["reason_code"] == "AUTH_LEVEL_TOO_LOW"
        assert result["requires_human_approval"] is True


def test_check_compliance_no_table(tmp_path):
    """Test check_compliance_complete returns False when compliance table missing (line 238)."""
    from openclaw.authority import AuthorityEngine

    db_path = str(tmp_path / "auth.db")
    engine = AuthorityEngine(db_path)

    # No compliance_status table created
    result = engine.check_compliance_complete()
    assert result is False


def test_check_compliance_no_required_items(tmp_path):
    """Test check_compliance_complete returns True when no REQ_ items exist (line 254)."""
    from openclaw.authority import AuthorityEngine
    import sqlite3

    db_path = str(tmp_path / "auth.db")
    engine = AuthorityEngine(db_path)

    # Create table but add no REQ_ items
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE compliance_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id TEXT UNIQUE NOT NULL,
            description TEXT,
            status TEXT,
            completed_date TEXT,
            evidence_path TEXT,
            responsible_person TEXT,
            last_updated TEXT
        )
    """)
    # Insert an item that does NOT start with REQ_
    conn.execute(
        "INSERT INTO compliance_status (requirement_id, status) VALUES ('OPT_ITEM', 'not_started')"
    )
    conn.commit()
    conn.close()

    result = engine.check_compliance_complete()
    assert result is True


def test_check_compliance_exception_path(tmp_path):
    """Test check_compliance_complete returns False on unexpected exception (lines 257-261)."""
    from openclaw.authority import AuthorityEngine
    import sqlite3

    db_path = str(tmp_path / "auth.db")
    engine = AuthorityEngine(db_path)

    # Create the compliance_status table with a broken schema (no 'status' column)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE compliance_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requirement_id TEXT UNIQUE NOT NULL
        )
    """)
    conn.execute("INSERT INTO compliance_status (requirement_id) VALUES ('REQ_BROKEN')")
    conn.commit()
    conn.close()

    # The query references 'status' column which doesn't exist → OperationalError → returns False
    result = engine.check_compliance_complete()
    assert result is False


def test_get_authority_level_backward_compat(tmp_path):
    """Test the backward-compat get_authority_level function (lines 324-325)."""
    from openclaw.authority import get_authority_level
    import sqlite3

    db_path = str(tmp_path / "auth.db")
    conn = sqlite3.connect(db_path)
    # Returns default level (2) when no table
    level = get_authority_level(conn)
    assert level == 2
    conn.close()


def test_authority_main_block():
    """Test the __main__ block executes without error (lines 329-338)."""
    import runpy
    import openclaw.authority as mod

    # Run the module's __main__ block by calling runpy with run_name="__main__"
    # We use a temporary DB that doesn't exist (default path) — get_current_level returns LEVEL_2
    # Patch db_path to :memory: to avoid filesystem issues
    original_init = mod.AuthorityEngine.__init__

    def patched_init(self, db_path=None):
        original_init(self, ":memory:")

    mod.AuthorityEngine.__init__ = patched_init
    try:
        runpy.run_module("openclaw.authority", run_name="__main__", alter_sys=False)
    finally:
        mod.AuthorityEngine.__init__ = original_init


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
