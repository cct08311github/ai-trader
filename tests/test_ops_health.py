"""Tests for ops_health: PM2 liveness, alert thresholds, Telegram alerts."""

import json
import sqlite3
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from openclaw.ops_health import (
    get_pm2_processes,
    load_alert_thresholds,
    check_resource_alerts,
    send_ops_alerts,
    collect_ops_health_summary,
    _CRITICAL_SERVICES,
    _DEFAULT_THRESHOLDS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _make_pm2_json(processes):
    """Build PM2 jlist JSON from a list of (name, status, memory, restarts, uptime_ms) tuples."""
    import time
    result = []
    for name, status, mem_bytes, restarts, uptime_ms in processes:
        result.append({
            "name": name,
            "pid": 1234,
            "pm2_env": {
                "status": status,
                "restart_time": restarts,
                "pm_uptime": int(time.time() * 1000) - uptime_ms,
            },
            "monit": {"memory": mem_bytes},
        })
    return json.dumps(result)


# ── get_pm2_processes ─────────────────────────────────────────────────────────

class TestGetPm2Processes:
    def test_all_online(self):
        pm2_json = _make_pm2_json([
            ("ai-trader-api", "online", 100_000_000, 0, 60_000),
            ("ai-trader-watcher", "online", 50_000_000, 2, 120_000),
        ])
        with patch("subprocess.check_output", return_value=pm2_json):
            result = get_pm2_processes()

        assert result["health"]["total"] == 2
        assert result["health"]["online"] == 2
        assert result["health"]["errored"] == 0
        assert result["critical_down"] == []
        assert result["processes"]["ai-trader-api"]["status"] == "online"
        assert result["processes"]["ai-trader-api"]["memory_mb"] == pytest.approx(95.4, abs=0.1)

    def test_critical_service_down(self):
        pm2_json = _make_pm2_json([
            ("ai-trader-api", "errored", 0, 5, 0),
            ("ai-trader-watcher", "online", 50_000_000, 0, 60_000),
        ])
        with patch("subprocess.check_output", return_value=pm2_json):
            result = get_pm2_processes()

        assert result["health"]["errored"] == 1
        assert "ai-trader-api" in result["critical_down"]
        assert result["processes"]["ai-trader-api"]["restart_count"] == 5

    def test_critical_service_missing(self):
        pm2_json = _make_pm2_json([
            ("some-other-service", "online", 10_000_000, 0, 30_000),
        ])
        with patch("subprocess.check_output", return_value=pm2_json):
            result = get_pm2_processes()

        assert set(result["critical_down"]) == _CRITICAL_SERVICES

    def test_subprocess_failure_returns_empty(self):
        with patch("subprocess.check_output", side_effect=subprocess.TimeoutExpired("pm2", 10)):
            result = get_pm2_processes()

        assert result["processes"] == {}
        assert result["health"]["total"] == 0
        assert result["critical_down"] == []

    def test_invalid_json_returns_empty(self):
        with patch("subprocess.check_output", return_value="not json"):
            result = get_pm2_processes()

        assert result["processes"] == {}


# ── load_alert_thresholds ─────────────────────────────────────────────────────

class TestLoadAlertThresholds:
    def test_defaults_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "openclaw.ops_health.get_repo_root",
            lambda: tmp_path,
        )
        thresholds = load_alert_thresholds()
        assert thresholds["cpu_percent_warn"] == 80
        assert thresholds["cpu_percent_critical"] == 95

    def test_override_from_config(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "alert_policy.json").write_text(json.dumps({
            "cpu_percent_warn": 70,
        }))
        with patch("openclaw.ops_health.get_repo_root", return_value=tmp_path):
            thresholds = load_alert_thresholds()
        assert thresholds["cpu_percent_warn"] == 70
        assert thresholds["cpu_percent_critical"] == 95  # unchanged default


# ── check_resource_alerts ─────────────────────────────────────────────────────

