import sqlite3
import os
import json
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

    def test_check_ip_whitelist_fine_cidr_skipped(self):
        """Line 35: CIDR with prefixlen > 24 (e.g. /25) is skipped per policy."""
        # /25 is too fine-grained → policy skips it → IP not matched even if in range
        whitelist = ["10.0.0.0/25"]
        assert check_ip_whitelist("10.0.0.1", whitelist) is False

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


# ---------------------------------------------------------------------------
# New tests targeting previously uncovered lines
# ---------------------------------------------------------------------------


class TestParseAllowlistSpaceSeparated:
    """Lines 54-55: continue on empty chunk + parts.extend with space-separated entries."""

    def test_space_separated_entries_in_chunk(self):
        """_parse_allowlist handles space-separated IPs within a comma chunk."""
        raw = "192.168.1.1 10.0.0.1, 172.16.0.1"
        result = _parse_allowlist(raw)
        assert "192.168.1.1" in result
        assert "10.0.0.1" in result
        assert "172.16.0.1" in result

    def test_newline_separator(self):
        """_parse_allowlist handles newline-separated entries."""
        raw = "192.168.1.1\n10.0.0.2\n172.16.0.3"
        result = _parse_allowlist(raw)
        assert "192.168.1.1" in result
        assert "10.0.0.2" in result
        assert "172.16.0.3" in result

    def test_empty_chunks_skipped_via_continue(self):
        """Line 55: empty chunks from consecutive commas hit the continue branch."""
        raw = "192.168.1.1,,10.0.0.2"
        result = _parse_allowlist(raw)
        assert "192.168.1.1" in result
        assert "10.0.0.2" in result
        # no empty strings in result
        assert "" not in result


class TestGetCurrentPublicIp:
    """Lines 70-84: get_current_public_ip URL fetch logic."""

    def test_returns_override_ip_from_env(self, monkeypatch):
        """When OPENCLAW_CURRENT_IP env var is set, returns it without HTTP fetch."""
        from openclaw.network_allowlist import get_current_public_ip
        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "203.0.113.50")
        assert get_current_public_ip() == "203.0.113.50"

    def test_fetches_ip_from_url_on_success(self, monkeypatch):
        """Lines 77-80: urlopen succeeds and returns a valid IP."""
        from unittest.mock import MagicMock
        from openclaw.network_allowlist import get_current_public_ip
        monkeypatch.delenv("OPENCLAW_CURRENT_IP", raising=False)

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"203.0.113.99"

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: mock_resp)

        result = get_current_public_ip()
        assert result == "203.0.113.99"

    def test_raises_when_all_urls_fail(self, monkeypatch):
        """Lines 74-84: when all URLs fail, raises NetworkSecurityError."""
        from openclaw.network_allowlist import get_current_public_ip, NetworkSecurityError
        monkeypatch.delenv("OPENCLAW_CURRENT_IP", raising=False)

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: (_ for _ in ()).throw(OSError("conn failed")))

        with pytest.raises(NetworkSecurityError, match="SEC_NETWORK_IP_LOOKUP_FAILED"):
            get_current_public_ip()


class TestInsertIncidentBestEffort:
    """Lines 105, 120-121: _insert_incident_best_effort edge cases."""

    def test_no_incidents_table_returns_early(self):
        """Line 105: early return when incidents table does not exist."""
        from openclaw.network_allowlist import _insert_incident_best_effort
        conn = sqlite3.connect(":memory:")
        # No incidents table created - should return without error
        _insert_incident_best_effort(conn=conn, code="TEST", detail_json='{}')
        conn.close()

    def test_incidents_table_present_commits(self):
        """Lines 120-121: inserts and commits when incidents table exists."""
        from openclaw.network_allowlist import _insert_incident_best_effort
        conn = setup_memory_db()
        _insert_incident_best_effort(conn=conn, code="TEST_CODE", detail_json='{"x": 1}', severity="warn")
        count = conn.execute("SELECT COUNT(*) FROM incidents WHERE code='TEST_CODE'").fetchone()[0]
        assert count == 1
        conn.close()

    def test_insert_incident_exception_is_swallowed(self):
        """Exception inside _insert_incident_best_effort is silently caught."""
        from openclaw.network_allowlist import _insert_incident_best_effort
        conn = sqlite3.connect(":memory:")
        # Create a broken incidents table (wrong schema) to provoke an error
        conn.execute("CREATE TABLE incidents (wrong_col TEXT)")
        # Should not raise
        _insert_incident_best_effort(conn=conn, code="FAIL", detail_json='{}')
        conn.close()

    def test_duplicate_open_incident_within_window_is_suppressed(self, monkeypatch):
        from openclaw.network_allowlist import _insert_incident_best_effort

        conn = setup_memory_db()
        monkeypatch.setenv("OPENCLAW_INCIDENT_DEDUPE_WINDOW_SEC", "3600")
        detail_json = '{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}'
        _insert_incident_best_effort(conn=conn, code="SEC_NETWORK_IP_DENIED", detail_json=detail_json)
        _insert_incident_best_effort(conn=conn, code="SEC_NETWORK_IP_DENIED", detail_json=detail_json)
        count = conn.execute("SELECT COUNT(*) FROM incidents WHERE code='SEC_NETWORK_IP_DENIED'").fetchone()[0]
        assert count == 1
        conn.close()

    def test_resolved_incident_does_not_block_new_insert(self, monkeypatch):
        from openclaw.network_allowlist import _insert_incident_best_effort

        conn = setup_memory_db()
        monkeypatch.setenv("OPENCLAW_INCIDENT_DEDUPE_WINDOW_SEC", "3600")
        detail_json = '{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}'
        conn.execute(
            "INSERT INTO incidents VALUES ('i1', '2026-03-06T00:00:00+00:00', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 1)",
            (detail_json,),
        )
        conn.commit()
        _insert_incident_best_effort(conn=conn, code="SEC_NETWORK_IP_DENIED", detail_json=detail_json)
        count = conn.execute("SELECT COUNT(*) FROM incidents WHERE code='SEC_NETWORK_IP_DENIED'").fetchone()[0]
        assert count == 2
        conn.close()


