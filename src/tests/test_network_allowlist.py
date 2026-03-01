import sqlite3
import os
import pytest
from openclaw.network_allowlist import (
    check_ip_whitelist,
    enforce_network_security,
    NetworkSecurityError,
    _parse_allowlist,
)


def setup_memory_db() -> sqlite3.Connection:
    """建立 :memory: SQLite 連線 + 執行必要的 migration（如果有的話）"""
    conn = sqlite3.connect(":memory:")
    # 建立 incidents 表格以測試記錄功能
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            severity TEXT NOT NULL,
            source TEXT NOT NULL,
            code TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        )
    """)
    return conn


class TestNetworkAllowlist:
    def setup_method(self):
        self.conn = setup_memory_db()

    def teardown_method(self):
        self.conn.close()

    def test_check_ip_whitelist_success(self):
        """成功路徑：IP 在允許清單中"""
        whitelist = ["192.168.1.0/24", "10.0.0.1"]
        assert check_ip_whitelist("192.168.1.100", whitelist) is True
        assert check_ip_whitelist("10.0.0.1", whitelist) is True

    def test_check_ip_whitelist_failure(self):
        """失敗路徑：IP 不在允許清單中"""
        whitelist = ["192.168.1.0/24"]
        assert check_ip_whitelist("10.0.0.2", whitelist) is False

    def test_check_ip_whitelist_boundary(self):
        """邊界條件：無效的允許清單項目"""
        whitelist = ["invalid_ip", "", "192.168.1.0/33"]
        # 應忽略無效項目，因此任何 IP 都不匹配
        assert check_ip_whitelist("192.168.1.1", whitelist) is False

    def test_parse_allowlist(self):
        """解析允許清單字串"""
        raw = "192.168.1.0/24, 10.0.0.1"
        result = _parse_allowlist(raw)
        assert "192.168.1.0/24" in result
        assert "10.0.0.1" in result

    def test_enforce_network_security_without_whitelist(self):
        """無允許清單時不強制執行"""
        # 模擬環境變數
        os.environ.pop("OPENCLAW_IP_ALLOWLIST", None)
        # 使用測試 IP
        os.environ["OPENCLAW_CURRENT_IP"] = "8.8.8.8"
        try:
            ip = enforce_network_security()
            assert ip == "8.8.8.8"
        finally:
            os.environ.pop("OPENCLAW_CURRENT_IP", None)

    def test_enforce_network_security_denied(self):
        """IP 被拒絕時引發異常"""
        whitelist = ["192.168.1.0/24"]
        os.environ["OPENCLAW_CURRENT_IP"] = "8.8.8.8"
        try:
            with pytest.raises(NetworkSecurityError):
                enforce_network_security(whitelist=whitelist)
        finally:
            os.environ.pop("OPENCLAW_CURRENT_IP", None)

    def test_enforce_network_security_allowed(self):
        """IP 被允許時通過"""
        whitelist = ["8.8.8.8"]
        os.environ["OPENCLAW_CURRENT_IP"] = "8.8.8.8"
        try:
            ip = enforce_network_security(whitelist=whitelist)
            assert ip == "8.8.8.8"
        finally:
            os.environ.pop("OPENCLAW_CURRENT_IP", None)