class TestCheckResourceAlerts:
    def test_no_alerts_when_healthy(self):
        summary = {
            "pm2": {
                "critical_down": [],
                "processes": {
                    "ai-trader-api": {"status": "online"},
                    "ai-trader-watcher": {"status": "online"},
                },
            }
        }
        alerts = check_resource_alerts(summary, _DEFAULT_THRESHOLDS)
        assert alerts == []

    def test_critical_alert_for_down_service(self):
        summary = {
            "pm2": {
                "critical_down": ["ai-trader-api"],
                "processes": {},
            }
        }
        alerts = check_resource_alerts(summary, _DEFAULT_THRESHOLDS)
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"
        assert "ai-trader-api" in alerts[0]["message"]

    def test_critical_alert_for_errored_process(self):
        summary = {
            "pm2": {
                "critical_down": [],
                "processes": {
                    "ai-trader-api": {"status": "errored", "restart_count": 12},
                },
            }
        }
        alerts = check_resource_alerts(summary, _DEFAULT_THRESHOLDS)
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"
        assert "errored" in alerts[0]["message"]
        assert "12" in alerts[0]["message"]

    def test_multiple_alerts(self):
        summary = {
            "pm2": {
                "critical_down": ["ai-trader-api", "ai-trader-watcher"],
                "processes": {
                    "other": {"status": "errored", "restart_count": 3},
                },
            }
        }
        alerts = check_resource_alerts(summary, _DEFAULT_THRESHOLDS)
        assert len(alerts) == 3  # 2 critical_down + 1 errored


# ── send_ops_alerts ───────────────────────────────────────────────────────────

class TestSendOpsAlerts:
    def test_no_alerts_does_nothing(self):
        send_ops_alerts([])  # should not raise

    def test_warning_only_does_not_send(self):
        mock_tg = MagicMock()
        with patch.dict("sys.modules", {"openclaw.tg_notify": mock_tg}):
            alerts = [{"severity": "warning", "source": "test", "message": "warn"}]
            send_ops_alerts(alerts)
        mock_tg.send_message.assert_not_called()

    def test_critical_alert_sends_telegram(self):
        mock_tg = MagicMock()
        with patch.dict("sys.modules", {"openclaw.tg_notify": mock_tg}):
            alerts = [
                {"severity": "critical", "source": "pm2", "message": "api is down"},
                {"severity": "warning", "source": "test", "message": "warn"},
            ]
            send_ops_alerts(alerts)
        mock_tg.send_message.assert_called_once()
        msg = mock_tg.send_message.call_args[0][0]
        assert "api is down" in msg
        assert "Ops Alert" in msg

    def test_send_failure_does_not_raise(self):
        mock_tg = MagicMock()
        mock_tg.send_message.side_effect = RuntimeError("network error")
        with patch.dict("sys.modules", {"openclaw.tg_notify": mock_tg}):
            # Should not raise
            send_ops_alerts([{"severity": "critical", "source": "test", "message": "boom"}])


# ── collect_ops_health_summary (PM2 integration) ─────────────────────────────

class TestCollectOpsHealthSummaryPm2:
    def test_includes_pm2_metrics(self, mem_db):
        pm2_json = _make_pm2_json([
            ("ai-trader-api", "online", 100_000_000, 0, 60_000),
            ("ai-trader-watcher", "online", 50_000_000, 0, 60_000),
        ])
        with (
            patch("subprocess.check_output", return_value=pm2_json),
            patch("openclaw.ops_health.system_state_path_from_env", return_value="/nonexistent"),
            patch("openclaw.ops_health.get_quarantine_status", return_value={"active_count": 0}),
            patch("openclaw.ops_health.send_ops_alerts"),
        ):
            summary = collect_ops_health_summary(mem_db)

        assert "pm2" in summary
        assert summary["metrics"]["pm2_errored"] == 0
        assert summary["metrics"]["pm2_critical_down"] == 0
        assert summary["overall"] == "ok"

    def test_critical_overall_when_pm2_service_down(self, mem_db):
        pm2_json = _make_pm2_json([
            ("ai-trader-api", "errored", 0, 10, 0),
        ])
        with (
            patch("subprocess.check_output", return_value=pm2_json),
            patch("openclaw.ops_health.system_state_path_from_env", return_value="/nonexistent"),
            patch("openclaw.ops_health.get_quarantine_status", return_value={"active_count": 0}),
            patch("openclaw.ops_health.send_ops_alerts"),
        ):
            summary = collect_ops_health_summary(mem_db)

        assert summary["overall"] == "critical"
        assert summary["metrics"]["pm2_errored"] == 1
        assert summary["metrics"]["pm2_critical_down"] > 0

    def test_alerts_sent_on_critical(self, mem_db):
        pm2_json = _make_pm2_json([
            ("ai-trader-api", "errored", 0, 5, 0),
        ])
        with (
            patch("subprocess.check_output", return_value=pm2_json),
            patch("openclaw.ops_health.system_state_path_from_env", return_value="/nonexistent"),
            patch("openclaw.ops_health.get_quarantine_status", return_value={"active_count": 0}),
            patch("openclaw.ops_health.send_ops_alerts") as mock_send,
        ):
            summary = collect_ops_health_summary(mem_db)

        mock_send.assert_called_once()
        alerts = mock_send.call_args[0][0]
        assert any(a["severity"] == "critical" for a in alerts)
