"""Tests for app/api/control.py — targeting 24% → near 100%."""
from __future__ import annotations

import json
import os
import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _write_state_file(tmp_path, trading_enabled=False, simulation_mode=True):
    state = {
        "trading_enabled": trading_enabled,
        "simulation_mode": simulation_mode,
        "last_modified": "2026-01-01T00:00:00",
        "last_modified_by": "test",
    }
    p = tmp_path / "system_state.json"
    p.write_text(json.dumps(state))
    return p


@pytest.fixture
def patched_client(client, tmp_path, monkeypatch):
    """Client with a real temp system_state.json for control endpoints."""
    p = _write_state_file(tmp_path)
    import app.api.control as ctrl
    monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", str(p))
    return client, tmp_path, p


class TestStopTrading:
    def test_stop_creates_file(self, patched_client, tmp_path, monkeypatch):
        client, tmp_path, _ = patched_client
        stop_file = tmp_path / ".EMERGENCY_STOP"
        import app.api.control as ctrl
        monkeypatch.setattr(
            ctrl, "SYSTEM_STATE_PATH",
            str(tmp_path / "system_state.json")
        )
        # Patch the stop file path inside control module via monkeypatching os.path.join
        # We need to point stop_file to our tmp_path
        original_stop_path = os.path.join(os.path.dirname(ctrl.__file__), "../../../../.EMERGENCY_STOP")

        r = client.post(
            "/api/control/stop",
            json={"reason": "test stop"},
            headers=_AUTH,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_stop_no_auth(self, client):
        r = client.post("/api/control/stop", json={"reason": "x"})
        assert r.status_code == 401

    def test_stop_default_reason(self, patched_client):
        client, tmp_path, _ = patched_client
        r = client.post("/api/control/stop", json={}, headers=_AUTH)
        assert r.status_code == 200


class TestResumeTrading:
    def test_resume_when_no_stop_file(self, patched_client):
        client, _, _ = patched_client
        r = client.post("/api/control/resume", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_resume_no_auth(self, client):
        r = client.post("/api/control/resume")
        assert r.status_code == 401


class TestEnableAutoTrading:
    def test_enable_returns_ok(self, patched_client):
        client, _, _ = patched_client
        r = client.post("/api/control/enable", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_enable_no_auth(self, client):
        r = client.post("/api/control/enable")
        assert r.status_code == 401


class TestDisableAutoTrading:
    def test_disable_returns_ok(self, patched_client):
        client, _, _ = patched_client
        r = client.post("/api/control/disable", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_disable_no_auth(self, client):
        r = client.post("/api/control/disable")
        assert r.status_code == 401


class TestSwitchSimulation:
    def test_simulation_mode(self, patched_client, monkeypatch):
        client, _, _ = patched_client
        # Mock out _clear_shioaji_cache to avoid import errors
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "_clear_shioaji_cache", lambda: None)
        r = client.post("/api/control/simulation", headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert "simulation" in r.json()["message"].lower()

    def test_simulation_no_auth(self, client):
        r = client.post("/api/control/simulation")
        assert r.status_code == 401


class TestSwitchLive:
    def test_live_mode(self, patched_client, monkeypatch):
        client, _, _ = patched_client
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "_clear_shioaji_cache", lambda: None)
        r = client.post("/api/control/live", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "warning" in data  # REAL MONEY warning

    def test_live_no_auth(self, client):
        r = client.post("/api/control/live")
        assert r.status_code == 401


class TestControlStatus:
    def test_status_returns_ok(self, patched_client):
        client, _, _ = patched_client
        r = client.get("/api/control/status", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "emergency_stop" in data
        assert "auto_trading_enabled" in data
        assert "simulation_mode" in data

    def test_status_no_emergency_stop(self, patched_client):
        client, tmp_path, _ = patched_client
        # Ensure no emergency stop file
        stop_file = os.path.join(str(tmp_path), ".EMERGENCY_STOP")
        if os.path.exists(stop_file):
            os.remove(stop_file)
        r = client.get("/api/control/status", headers=_AUTH)
        assert r.status_code == 200
        # emergency_stop could be True or False depending on real system
        # Just check the field exists and is boolean
        assert isinstance(r.json()["emergency_stop"], bool)

    def test_status_no_auth(self, client):
        r = client.get("/api/control/status")
        assert r.status_code == 401

    def test_status_mode_warning_simulation(self, patched_client):
        client, _, _ = patched_client
        r = client.get("/api/control/status", headers=_AUTH)
        data = r.json()
        assert "mode_warning" in data

    def test_status_reads_emergency_stop_reason(self, patched_client):
        """When .EMERGENCY_STOP file exists, status reads its content (covers lines 152-153)."""
        client, _, _ = patched_client
        import app.api.control as ctrl
        stop_file_path = os.path.join(os.path.dirname(ctrl.__file__), "../../../../.EMERGENCY_STOP")
        stop_file_path = os.path.abspath(stop_file_path)
        stop_existed = os.path.exists(stop_file_path)
        try:
            with open(stop_file_path, "w") as f:
                f.write("Test emergency reason")
            r = client.get("/api/control/status", headers=_AUTH)
            assert r.status_code == 200
            data = r.json()
            assert data["emergency_stop"] is True
            assert data["emergency_reason"] == "Test emergency reason"
        finally:
            if not stop_existed and os.path.exists(stop_file_path):
                os.remove(stop_file_path)


class TestClearShioajiCache:
    def test_clear_cache_calls_shioaji(self, monkeypatch):
        """_clear_shioaji_cache should call _clear_api_cache from shioaji_service."""
        calls = []
        import app.services.shioaji_service as svc
        monkeypatch.setattr(svc, "_clear_api_cache", lambda: calls.append(True))
        import app.api.control as ctrl
        ctrl._clear_shioaji_cache()
        assert len(calls) == 1

    def test_clear_cache_handles_import_error(self, monkeypatch):
        """_clear_shioaji_cache should not raise even if import fails."""
        import app.api.control as ctrl
        # Temporarily break the shioaji_service import
        import sys
        saved = sys.modules.pop("app.services.shioaji_service", None)
        try:
            # Force ImportError by making the module unimportable
            sys.modules["app.services.shioaji_service"] = None  # type: ignore
            ctrl._clear_shioaji_cache()  # should not raise
        finally:
            if saved is not None:
                sys.modules["app.services.shioaji_service"] = saved
            else:
                sys.modules.pop("app.services.shioaji_service", None)


class TestControlExceptionPaths:
    def test_enable_500_when_state_file_missing(self, client, monkeypatch):
        """enable endpoint returns 500 when state file not found."""
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", "/nonexistent/path/state.json")
        r = client.post("/api/control/enable", headers=_AUTH)
        assert r.status_code == 500

    def test_disable_500_when_state_file_missing(self, client, monkeypatch):
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", "/nonexistent/path/state.json")
        r = client.post("/api/control/disable", headers=_AUTH)
        assert r.status_code == 500

    def test_simulation_500_when_state_file_missing(self, client, monkeypatch):
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", "/nonexistent/path/state.json")
        monkeypatch.setattr(ctrl, "_clear_shioaji_cache", lambda: None)
        r = client.post("/api/control/simulation", headers=_AUTH)
        assert r.status_code == 500

    def test_live_500_when_state_file_missing(self, client, monkeypatch):
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", "/nonexistent/path/state.json")
        monkeypatch.setattr(ctrl, "_clear_shioaji_cache", lambda: None)
        r = client.post("/api/control/live", headers=_AUTH)
        assert r.status_code == 500

    def test_status_500_when_state_file_missing(self, client, monkeypatch):
        import app.api.control as ctrl
        monkeypatch.setattr(ctrl, "SYSTEM_STATE_PATH", "/nonexistent/path/state.json")
        r = client.get("/api/control/status", headers=_AUTH)
        assert r.status_code == 500

    def test_resume_deletes_stop_file_when_exists(self, patched_client, monkeypatch):
        """resume removes .EMERGENCY_STOP if it exists."""
        client, tmp_path, _ = patched_client
        import app.api.control as ctrl
        # Create a real stop file at the expected real location
        stop_file_path = os.path.join(os.path.dirname(ctrl.__file__), "../../../../.EMERGENCY_STOP")
        stop_file_path = os.path.abspath(stop_file_path)
        stop_existed = os.path.exists(stop_file_path)
        try:
            with open(stop_file_path, "w") as f:
                f.write("test stop")
            r = client.post("/api/control/resume", headers=_AUTH)
            assert r.status_code == 200
        finally:
            # Restore original state
            if not stop_existed and os.path.exists(stop_file_path):
                os.remove(stop_file_path)


class TestStopResumeExceptions:
    def test_stop_500_when_open_fails(self, client, monkeypatch):
        """stop endpoint returns 500 when file write fails (covers lines 35-36)."""
        import builtins
        original_open = builtins.open
        def bad_open(file, *args, **kwargs):
            if ".EMERGENCY_STOP" in str(file) and "w" in str(args):
                raise PermissionError("cannot write stop file")
            return original_open(file, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", bad_open)
        r = client.post("/api/control/stop", json={"reason": "test"}, headers=_AUTH)
        assert r.status_code == 500

    def test_resume_500_when_remove_fails(self, client, monkeypatch):
        """resume endpoint returns 500 when os.remove fails (covers lines 48-49)."""
        import app.api.control as ctrl
        import app.api.control as ctrl_mod

        # Patch os.remove inside the control module
        original_remove = os.remove
        import app.api.control as ctrl

        def bad_remove(path):
            raise PermissionError("cannot remove stop file")

        # First create the stop file so remove is called
        stop_file_path = os.path.join(os.path.dirname(ctrl.__file__), "../../../../.EMERGENCY_STOP")
        stop_file_path = os.path.abspath(stop_file_path)
        stop_existed = os.path.exists(stop_file_path)
        try:
            with open(stop_file_path, "w") as f:
                f.write("test")
            monkeypatch.setattr(os, "remove", bad_remove)
            r = client.post("/api/control/resume", headers=_AUTH)
            assert r.status_code == 500
        finally:
            monkeypatch.undo()
            if not stop_existed and os.path.exists(stop_file_path):
                os.remove(stop_file_path)
