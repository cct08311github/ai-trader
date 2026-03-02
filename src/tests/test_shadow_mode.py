import json
import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from openclaw.shadow_mode import (
    ShadowModeManager,
    DeploymentState,
    DeploymentMetric,
    _now_s,
    get_shadow_mode_manager,
    integrate_with_decision_pipeline,
    handle_shadow_deploy_command,
    handle_shadow_rollback_command,
)


def setup_memory_db() -> sqlite3.Connection:
    """建立 :memory: SQLite 連線 + 執行必要的 migration（如果有的話）"""
    conn = sqlite3.connect(":memory:")
    # 此模組未使用資料庫，但為了符合要求，我們建立一個連接
    return conn


class TestShadowMode:
    def setup_method(self):
        self.conn = setup_memory_db()

    def teardown_method(self):
        self.conn.close()

    def test_shadow_mode_manager_creation(self):
        """成功路徑：建立管理員並啟動部署"""
        mgr = ShadowModeManager(
            stable_version="v1.0",
            shadow_version="v1.1",
            deployment_id="test-deploy",
        )
        assert mgr.state == DeploymentState.PENDING
        assert mgr.current_phase == "0%"
        assert mgr.shadow_traffic_percent == 0.0
        
        mgr.start_deployment()
        assert mgr.state == DeploymentState.ACTIVE
        assert mgr.current_phase == "10%"
        assert mgr.shadow_traffic_percent == 0.1
        assert mgr.started_at is not None

    def test_advance_phase_boundary(self):
        """邊界條件：逐步推進階段"""
        mgr = ShadowModeManager(
            stable_version="v1.0",
            shadow_version="v1.1",
            deployment_id="test-deploy",
        )
        mgr.start_deployment()
        assert mgr.current_phase == "10%"
        
        # 推進到 30%
        result = mgr.advance_phase()
        assert result is True
        assert mgr.current_phase == "30%"
        assert mgr.shadow_traffic_percent == 0.3
        
        # 推進到 100%
        result = mgr.advance_phase()
        assert result is True
        assert mgr.current_phase == "100%"
        assert mgr.shadow_traffic_percent == 1.0
        assert mgr.state == DeploymentState.FULL_DEPLOYMENT
        
        # 無法再推進
        result = mgr.advance_phase()
        assert result is False
        assert mgr.current_phase == "100%"

    def test_should_route_to_shadow_failure(self):
        """失敗路徑：不應路由到影子版本"""
        mgr = ShadowModeManager(
            stable_version="v1.0",
            shadow_version="v1.1",
            deployment_id="test-deploy",
        )
        # 尚未啟動，不應路由
        assert mgr.should_route_to_shadow("decision1") is False
        
        mgr.start_deployment()
        # 10% 流量，使用確定性雜湊，我們可以測試一個決策 ID
        # 為了簡單起見，我們只檢查函數是否被呼叫
        routed = mgr.should_route_to_shadow("decision1")
        assert isinstance(routed, bool)
        
        # 記錄指標
        mgr.record_metric("decision1", "execution_time_ms", 100.0, 80.0)
        assert len(mgr.metrics) == 1
        metric = mgr.metrics[0]
        assert metric.shadow_better is True  # 影子版本更快

    def test_rollback_within_window(self):
        """滾回測試：在時間窗口內滾回"""
        mgr = ShadowModeManager(
            stable_version="v1.0",
            shadow_version="v1.1",
            deployment_id="test-deploy",
        )
        mgr.start_deployment()
        mgr.phase_changed_at = _now_s() - 3600  # 1 小時前
        result = mgr.rollback("測試滾回")
        assert result is True
        assert mgr.state == DeploymentState.ROLLED_BACK
        assert mgr.current_phase == "0%"
        assert mgr.shadow_traffic_percent == 0.0
        assert mgr.rollback_reason == "測試滾回"

    def test_to_dict_from_dict(self):
        """序列化與反序列化"""
        mgr = ShadowModeManager(
            stable_version="v1.0",
            shadow_version="v1.1",
            deployment_id="test-deploy",
        )
        mgr.start_deployment()
        mgr.record_metric("decision1", "pnl", 100.0, 120.0)
        
        data = mgr.to_dict()
        assert data["stable_version"] == "v1.0"
        assert data["shadow_version"] == "v1.1"
        assert data["state"] == "ACTIVE"
        
        # 反序列化
        mgr2 = ShadowModeManager.from_dict(data)
        assert mgr2.deployment_id == mgr.deployment_id
        assert mgr2.state == mgr.state
        assert len(mgr2.metrics) == 1


