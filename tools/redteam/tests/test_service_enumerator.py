"""Tests for service_enumerator module."""
import json
from unittest.mock import patch, MagicMock

import pytest

from tools.redteam.service_enumerator import (
    enumerate_pm2,
    enumerate_nginx,
    enumerate_tailscale,
    enumerate_all,
)


class TestEnumeratePm2:
    @patch("tools.redteam.service_enumerator._run")
    def test_parses_pm2_jlist(self, mock_run):
        mock_run.return_value = json.dumps([
            {
                "name": "ai-trader-web",
                "pid": 1234,
                "pm_id": 0,
                "pm2_env": {
                    "status": "online",
                    "exec_interpreter": "node",
                },
            },
            {
                "name": "ai-trader-api",
                "pid": 5678,
                "pm_id": 1,
                "pm2_env": {
                    "status": "stopped",
                    "exec_interpreter": "python3",
                },
            },
        ])

        services = enumerate_pm2()
        assert len(services) == 2
        assert services[0].name == "ai-trader-web"
        assert services[0].pid == 1234
        assert services[0].status == "online"
        assert services[1].status == "stopped"

    @patch("tools.redteam.service_enumerator._run")
    def test_empty_on_failure(self, mock_run):
        mock_run.return_value = ""
        assert enumerate_pm2() == []

    @patch("tools.redteam.service_enumerator._run")
    def test_empty_on_invalid_json(self, mock_run):
        mock_run.return_value = "not json"
        assert enumerate_pm2() == []


class TestEnumerateNginx:
    def test_empty_on_missing_dir(self):
        assert enumerate_nginx("/nonexistent/path/") == []


class TestEnumerateTailscale:
    @patch("tools.redteam.service_enumerator._run")
    def test_parses_tailscale_status(self, mock_run):
        mock_run.return_value = json.dumps({
            "BackendState": "Running",
            "Self": {
                "HostName": "my-server",
                "TailscaleIPs": ["100.64.0.1"],
                "OS": "linux",
            },
        })

        services = enumerate_tailscale()
        assert len(services) == 1
        assert "my-server" in services[0].name
        assert services[0].status == "online"

    @patch("tools.redteam.service_enumerator._run")
    def test_empty_on_failure(self, mock_run):
        mock_run.return_value = ""
        assert enumerate_tailscale() == []


class TestEnumerateAll:
    @patch("tools.redteam.service_enumerator.enumerate_tailscale")
    @patch("tools.redteam.service_enumerator.enumerate_nginx")
    @patch("tools.redteam.service_enumerator.enumerate_pm2")
    def test_combines_all_sources(self, mock_pm2, mock_nginx, mock_ts):
        from tools.redteam.finding_scorer import ServiceInfo

        mock_pm2.return_value = [ServiceInfo(name="pm2-svc")]
        mock_nginx.return_value = [ServiceInfo(name="nginx-svc")]
        mock_ts.return_value = [ServiceInfo(name="ts-svc")]

        result = enumerate_all()
        assert len(result) == 3
        names = {s.name for s in result}
        assert names == {"pm2-svc", "nginx-svc", "ts-svc"}
