"""Test Strategy Version Control (v4 #28)."""

import pytest
import tempfile
import os
import json
from datetime import datetime, timedelta, timezone


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
        now = datetime.now(timezone.utc)
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


def test_create_version_auto_tag():
    """Test that create_version auto-generates a version tag when none provided (line 64)."""
    from openclaw.strategy_registry import StrategyRegistry

    registry = StrategyRegistry(":memory:")
    version = registry.create_version(
        strategy_config={"k": "v"},
        created_by="pm",
        # No version_tag provided
    )
    assert "version_tag" in version
    assert "Version" in version["version_tag"]


def test_activate_version_exception_path():
    """Test activate_version returns False on DB error (lines 173-175)."""
    from openclaw.strategy_registry import StrategyRegistry

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        registry = StrategyRegistry(db_path)
        version = registry.create_version({"k": "v"}, "pm", version_tag="V1")

        # Patch get_active_version to raise so we hit except in activate_version
        def bad_get_active():
            raise RuntimeError("forced failure")

        registry.get_active_version = bad_get_active
        result = registry.activate_version(version["version_id"], "admin", "test")
        assert result is False
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_rollback_to_nonexistent_version():
    """Test rollback returns False when target version doesn't exist (line 186)."""
    from openclaw.strategy_registry import StrategyRegistry

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        registry = StrategyRegistry(db_path)
        result = registry.rollback_to_version("nonexistent_id", "pm", "test")
        assert result is False
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_rollback_exception_path():
    """Test rollback_to_version returns False on DB error (lines 258-260)."""
    from openclaw.strategy_registry import StrategyRegistry

    registry = StrategyRegistry(":memory:")
    version = registry.create_version({"k": "v"}, "pm", version_tag="V1")
    registry.activate_version(version["version_id"], "admin", "First")

    # Make _get_conn fail after get_version/get_active_version succeed
    original_get_conn = registry._get_conn
    call_count = [0]

    def counting_bad_conn():
        call_count[0] += 1
        # Allow first 2 calls (get_version + get_active_version inside rollback)
        # then fail on the 3rd (the main conn for updates)
        if call_count[0] >= 3:
            raise RuntimeError("forced failure")
        return original_get_conn()

    registry._get_conn = counting_bad_conn
    result = registry.rollback_to_version(version["version_id"], "pm", "test failure")
    assert result is False


def test_generate_monthly_report_december():
    """Test generate_monthly_report handles December correctly (line 370)."""
    from openclaw.strategy_registry import StrategyRegistry

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        registry = StrategyRegistry(db_path)
        # Should not raise; December wraps to Jan of next year
        report = registry.generate_monthly_report(2025, 12)
        assert report["year"] == 2025
        assert report["month"] == 12
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_get_next_version_number_fallback():
    """Test _get_next_version_number returns 1 when count query returns nothing (lines 419-422)."""
    from openclaw.strategy_registry import StrategyRegistry
    import sqlite3

    registry = StrategyRegistry(":memory:")
    conn = registry._get_conn()
    # Ensure table exists
    registry._ensure_table_exists(conn)
    # Normal path: 0 rows → returns 1
    result = registry._get_next_version_number(conn)
    assert result == 1
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# Tests for src/openclaw/rl/hybrid_arch/__init__.py
# These tests exercise the stable import-path re-export module.
# ---------------------------------------------------------------------------

class TestHybridArchInit:
    """Verify that rl.hybrid_arch re-exports all expected symbols."""

    def test_imports_without_error(self):
        import openclaw.rl.hybrid_arch  # noqa: F401

    def test_exports_llm_strategy_planner(self):
        from openclaw.rl.hybrid_arch import LLMStrategyPlanner
        assert LLMStrategyPlanner is not None

    def test_exports_rl_parameter_optimizer(self):
        from openclaw.rl.hybrid_arch import RLParameterOptimizer
        assert RLParameterOptimizer is not None

    def test_exports_hybrid_coordinator(self):
        from openclaw.rl.hybrid_arch import HybridCoordinator
        assert HybridCoordinator is not None

    def test_exports_strategy_plan(self):
        from openclaw.rl.hybrid_arch import StrategyPlan
        assert StrategyPlan is not None

    def test_exports_optimization_result(self):
        from openclaw.rl.hybrid_arch import OptimizationResult
        assert OptimizationResult is not None

    def test_exports_hybrid_run_result(self):
        from openclaw.rl.hybrid_arch import HybridRunResult
        assert HybridRunResult is not None

    def test_all_dunder_lists_all_exports(self):
        import openclaw.rl.hybrid_arch as mod
        expected = {
            "LLMStrategyPlanner",
            "RLParameterOptimizer",
            "HybridCoordinator",
            "StrategyPlan",
            "OptimizationResult",
            "HybridRunResult",
        }
        assert expected == set(mod.__all__)

    def test_symbols_are_same_objects_as_hybrid_architecture(self):
        """Re-exported symbols must be identical to those in the origin module."""
        from openclaw.rl.hybrid_arch import (
            HybridCoordinator,
            HybridRunResult,
            LLMStrategyPlanner,
            OptimizationResult,
            RLParameterOptimizer,
            StrategyPlan,
        )
        from openclaw.rl.hybrid_architecture import (
            HybridCoordinator as HC2,
            HybridRunResult as HRR2,
            LLMStrategyPlanner as LSP2,
            OptimizationResult as OR2,
            RLParameterOptimizer as RPO2,
            StrategyPlan as SP2,
        )
        assert LLMStrategyPlanner is LSP2
        assert RLParameterOptimizer is RPO2
        assert HybridCoordinator is HC2
        assert StrategyPlan is SP2
        assert OptimizationResult is OR2
        assert HybridRunResult is HRR2