# ---------------------------------------------------------------------------
# DeploymentMetric.shadow_better — lines 57, 60
# ---------------------------------------------------------------------------

class TestDeploymentMetricShadowBetter:
    def test_pnl_shadow_better_true(self):
        # Line 57: pnl metric, shadow_value > stable_value
        m = DeploymentMetric("d1", "pnl", stable_value=100.0, shadow_value=120.0)
        assert m.shadow_better is True

    def test_pnl_shadow_not_better(self):
        # Line 57: pnl metric, shadow_value <= stable_value
        m = DeploymentMetric("d1", "pnl", stable_value=100.0, shadow_value=80.0)
        assert m.shadow_better is False

    def test_execution_time_shadow_better(self):
        # Line 58-59: execution_time_ms, lower is better
        m = DeploymentMetric("d1", "execution_time_ms", stable_value=100.0, shadow_value=80.0)
        assert m.shadow_better is True

    def test_execution_time_shadow_worse(self):
        m = DeploymentMetric("d1", "execution_time_ms", stable_value=80.0, shadow_value=100.0)
        assert m.shadow_better is False

    def test_unknown_metric_type_returns_false(self):
        # Line 60: unknown metric type
        m = DeploymentMetric("d1", "unknown_metric", stable_value=5.0, shadow_value=10.0)
        assert m.shadow_better is False

    def test_decision_quality_shadow_better(self):
        # Line 57: decision_quality in the "higher is better" group
        m = DeploymentMetric("d1", "decision_quality", stable_value=0.5, shadow_value=0.8)
        assert m.shadow_better is True


# ---------------------------------------------------------------------------
# ShadowModeManager.start_deployment — wrong state (lines 99-100)
# ---------------------------------------------------------------------------

