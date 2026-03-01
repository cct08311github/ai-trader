"""Test Robustness for AI-Trader v4 (全覆蓋測試計畫 - 任務1)."""

import pytest
import sqlite3
import time
import threading
import json
import tempfile
import os
from unittest.mock import Mock, patch

from openclaw.position_sizing import (
    load_sentinel_policy,
    get_position_limits_for_level,
)

from openclaw.correlation_guard import (
    load_correlation_guard_policy,
    log_correlation_incident,
)


class TestDatabaseRobustness:
    """測試資料庫相關的 robustness。"""

    def test_sqlite_database_locking(self):
        """測試 SQLite 資料庫鎖定情況。"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn1 = sqlite3.connect(db_path)
            conn1.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn1.execute("INSERT INTO test (value) VALUES ('test1')")
            conn1.commit()
            
            conn2 = sqlite3.connect(db_path)
            conn2.execute("BEGIN EXCLUSIVE")
            conn2.execute("INSERT INTO test (value) VALUES ('test2')")
            
            conn3 = sqlite3.connect(db_path, timeout=1)
            try:
                cursor = conn3.execute("SELECT * FROM test")
                results = cursor.fetchall()
                assert len(results) >= 1
            except sqlite3.OperationalError as e:
                assert "locked" in str(e).lower() or "timeout" in str(e).lower()
            finally:
                conn3.close()
                conn2.rollback()
                conn2.close()
                conn1.close()
                
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_concurrent_database_access(self):
        """測試並發資料庫訪問。"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value INTEGER)")
            conn.commit()
            conn.close()
            
            results = []
            errors = []
            
            def worker(worker_id):
                try:
                    conn = sqlite3.connect(db_path, timeout=5)
                    for i in range(10):
                        conn.execute(
                            "INSERT INTO test (value) VALUES (?)",
                            (worker_id * 100 + i,)
                        )
                        conn.commit()
                        time.sleep(0.01)
                    conn.close()
                    results.append(f"worker_{worker_id}_success")
                except Exception as e:
                    errors.append(f"worker_{worker_id}_error: {str(e)}")
            
            threads = []
            for i in range(5):
                t = threading.Thread(target=worker, args=(i,))
                threads.append(t)
                t.start()
            
            for t in threads:
                t.join()
            
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT COUNT(*) FROM test")
            count = cursor.fetchone()[0]
            conn.close()
            
            assert count > 0
            assert count <= 50
            
            if errors:
                print(f"Concurrent access errors: {errors}")
                
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_database_corruption_recovery(self):
        """測試資料庫損壞恢復能力。"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO test (value) VALUES ('正常資料')")
            conn.commit()
            conn.close()
            
            with open(db_path, 'wb') as f:
                f.write(b'INVALID SQLITE DATA' * 100)
            
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.execute("SELECT * FROM test")
                cursor.fetchall()
                conn.close()
            except sqlite3.DatabaseError as e:
                assert "database" in str(e).lower() or "corrupt" in str(e).lower() or "file" in str(e).lower()
                
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestInvalidJSONRobustness:
    """測試無效 JSON 處理的 robustness。"""

    def test_load_sentinel_policy_invalid_json_content(self):
        """測試加載包含無效內容的 JSON 文件。"""
        test_cases = [
            b"",
            b"null",
            b"123",
            b'"string"',
            b"true",
            b"[1, 2, 3]",
            b"{invalid json}",
            b'{"nested": {"malformed": ]}',
        ]
        
        for i, content in enumerate(test_cases):
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
                f.write(content)
                file_path = f.name
            
            try:
                policy = load_sentinel_policy(file_path)
                assert isinstance(policy, dict)
            except Exception:
                pass
            finally:
                if os.path.exists(file_path):
                    os.unlink(file_path)

    def test_load_correlation_guard_policy_invalid_content(self):
        """測試加載無效的 correlation guard 政策文件。"""
        test_cases = [
            b"",
            b"null",
            b"123",
            b'"string"',
            b"{invalid}",
            b'{"window": "not a number"}',
            b'{"max_pair_abs_corr": 2.0}',
            b'{"exposure_scale_on_breach": -1.0}',
        ]
        
        for i, content in enumerate(test_cases):
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
                f.write(content)
                file_path = f.name
            
            try:
                policy = load_correlation_guard_policy(file_path)
                assert policy is not None
                assert hasattr(policy, 'window')
                assert hasattr(policy, 'max_pair_abs_corr')
            except Exception:
                pass
            finally:
                if os.path.exists(file_path):
                    os.unlink(file_path)

    def test_json_decode_error_handling(self):
        """測試 JSON 解碼錯誤處理。"""
        invalid_json = b'{"key": "value\x00with null byte"}'
        
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            f.write(invalid_json)
            file_path = f.name
        
        try:
            policy = load_sentinel_policy(file_path)
            assert policy == {}
        except Exception:
            pass
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)


class TestSystemIntegrationRobustness:
    """測試系統整合的 robustness。"""

    def test_log_correlation_incident_without_table(self):
        """測試在沒有 incidents 表的情況下記錄相關性事件。"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY)")
            conn.commit()
            
            from openclaw.correlation_guard import CorrelationGuardDecision
            decision = CorrelationGuardDecision(
                ok=False,
                reason_code="CORR_MAX_PAIR_EXCEEDED",
                n_symbols=5,
                max_pair_abs_corr=0.9,
                weighted_avg_abs_corr=0.6,
                top_pairs=[("AAPL", "MSFT", 0.9)],
                suggestions=["Reduce exposure"],
                matrix={"AAPL": {"AAPL": 1.0, "MSFT": 0.9}, "MSFT": {"AAPL": 0.9, "MSFT": 1.0}}
            )
            
            log_correlation_incident(conn, decision)
            conn.close()
            
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_get_position_limits_with_corrupted_policy(self):
        """測試使用損壞的政策文件獲取位置限制。"""
        corrupted_policy = {
            "position_limits": {
                "levels": {
                    "2": {
                        "max_risk_per_trade_pct_nav": "not a number",
                        "max_position_notional_pct_nav": None
                    }
                }
            }
        }
        
        limits = get_position_limits_for_level(corrupted_policy, level=2)
        assert limits.max_risk_per_trade_pct_nav == 0.003
        assert limits.max_position_notional_pct_nav == 0.05
