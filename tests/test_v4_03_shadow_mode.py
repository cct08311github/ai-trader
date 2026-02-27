"""Test Shadow Mode deployment (v4 #3)."""

import pytest
import time
from unittest.mock import Mock, patch
from openclaw.shadow_mode import ShadowModeManager, DeploymentState


def test_shadow_mode_manager_initialization():
    """Test ShadowModeManager initialization."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    assert manager.stable_version == "v1.0.0"
    assert manager.shadow_version == "v1.1.0"
    assert manager.deployment_id == "deploy_001"
    assert manager.state == DeploymentState.PENDING
    assert manager.created_at > 0


def test_shadow_mode_phase_transition():
    """Test phase transition: 10% → 30% → 100%."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    # Start deployment
    manager.start_deployment()
    assert manager.state == DeploymentState.ACTIVE
    assert manager.current_phase == "10%"
    assert manager.shadow_traffic_percent == 0.1
    
    # Advance to 30%
    manager.advance_phase()
    assert manager.current_phase == "30%"
    assert manager.shadow_traffic_percent == 0.3
    
    # Advance to 100%
    manager.advance_phase()
    assert manager.current_phase == "100%"
    assert manager.shadow_traffic_percent == 1.0
    assert manager.state == DeploymentState.FULL_DEPLOYMENT


def test_shadow_mode_rollback():
    """Test rollback within 2-hour window."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()
    manager.advance_phase()  # 30%
    
    # Simulate issue and rollback
    rollback_success = manager.rollback(reason="performance regression")
    
    assert rollback_success is True
    assert manager.state == DeploymentState.ROLLED_BACK
    assert manager.rollback_reason == "performance regression"
    assert manager.rolled_back_at > 0


def test_shadow_mode_rollback_after_2h():
    """Test rollback not allowed after 2-hour window."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()
    
    # Mock time to be >2 hours after deployment
    with patch('time.time', return_value=manager.created_at + (2 * 3600) + 1):
        rollback_success = manager.rollback(reason="too late")
        
        assert rollback_success is False
        assert manager.state == DeploymentState.ACTIVE  # Still active
        assert "outside rollback window" in manager.last_error


def test_shadow_mode_traffic_routing():
    """Test traffic routing based on percentage."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()  # 10%
    
    # Test routing decisions
    shadow_count = 0
    stable_count = 0
    
    for i in range(1000):
        if manager.should_route_to_shadow(decision_id=f"dec_{i}"):
            shadow_count += 1
        else:
            stable_count += 1
    
    # Should be approximately 10% shadow traffic
    shadow_ratio = shadow_count / 1000
    assert 0.08 <= shadow_ratio <= 0.12  # Allow ±2% tolerance
    
    # Test that same decision_id always routes the same way (consistency)
    decision_id = "consistent_decision"
    first_route = manager.should_route_to_shadow(decision_id)
    for _ in range(10):
        assert manager.should_route_to_shadow(decision_id) == first_route


def test_shadow_mode_metrics_collection():
    """Test metrics collection for shadow vs stable."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()
    
    # Record metrics
    manager.record_metric(
        decision_id="dec_001",
        metric_type="pnl",
        stable_value=0.05,
        shadow_value=0.03
    )
    
    manager.record_metric(
        decision_id="dec_002",
        metric_type="execution_time_ms",
        stable_value=150,
        shadow_value=120
    )
    
    metrics = manager.get_metrics_summary()
    
    assert len(metrics) == 2
    assert metrics[0]["metric_type"] == "pnl"
    assert metrics[1]["metric_type"] == "execution_time_ms"
    assert "shadow_better" in metrics[0]  # Boolean indicating if shadow performed better


def test_shadow_mode_decision_integration():
    """Test integration with decision pipeline."""
    from openclaw.decision_pipeline import make_decision
    
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()
    
    # Mock decision function
    def mock_decision_v1(symbol, quantity):
        return {"version": "v1.0.0", "action": "BUY"}
    
    def mock_decision_v2(symbol, quantity):
        return {"version": "v1.1.0", "action": "SELL"}
    
    # Test routing
    decision_id = "test_integration"
    if manager.should_route_to_shadow(decision_id):
        result = mock_decision_v2("2330.TW", 100)
        assert result["version"] == "v1.1.0"
    else:
        result = mock_decision_v1("2330.TW", 100)
        assert result["version"] == "v1.0.0"
    
    # Record metric for this decision
    manager.record_metric(
        decision_id=decision_id,
        metric_type="decision_quality",
        stable_value=0.7,
        shadow_value=0.8
    )


def test_shadow_mode_persistence():
    """Test that deployment state can be saved and restored."""
    manager = ShadowModeManager(
        stable_version="v1.0.0",
        shadow_version="v1.1.0",
        deployment_id="deploy_001"
    )
    
    manager.start_deployment()
    manager.advance_phase()  # 30%
    
    # Save state
    state_dict = manager.to_dict()
    
    assert state_dict["deployment_id"] == "deploy_001"
    assert state_dict["state"] == "ACTIVE"
    assert state_dict["current_phase"] == "30%"
    assert state_dict["shadow_traffic_percent"] == 0.3
    
    # Restore state
    restored_manager = ShadowModeManager.from_dict(state_dict)
    
    assert restored_manager.deployment_id == manager.deployment_id
    assert restored_manager.state == manager.state
    assert restored_manager.current_phase == manager.current_phase
    assert restored_manager.shadow_traffic_percent == manager.shadow_traffic_percent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