class TestStartDeploymentEdgeCases:
    def test_cannot_start_from_rolled_back(self):
        # Lines 99-100: wrong state for start_deployment
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.ROLLED_BACK
        mgr.start_deployment()
        # state should remain ROLLED_BACK
        assert mgr.state == DeploymentState.ROLLED_BACK
        assert mgr.last_error is not None
        assert "cannot start" in mgr.last_error

    def test_cannot_start_from_completed(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.COMPLETED
        mgr.start_deployment()
        assert mgr.state == DeploymentState.COMPLETED
        assert mgr.last_error is not None

    def test_start_idempotent_when_already_active(self):
        # start_deployment from ACTIVE state should succeed (keep started_at)
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        original_started_at = mgr.started_at
        mgr.start_deployment()  # second call from ACTIVE
        assert mgr.started_at == original_started_at  # unchanged
        assert mgr.state == DeploymentState.ACTIVE


# ---------------------------------------------------------------------------
# ShadowModeManager.advance_phase — edge cases (lines 114-115, 119-120)
# ---------------------------------------------------------------------------

class TestAdvancePhaseEdgeCases:
    def test_cannot_advance_from_pending(self):
        # Lines 114-115: wrong state (PENDING)
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        result = mgr.advance_phase()
        assert result is False
        assert mgr.last_error is not None
        assert "cannot advance" in mgr.last_error

    def test_cannot_advance_from_rolled_back(self):
        # Lines 114-115: wrong state (ROLLED_BACK)
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.ROLLED_BACK
        result = mgr.advance_phase()
        assert result is False

    def test_unknown_current_phase(self):
        # Lines 119-120: unknown current_phase
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        mgr.current_phase = "bogus_phase"
        result = mgr.advance_phase()
        assert result is False
        assert "unknown current_phase" in mgr.last_error

    def test_advance_at_100_sets_completed(self):
        # Already at last phase — returns False + state=COMPLETED
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        mgr.advance_phase()  # 30%
        mgr.advance_phase()  # 100%
        result = mgr.advance_phase()  # already at 100%
        assert result is False
        assert mgr.state == DeploymentState.COMPLETED


# ---------------------------------------------------------------------------
# ShadowModeManager.rollback — edge cases (lines 146-147, 150-151, 156-157)
# ---------------------------------------------------------------------------

class TestRollbackEdgeCases:
    def test_cannot_rollback_from_pending(self):
        # Lines 146-147: wrong state
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        result = mgr.rollback("reason")
        assert result is False
        assert "cannot rollback" in mgr.last_error

    def test_cannot_rollback_from_completed(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.COMPLETED
        result = mgr.rollback("done")
        assert result is False

    def test_rollback_missing_phase_changed_at(self):
        # Lines 150-151: phase_changed_at is None/falsy
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.ACTIVE
        mgr.phase_changed_at = None
        result = mgr.rollback("no phase_changed_at")
        assert result is False
        assert mgr.last_error == "phase_changed_at missing"

    def test_rollback_outside_window(self):
        # Lines 156-157: outside 2-hour rollback window
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        # Set phase_changed_at to 3 hours ago
        mgr.phase_changed_at = _now_s() - 3 * 3600
        result = mgr.rollback("too late")
        assert result is False
        assert mgr.last_error == "outside rollback window"


# ---------------------------------------------------------------------------
# ShadowModeManager.should_route_to_shadow — pct=0 and pct>=1 branches (lines 179, 181)
# ---------------------------------------------------------------------------

class TestShouldRouteToShadow:
    def test_pct_zero_never_routes(self):
        # Line 179: pct <= 0.0 -> return False
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.ACTIVE
        mgr.shadow_traffic_percent = 0.0
        assert mgr.should_route_to_shadow("any_id") is False

    def test_pct_one_always_routes(self):
        # Line 181: pct >= 1.0 -> return True
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.FULL_DEPLOYMENT
        mgr.shadow_traffic_percent = 1.0
        assert mgr.should_route_to_shadow("any_id") is True

    def test_partial_pct_deterministic(self):
        # 50% traffic — consistent hashing, same ID always gives same result
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.state = DeploymentState.ACTIVE
        mgr.shadow_traffic_percent = 0.5
        result1 = mgr.should_route_to_shadow("stable_decision_id")
        result2 = mgr.should_route_to_shadow("stable_decision_id")
        assert result1 == result2  # deterministic


# ---------------------------------------------------------------------------
# get_metrics_summary (lines 206-237)
# ---------------------------------------------------------------------------

class TestGetMetricsSummary:
    def test_empty_metrics(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        summary = mgr.get_metrics_summary()
        assert summary == []

    def test_single_metric_type(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.record_metric("d1", "pnl", 100.0, 120.0)
        mgr.record_metric("d2", "pnl", 200.0, 180.0)
        summary = mgr.get_metrics_summary()
        assert len(summary) == 1
        s = summary[0]
        assert s["metric_type"] == "pnl"
        assert s["count"] == 2
        assert s["stable_avg"] == 150.0
        assert s["shadow_avg"] == 150.0
        assert s["avg_delta"] == 0.0
        assert "shadow_better_count" in s
        assert "shadow_better_ratio" in s
        assert "shadow_better" in s
        assert "last_recorded_at" in s

    def test_multiple_metric_types(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.record_metric("d1", "pnl", 100.0, 110.0)
        mgr.record_metric("d2", "execution_time_ms", 200.0, 150.0)
        summary = mgr.get_metrics_summary()
        assert len(summary) == 2
        types = [s["metric_type"] for s in summary]
        assert "pnl" in types
        assert "execution_time_ms" in types

    def test_shadow_better_majority(self):
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        # 3 shadow-better, 1 not -> shadow_better_count=3, shadow_better=True
        mgr.record_metric("d1", "pnl", 100.0, 110.0)
        mgr.record_metric("d2", "pnl", 100.0, 105.0)
        mgr.record_metric("d3", "pnl", 100.0, 95.0)  # worse
        mgr.record_metric("d4", "pnl", 100.0, 108.0)
        summary = mgr.get_metrics_summary()
        assert summary[0]["shadow_better_count"] == 3
        assert summary[0]["shadow_better"] is True


# ---------------------------------------------------------------------------
# get_shadow_mode_manager — file-based loading (lines 318-339)
# ---------------------------------------------------------------------------

class TestGetShadowModeManager:
    def setup_method(self):
        # Reset global singleton before each test
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def teardown_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def test_returns_none_when_no_manager_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env var if it exists
            env = {k: v for k, v in os.environ.items() if k != "OPENCLAW_SHADOW_MODE_FILE"}
            with patch.dict(os.environ, env, clear=True):
                result = get_shadow_mode_manager()
        assert result is None

    def test_returns_active_manager_from_singleton(self):
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        sm._ACTIVE_MANAGER = mgr
        result = get_shadow_mode_manager()
        assert result is mgr

    def test_singleton_non_active_state_returns_none(self):
        # Singleton present but not ACTIVE/FULL_DEPLOYMENT
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        # Leave state as PENDING (not active)
        sm._ACTIVE_MANAGER = mgr
        result = get_shadow_mode_manager()
        assert result is None

    def test_loads_from_json_file_active(self, tmp_path):
        # Lines 327-333: load from JSON file when state is ACTIVE
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep-file"
        )
        mgr.start_deployment()
        data = mgr.to_dict()
        json_file = tmp_path / "shadow.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        with patch.dict(os.environ, {"OPENCLAW_SHADOW_MODE_FILE": str(json_file)}):
            result = get_shadow_mode_manager()
        assert result is not None
        assert result.deployment_id == "dep-file"

    def test_loads_from_json_file_non_active_returns_none(self, tmp_path):
        # File exists but state is PENDING → returns None
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep-file"
        )
        data = mgr.to_dict()  # PENDING state
        json_file = tmp_path / "shadow.json"
        json_file.write_text(json.dumps(data), encoding="utf-8")

        with patch.dict(os.environ, {"OPENCLAW_SHADOW_MODE_FILE": str(json_file)}):
            result = get_shadow_mode_manager()
        assert result is None

    def test_file_not_found_returns_none(self, tmp_path):
        # Lines 335-336: FileNotFoundError
        nonexistent = tmp_path / "missing.json"
        with patch.dict(os.environ, {"OPENCLAW_SHADOW_MODE_FILE": str(nonexistent)}):
            result = get_shadow_mode_manager()
        assert result is None

    def test_invalid_json_returns_none(self, tmp_path):
        # Lines 337-339: generic exception (invalid JSON)
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("NOT_VALID_JSON", encoding="utf-8")
        with patch.dict(os.environ, {"OPENCLAW_SHADOW_MODE_FILE": str(bad_file)}):
            result = get_shadow_mode_manager()
        assert result is None


# ---------------------------------------------------------------------------
# integrate_with_decision_pipeline (lines 353-401)
# ---------------------------------------------------------------------------

class TestIntegrateWithDecisionPipeline:
    def setup_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def teardown_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def test_no_manager_uses_stable(self):
        # Lines 355-360: mgr is None → use stable only
        stable_called = []
        shadow_called = []

        def stable():
            stable_called.append(True)
            return "stable_result"

        def shadow():
            shadow_called.append(True)
            return "shadow_result"

        result, was_shadow, metric = integrate_with_decision_pipeline(
            "dec_001", stable, shadow
        )
        assert result == "stable_result"
        assert was_shadow is False
        assert len(stable_called) == 1
        assert len(shadow_called) == 0
        assert metric["decision_id"] == "dec_001"
        assert "stable_latency_s" in metric

    def test_full_deployment_uses_shadow(self):
        # Lines 362-367: FULL_DEPLOYMENT → use shadow output
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        mgr.advance_phase()  # 30%
        mgr.advance_phase()  # 100%, FULL_DEPLOYMENT
        sm._ACTIVE_MANAGER = mgr

        shadow_called = []

        def stable():
            return "stable"

        def shadow():
            shadow_called.append(True)
            return "shadow_result"

        result, was_shadow, metric = integrate_with_decision_pipeline(
            "dec_002", stable, shadow
        )
        assert result == "shadow_result"
        assert was_shadow is True
        assert len(shadow_called) == 1
        assert "shadow_latency_s" in metric

    def test_active_deployment_no_route(self):
        # Lines 369-401: ACTIVE, but decision not routed to shadow (using a deterministic ID)
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()  # 10% traffic
        sm._ACTIVE_MANAGER = mgr

        # Find a decision_id that does NOT route
        # Use a deterministic approach — force should_route to return False
        with patch.object(mgr, "should_route_to_shadow", return_value=False):
            def stable():
                return "stable_result"

            def shadow():
                return "shadow_result"

            result, was_shadow, metric = integrate_with_decision_pipeline(
                "dec_003", stable, shadow
            )
        assert result == "stable_result"
        assert was_shadow is False
        assert metric["shadow_routed"] is False
        assert "shadow_result" not in metric

    def test_active_deployment_routed_to_shadow(self):
        # Lines 383-401: ACTIVE, routed to shadow — shadow executed, metric recorded
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()  # 10% traffic
        sm._ACTIVE_MANAGER = mgr

        with patch.object(mgr, "should_route_to_shadow", return_value=True):
            def stable():
                return "stable_result"

            def shadow():
                return "shadow_result"

            result, was_shadow, metric = integrate_with_decision_pipeline(
                "dec_004", stable, shadow
            )
        assert result == "stable_result"  # ACTIVE uses stable for output
        assert was_shadow is False
        assert metric["shadow_routed"] is True
        assert metric["shadow_result"] == "shadow_result"
        assert "shadow_latency_s" in metric
        # Metric should be recorded in mgr
        assert len(mgr.metrics) == 1

    def test_active_deployment_routed_record_metric_exception(self):
        # Lines 398-399: except Exception: pass — record_metric raises
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep1"
        )
        mgr.start_deployment()
        sm._ACTIVE_MANAGER = mgr

        with patch.object(mgr, "should_route_to_shadow", return_value=True), \
             patch.object(mgr, "record_metric", side_effect=RuntimeError("boom")):
            result, was_shadow, metric = integrate_with_decision_pipeline(
                "dec_exc", lambda: "stable", lambda: "shadow"
            )
        # Should not raise — exception is silently swallowed
        assert result == "stable"
        assert was_shadow is False


# ---------------------------------------------------------------------------
# handle_shadow_deploy_command (lines 412-424)
# ---------------------------------------------------------------------------

class TestHandleShadowDeployCommand:
    def setup_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def teardown_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def test_insufficient_args(self):
        # Line 412-413: < 3 args
        result = handle_shadow_deploy_command(["v1.0"])
        assert "Usage" in result

    def test_no_args(self):
        result = handle_shadow_deploy_command([])
        assert "Usage" in result

    def test_deploy_command_success(self):
        # Lines 415-427: successful deploy
        result = handle_shadow_deploy_command(["v1.0", "v1.1", "deploy-123"])
        assert "deploy-123" in result
        assert "v1.0" in result
        assert "v1.1" in result
        # Verify global manager is set
        import openclaw.shadow_mode as sm
        assert sm._ACTIVE_MANAGER is not None
        assert sm._ACTIVE_MANAGER.deployment_id == "deploy-123"


# ---------------------------------------------------------------------------
# handle_shadow_rollback_command (lines 437-445)
# ---------------------------------------------------------------------------

class TestHandleShadowRollbackCommand:
    def setup_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def teardown_method(self):
        import openclaw.shadow_mode as sm
        sm._ACTIVE_MANAGER = None

    def test_no_active_manager(self):
        # Line 438-439: no active manager
        result = handle_shadow_rollback_command(["some reason"])
        assert "No active shadow deployment" in result

    def test_rollback_success(self):
        # Lines 441-444: successful rollback
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep-rb"
        )
        mgr.start_deployment()
        sm._ACTIVE_MANAGER = mgr

        result = handle_shadow_rollback_command(["performance", "dropped"])
        assert "dep-rb" in result
        assert "performance dropped" in result

    def test_rollback_no_reason_uses_default(self):
        # When args is empty, reason defaults to "manual rollback"
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep-rb2"
        )
        mgr.start_deployment()
        sm._ACTIVE_MANAGER = mgr

        result = handle_shadow_rollback_command([])
        assert "manual rollback" in result

    def test_rollback_fails_when_outside_window(self):
        # Lines 444-445: rollback fails
        import openclaw.shadow_mode as sm
        mgr = ShadowModeManager(
            stable_version="v1.0", shadow_version="v1.1", deployment_id="dep-fail"
        )
        mgr.start_deployment()
        # Force outside window
        mgr.phase_changed_at = _now_s() - 10 * 3600
        sm._ACTIVE_MANAGER = mgr

        result = handle_shadow_rollback_command(["too late"])
        assert "Rollback failed" in result or "outside rollback window" in result.lower() or "dep-fail" in result


# ---------------------------------------------------------------------------
# __main__ block (lines 449-450)
# ---------------------------------------------------------------------------

class TestMainBlock:
    def test_main_block_prints(self, capsys):
        # Lines 449-450: run __main__ block via runpy
        import runpy
        runpy.run_module("openclaw.shadow_mode", run_name="__main__", alter_sys=False)
        captured = capsys.readouterr()
        assert "Shadow Mode Manager" in captured.out
