import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from openclaw.system_switch import check_system_switch


class _Handler(BaseHTTPRequestHandler):
    payload = {"trading_enabled": False}

    def do_GET(self):
        if self.path != "/api/control/status":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # silence test output
        return


def _start_server(payload):
    _Handler.payload = payload
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    host, port = httpd.server_address
    return httpd, f"http://{host}:{port}/api/control/status"


def test_api_fallback_enabled_when_file_missing(tmp_path):
    httpd, url = _start_server({"trading_enabled": True})
    try:
        allowed, reason = check_system_switch(str(tmp_path / "missing.json"), api_url=url, api_timeout_s=1.0)
        assert allowed is True
        assert reason is None
    finally:
        httpd.shutdown()


def test_api_fallback_disabled_when_file_missing(tmp_path):
    httpd, url = _start_server({"trading_enabled": False})
    try:
        allowed, reason = check_system_switch(str(tmp_path / "missing.json"), api_url=url, api_timeout_s=1.0)
        assert allowed is False
        assert reason == "Auto-trading is disabled (master switch OFF)"
    finally:
        httpd.shutdown()


def test_api_fallback_unavailable_defaults_disabled(tmp_path):
    # point to unused port to force connection error
    url = "http://127.0.0.1:9/api/control/status"
    allowed, reason = check_system_switch(str(tmp_path / "missing.json"), api_url=url, api_timeout_s=0.2)
    assert allowed is False
    assert "default: disabled" in reason
