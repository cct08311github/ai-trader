"""Test Strategy Version Control (v4 #28)."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta


def test_version_status_enum():
    """Test VersionStatus enum values."""
    from openclaw.strategy_registry import VersionStatus
    
    assert VersionStatus.DRAFT.value == "draft"
    assert VersionStatus.ACTIVE.value == "active"
    assert VersionStatus.DEPRECATED.value == "deprecated"
    assert VersionStatus.ROLLED_BACK.value == "rolled_back"


def test_registry_init():
    """Test registry initialization."""
    from openclaw.strategy_registry import StrategyRegistry
    
    registry = StrategyRegistry()
    assert registry.db_path == "data/sqlite/trades.db"
    
    # Test with custom path
    registry2 = StrategyRegistry(":memory:")
    assert registry2.db_path == ":memory:"


def test_create_version():
    """Test creating a new strategy version."""
    from openclaw.strategy_registry import StrategyRegistry, VersionStatus
    
    # Use temporary file
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create version
        config = {"buy_threshold": 0.02, "sell_threshold": 0.015}
        version = registry.create_version(
            strategy_config=config,
            created_by="pm",
            source_proposal_id="prop_123",
            version_tag="Test Version 1",
            notes="Initial test version"
        )
        
        assert "version_id" in version
        assert version["version_tag"] == "Test Version 1"
        assert version["status"] == VersionStatus.DRAFT.value
        assert version["version_id"].startswith("v")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_activate_version():
    """Test activating a version."""
    from openclaw.strategy_registry import StrategyRegistry, VersionStatus
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create and activate version
        config = {"test": "config"}
        version = registry.create_version(config, "pm", version_tag="V1")
        
        success = registry.activate_version(
            version["version_id"],
            activated_by="admin",
            reason="Initial activation"
        )
        
        assert success is True
        
        # Verify activation
        active = registry.get_active_version()
        assert active is not None
        assert active["version_id"] == version["version_id"]
        assert active["status"] == VersionStatus.ACTIVE.value
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_activate_replaces_previous():
    """Test that activating a new version deactivates previous."""
    from openclaw.strategy_registry import StrategyRegistry, VersionStatus
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create and activate first version
        v1 = registry.create_version({"config": "v1"}, "pm", version_tag="V1")
        registry.activate_version(v1["version_id"], "admin", "First")
        
        # Create and activate second version
        v2 = registry.create_version({"config": "v2"}, "pm", version_tag="V2")
        registry.activate_version(v2["version_id"], "admin", "Second")
        
        # Verify v1 is deprecated, v2 is active
        active = registry.get_active_version()
        assert active["version_id"] == v2["version_id"]
        
        v1_info = registry.get_version(v1["version_id"])
        assert v1_info["status"] == VersionStatus.DEPRECATED.value
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_rollback_to_version():
    """Test rolling back to a previous version."""
    from openclaw.strategy_registry import StrategyRegistry, VersionStatus
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create and activate first version
        v1 = registry.create_version({"config": "v1"}, "pm", version_tag="V1")
        registry.activate_version(v1["version_id"], "admin", "First")
        
        # Create and activate second version
        v2 = registry.create_version({"config": "v2"}, "pm", version_tag="V2")
        registry.activate_version(v2["version_id"], "admin", "Second")
        
        # Rollback to v1
        success = registry.rollback_to_version(
            v1["version_id"],
            rolled_back_by="critic",
            reason="v2 had issues"
        )
        
        assert success is True
        
        # Verify new active version is a rollback of v1
        active = registry.get_active_version()
        assert active is not None
        assert "Rollback" in active["version_tag"]
        
        # Verify v2 is rolled_back
        v2_info = registry.get_version(v2["version_id"])
        assert v2_info["status"] == VersionStatus.ROLLED_BACK.value
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_get_version_history():
    """Test getting version history."""
    from openclaw.strategy_registry import StrategyRegistry
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create several versions
        for i in range(3):
            registry.create_version(
                {"index": i},
                "pm",
                version_tag=f"Version {i+1}"
            )
        
        # Get history
        history = registry.get_version_history()
        
        assert len(history) == 3
        assert "Version 1" in [h["version_tag"] for h in history]
        assert "Version 3" in [h["version_tag"] for h in history]
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_generate_monthly_report():
    """Test generating monthly report."""
    from openclaw.strategy_registry import StrategyRegistry
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        registry = StrategyRegistry(db_path)
        
        # Create some versions
        v1 = registry.create_version({"config": "v1"}, "pm", version_tag="Jan Version")
        registry.activate_version(v1["version_id"], "admin", "Start")
        
        # Generate report for current month
        now = datetime.utcnow()
        report = registry.generate_monthly_report(now.year, now.month)
        
        assert report["year"] == now.year
        assert report["month"] == now.month
        assert report["total_versions"] >= 1
        assert len(report["versions"]) >= 1
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_get_nonexistent_version():
    """Test getting non-existent version returns None."""
    from openclaw.strategy_registry import StrategyRegistry
    
    import tempfile; import os; f = tempfile.NamedTemporaryFile(suffix=".db", delete=False); db_path = f.name; f.close(); registry = StrategyRegistry(db_path); import atexit; atexit.register(lambda: os.unlink(db_path) if os.path.exists(db_path) else None)
    
    version = registry.get_version("non_existent_id")
    assert version is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