class TestEnforceNetworkSecurityDbPath:
    """Lines 172-174, 180-181: enforce_network_security creates its own connection when conn=None."""

    def test_denied_with_db_path_opens_and_closes_conn(self, tmp_path, monkeypatch):
        """Lines 172-174, 180-181: conn opened from db_path, then closed in finally."""
        db_file = tmp_path / "test_trades.db"
        import sqlite3 as _sqlite3
        setup_conn = _sqlite3.connect(str(db_file))
        setup_conn.execute("""
            CREATE TABLE incidents (
                incident_id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                code TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0
            )
        """)
        setup_conn.commit()
        setup_conn.close()

        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "1.2.3.4")
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)
        with pytest.raises(NetworkSecurityError):
            enforce_network_security(
                whitelist=["192.168.1.0/24"],
                db_path=str(db_file),
            )

    def test_denied_without_db_path_falls_back_to_env_db_path(self, tmp_path, monkeypatch):
        """Lines 172-174: when db_path=None and no conn, uses OPENCLAW_DB_PATH env."""
        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "1.2.3.4")
        monkeypatch.setenv("OPENCLAW_DB_PATH", str(tmp_path / "fallback.db"))
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)
        with pytest.raises(NetworkSecurityError):
            enforce_network_security(
                whitelist=["192.168.1.0/24"],
            )

    def test_denied_with_explicit_conn_does_not_close_it(self, monkeypatch):
        """Lines 176-181: when conn is supplied, it must NOT be closed by enforce_network_security."""
        conn = setup_memory_db()
        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "1.2.3.4")
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)
        try:
            with pytest.raises(NetworkSecurityError):
                enforce_network_security(
                    whitelist=["192.168.1.0/24"],
                    conn=conn,
                )
            # conn should still be usable (not closed)
            count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            assert count >= 0
        finally:
            conn.close()

    def test_denied_incident_payload_is_canonicalized(self, monkeypatch):
        conn = setup_memory_db()
        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "8.8.8.8")
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)
        try:
            with pytest.raises(NetworkSecurityError):
                enforce_network_security(whitelist=["203.0.113.0/28", "192.168.1.0/24"], conn=conn)
        finally:
            monkeypatch.delenv("OPENCLAW_CURRENT_IP", raising=False)
        row = conn.execute("SELECT detail_json FROM incidents WHERE code='SEC_NETWORK_IP_DENIED'").fetchone()
        detail = json.loads(row[0])
        assert detail["allowlist"] == ["192.168.1.0/24", "203.0.113.0/28"]
        assert detail["current_ip"] == "8.8.8.8"
        conn.close()

    def test_inner_exception_swallowed_lines_172_174(self, tmp_path, monkeypatch):
        """Lines 172-174: exception inside inner try block is swallowed."""
        import sqlite3 as _sqlite3
        from unittest.mock import patch

        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "1.2.3.4")
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)

        # Make sqlite3.connect raise to trigger the except Exception: pass at lines 172-174
        with patch("openclaw.network_allowlist.sqlite3.connect", side_effect=OSError("cannot open db")):
            with pytest.raises(NetworkSecurityError, match="SEC_NETWORK_IP_DENIED"):
                enforce_network_security(
                    whitelist=["192.168.1.0/24"],
                    db_path=str(tmp_path / "nowrite.db"),
                )

    def test_conn_close_exception_swallowed_lines_180_181(self, tmp_path, monkeypatch):
        """Lines 180-181: exception during conn.close() in finally is swallowed."""
        from unittest.mock import patch, MagicMock
        import sqlite3 as _sqlite3

        monkeypatch.setenv("OPENCLAW_CURRENT_IP", "1.2.3.4")
        monkeypatch.delenv("OPENCLAW_IP_ALLOWLIST", raising=False)

        mock_conn = MagicMock(spec=_sqlite3.Connection)
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.close.side_effect = OSError("close failed")

        with patch("openclaw.network_allowlist.sqlite3.connect", return_value=mock_conn):
            with pytest.raises(NetworkSecurityError, match="SEC_NETWORK_IP_DENIED"):
                enforce_network_security(
                    whitelist=["192.168.1.0/24"],
                    db_path=str(tmp_path / "test.db"),
                )
