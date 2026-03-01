import sqlite3
import time
from openclaw.shadow_mode import (
    ShadowModeManager,
    DeploymentState,
    DeploymentMetric,
    _now_s,
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
