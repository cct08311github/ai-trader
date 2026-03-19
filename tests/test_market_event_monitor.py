"""tests/test_market_event_monitor.py — market_event_monitor 單元測試 [Issue #197]"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── 讓 import 找得到 tools/ ─────────────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

import market_event_monitor as mon


# ── check_alerts 閾值邏輯 ────────────────────────────────────────────────────

class TestCheckAlerts:
    """驗證各種閾值邊界條件。"""

    def _run(self, us_data: dict, holding_changes: dict | None = None) -> list:
        return mon.check_alerts(us_data, holding_changes or {})

    # --- 正常狀況（無警報）---

    def test_no_alerts_when_all_below_threshold(self):
        us = {"S&P 500": 1.5, "Nasdaq": -2.0, "Dow": 0.8, "VIX": 15.0}
        assert self._run(us) == []

    def test_none_values_do_not_trigger(self):
        us = {"S&P 500": None, "Nasdaq": None, "Dow": None, "VIX": None}
        assert self._run(us) == []

    # --- 美股大盤閾值 ---

    def test_sp500_positive_spike_triggers(self):
        us = {"S&P 500": 3.5, "Nasdaq": 1.0, "Dow": 0.5, "VIX": 5.0}
        alerts = self._run(us)
        types = [a["type"] for a in alerts]
        assert "US_MARKET" in types
        assert any(a["label"] == "S&P 500" for a in alerts)

    def test_nasdaq_negative_crash_triggers(self):
        us = {"S&P 500": -1.0, "Nasdaq": -4.2, "Dow": -0.5, "VIX": 10.0}
        alerts = self._run(us)
        assert any(a["label"] == "Nasdaq" and a["change_pct"] == -4.2 for a in alerts)

    def test_exact_threshold_triggers(self):
        us = {"S&P 500": 3.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": 0.0}
        alerts = self._run(us)
        assert any(a["label"] == "S&P 500" for a in alerts)

    def test_just_below_threshold_no_alert(self):
        us = {"S&P 500": 2.99, "Nasdaq": -2.99, "Dow": 0.0, "VIX": 19.9}
        assert self._run(us) == []

    # --- VIX 閾值 ---

    def test_vix_spike_triggers(self):
        us = {"S&P 500": 1.0, "Nasdaq": 0.5, "Dow": 0.0, "VIX": 25.0}
        alerts = self._run(us)
        assert any(a["type"] == "VIX" and a["label"] == "VIX" for a in alerts)

    def test_vix_drop_triggers(self):
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": -22.0}
        alerts = self._run(us)
        assert any(a["type"] == "VIX" for a in alerts)

    # --- 持倉閾值 ---

    def test_holding_surge_triggers(self):
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": 0.0}
        alerts = self._run(us, holding_changes={"2330": 6.1})
        assert any(a["type"] == "HOLDING" and a["label"] == "2330" for a in alerts)

    def test_holding_crash_triggers(self):
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": 0.0}
        alerts = self._run(us, holding_changes={"2317": -5.5})
        assert any(a["label"] == "2317" and a["change_pct"] == -5.5 for a in alerts)

    def test_holding_below_threshold_no_alert(self):
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": 0.0}
        assert self._run(us, holding_changes={"2330": 4.9}) == []

    def test_holding_none_value_skipped(self):
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "Dow": 0.0, "VIX": 0.0}
        assert self._run(us, holding_changes={"2330": None}) == []

    def test_multiple_alerts_all_captured(self):
        us = {"S&P 500": -3.5, "Nasdaq": -4.0, "Dow": -1.0, "VIX": 30.0}
        alerts = self._run(us, holding_changes={"2330": -6.0, "2317": 1.0})
        labels = [a["label"] for a in alerts]
        assert "S&P 500" in labels
        assert "Nasdaq" in labels
        assert "VIX" in labels
        assert "2330" in labels
        assert "2317" not in labels  # 1.0 < 5.0 閾值


# ── build_alert_message 格式驗證 ─────────────────────────────────────────────

class TestBuildAlertMessage:
    def test_message_contains_alert_label(self):
        alerts = [{"type": "US_MARKET", "label": "S&P 500", "change_pct": -4.0, "threshold": 3.0}]
        us = {"S&P 500": -4.0, "Nasdaq": 1.0, "VIX": 5.0}
        msg = mon.build_alert_message(alerts, us)
        assert "S&P 500" in msg
        assert "4.00" in msg

    def test_message_contains_vix_snapshot(self):
        alerts = [{"type": "VIX", "label": "VIX", "change_pct": 25.0, "threshold": 20.0}]
        us = {"S&P 500": 1.0, "Nasdaq": 0.5, "VIX": 25.0}
        msg = mon.build_alert_message(alerts, us)
        assert "VIX" in msg
        assert "PM Review" in msg

    def test_message_contains_holding_alert(self):
        alerts = [{"type": "HOLDING", "label": "2330", "change_pct": 7.2, "threshold": 5.0}]
        us = {"S&P 500": 0.0, "Nasdaq": 0.0, "VIX": 0.0}
        msg = mon.build_alert_message(alerts, us)
        assert "2330" in msg


# ── main() 整合流程（mock 外部依賴）────────────────────────────────────────────

class TestMainIntegration:
    def _mock_us(self):
        return {"S&P 500": 1.0, "Nasdaq": 0.5, "Dow": 0.3, "VIX": 5.0}

    def _mock_us_alert(self):
        return {"S&P 500": -4.5, "Nasdaq": -5.0, "Dow": -3.5, "VIX": 28.0}

    def test_no_alerts_returns_0(self):
        with patch.object(mon, "fetch_us_market", return_value=self._mock_us()), \
             patch.object(mon, "fetch_holdings", return_value=[]), \
             patch.object(mon, "fetch_holding_changes", return_value={}):
            rc = mon.main(dry_run=True)
        assert rc == 0

    def test_alerts_returns_1(self):
        with patch.object(mon, "fetch_us_market", return_value=self._mock_us_alert()), \
             patch.object(mon, "fetch_holdings", return_value=[]), \
             patch.object(mon, "fetch_holding_changes", return_value={}):
            rc = mon.main(dry_run=True)
        assert rc == 1

    def test_dry_run_skips_telegram(self):
        with patch.object(mon, "fetch_us_market", return_value=self._mock_us_alert()), \
             patch.object(mon, "fetch_holdings", return_value=[]), \
             patch.object(mon, "fetch_holding_changes", return_value={}), \
             patch.object(mon, "send_telegram") as mock_tg, \
             patch.object(mon, "trigger_pm_review") as mock_pm:
            mon.main(dry_run=True)
        mock_tg.assert_not_called()
        mock_pm.assert_not_called()

    def test_alerts_trigger_telegram_and_pm(self):
        with patch.object(mon, "fetch_us_market", return_value=self._mock_us_alert()), \
             patch.object(mon, "fetch_holdings", return_value=[]), \
             patch.object(mon, "fetch_holding_changes", return_value={}), \
             patch.object(mon, "send_telegram", return_value=True) as mock_tg, \
             patch.object(mon, "trigger_pm_review", return_value=True) as mock_pm, \
             patch.dict(os.environ, {"AUTH_TOKEN": "test-token"}):
            # Reload to pick up AUTH_TOKEN
            mon.AUTH_TOKEN = "test-token"
            rc = mon.main(dry_run=False)
        assert rc == 1
        mock_tg.assert_called_once()
        mock_pm.assert_called_once()

    def test_missing_yfinance_returns_2_without_import_exit(self):
        with patch.object(mon, "yf", None):
            rc = mon.main(dry_run=True)
        assert rc == 2


# ── send_telegram 網路失敗容錯 ───────────────────────────────────────────────

class TestSendTelegram:
    def test_returns_false_on_network_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")), \
             patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake-token"}):
            mon.TELEGRAM_BOT_TOKEN = "fake-token"
            result = mon.send_telegram("test")
        assert result is False

    def test_returns_false_when_no_token(self):
        original = mon.TELEGRAM_BOT_TOKEN
        mon.TELEGRAM_BOT_TOKEN = ""
        try:
            result = mon.send_telegram("test")
        finally:
            mon.TELEGRAM_BOT_TOKEN = original
        assert result is False
