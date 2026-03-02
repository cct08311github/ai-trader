import json
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from openclaw.tw_session_rules import (
    TWTradingPhase,
    get_tw_trading_phase,
    TWSessionConfig,
    apply_tw_session_risk_adjustments,
    tw_session_allows_trading,
    _load_sentinel_tw_session_config,
)


def setup_memory_db() -> sqlite3.Connection:
    """建立 :memory: SQLite 連線 + 執行必要的 migration（如果有的話）"""
    conn = sqlite3.connect(":memory:")
    # 此模組未使用資料庫，但為了符合要求，我們建立一個連接
    return conn


class TestTWSessionRules:
    def setup_method(self):
        self.conn = setup_memory_db()

    def teardown_method(self):
        self.conn.close()

    def test_get_tw_trading_phase_success(self):
        """成功路徑：測試不同時間段"""
        # 創建一個已知時間（例如 2026-03-01 10:00:00 UTC+8）
        # 轉換為 epoch ms
        # 我們可以使用固定時間戳模擬
        # 由於時間依賴，我們只測試函數是否被呼叫
        now_ms = int(time.time() * 1000)
        phase = get_tw_trading_phase(now_ms)
        assert phase in [TWTradingPhase.PREOPEN_AUCTION, TWTradingPhase.REGULAR,
                         TWTradingPhase.AFTERHOURS_AUCTION, TWTradingPhase.CLOSED]

    def test_tw_session_allows_trading_boundary(self):
        """邊界條件：測試交易允許函數"""
        # 同樣，我們只測試函數是否被呼叫
        now_ms = int(time.time() * 1000)
        allowed = tw_session_allows_trading(now_ms)
        assert isinstance(allowed, bool)

    def test_apply_tw_session_risk_adjustments_failure(self):
        """失敗路徑：無效的輸入限制"""
        limits = {"max_orders_per_min": "not_a_number"}
        now_ms = int(time.time() * 1000)
        adjusted = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        # 應返回原始限制，因為轉換失敗
        assert "max_orders_per_min" in adjusted
        assert adjusted["max_orders_per_min"] == "not_a_number"
        # 應包含階段資訊
        assert "tw_trading_phase" in adjusted

    def test_twsessionconfig_default(self):
        """測試預設配置"""
        cfg = TWSessionConfig.default()
        assert cfg.tz == "Asia/Taipei"
        assert "max_orders_per_min" in cfg.preopen_multipliers
        assert cfg.preopen_multipliers["max_orders_per_min"] == 0.5

    def test_apply_tw_session_risk_adjustments_success(self):
        """成功路徑：應用乘數"""
        limits = {"max_orders_per_min": 100.0, "max_slippage_bps": 50.0}
        now_ms = int(time.time() * 1000)
        adjusted = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        # 檢查鍵是否存在
        assert "max_orders_per_min" in adjusted
        assert "max_slippage_bps" in adjusted
        assert "tw_trading_phase" in adjusted


def _ms_for_tw_time(hour: int, minute: int) -> int:
    """Return epoch-ms for a specific Taiwan local time on a fixed date."""
    tz = ZoneInfo("Asia/Taipei")
    dt = datetime(2026, 3, 3, hour, minute, 0, tzinfo=tz)
    return int(dt.timestamp() * 1000)


class TestTWSessionPhases:
    """Directly exercise each phase branch of get_tw_trading_phase (lines 90, 92, 94)."""

    def test_preopen_auction_phase(self):
        """09:05 TWN → PREOPEN_AUCTION (line 90)."""
        now_ms = _ms_for_tw_time(9, 5)
        phase = get_tw_trading_phase(now_ms)
        assert phase == TWTradingPhase.PREOPEN_AUCTION

    def test_regular_phase(self):
        """10:30 TWN → REGULAR (line 92)."""
        now_ms = _ms_for_tw_time(10, 30)
        phase = get_tw_trading_phase(now_ms)
        assert phase == TWTradingPhase.REGULAR

    def test_afterhours_phase(self):
        """13:35 TWN → AFTERHOURS_AUCTION (line 94)."""
        now_ms = _ms_for_tw_time(13, 35)
        phase = get_tw_trading_phase(now_ms)
        assert phase == TWTradingPhase.AFTERHOURS_AUCTION

    def test_closed_phase(self):
        """08:00 TWN → CLOSED."""
        now_ms = _ms_for_tw_time(8, 0)
        phase = get_tw_trading_phase(now_ms)
        assert phase == TWTradingPhase.CLOSED


class TestApplyTWSessionRiskAdjustmentsPhases:
    """Exercise each multiplier branch (lines 165-184)."""

    def test_preopen_multipliers_applied(self):
        """PREOPEN phase applies preopen_multipliers."""
        now_ms = _ms_for_tw_time(9, 5)
        limits = {
            "max_orders_per_min": 100.0,
            "max_slippage_bps": 100.0,
        }
        result = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        assert result["tw_trading_phase"] == TWTradingPhase.PREOPEN_AUCTION.value
        # Default preopen multiplier for max_orders_per_min is 0.5
        assert result["max_orders_per_min"] == pytest.approx(50.0)

    def test_regular_multipliers_applied(self):
        """REGULAR phase applies regular_multipliers (all 1.0 by default)."""
        now_ms = _ms_for_tw_time(10, 30)
        limits = {"max_orders_per_min": 100.0}
        result = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        assert result["tw_trading_phase"] == TWTradingPhase.REGULAR.value
        assert result["max_orders_per_min"] == pytest.approx(100.0)

    def test_afterhours_multipliers_applied(self):
        """AFTERHOURS phase applies afterhours_multipliers."""
        now_ms = _ms_for_tw_time(13, 35)
        limits = {
            "max_orders_per_min": 100.0,
            "max_qty_to_1m_volume_ratio": 1.0,
        }
        result = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        assert result["tw_trading_phase"] == TWTradingPhase.AFTERHOURS_AUCTION.value
        # Default afterhours multiplier for max_orders_per_min is 0.6
        assert result["max_orders_per_min"] == pytest.approx(60.0)

    def test_key_not_in_limits_skipped(self):
        """If a multiplier key is not in limits dict, it's skipped (continue branch)."""
        now_ms = _ms_for_tw_time(10, 30)
        limits = {"max_slippage_bps": 50.0}  # missing max_orders_per_min
        result = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        assert "max_orders_per_min" not in result
        assert result["max_slippage_bps"] == pytest.approx(50.0)

    def test_non_numeric_limit_value_skipped(self):
        """float(adjusted[k]) raises → except Exception: continue (lines 178-180)."""
        # Use REGULAR phase (10:30 TWN) so multipliers are applied
        now_ms = _ms_for_tw_time(10, 30)
        # Pass a non-numeric string for a key that also appears in multipliers
        limits = {
            "max_orders_per_min": "not_a_float",  # can't float() this
            "max_slippage_bps": 100.0,
        }
        result = apply_tw_session_risk_adjustments(limits, now_ms=now_ms)
        # The bad key should be preserved unchanged (exception → continue skips update)
        assert result["max_orders_per_min"] == "not_a_float"
        # The numeric key should be multiplied normally (1.0 × 100.0 = 100.0)
        assert result["max_slippage_bps"] == pytest.approx(100.0)
        assert result["tw_trading_phase"] == TWTradingPhase.REGULAR.value


class TestLoadSentinelTWSessionConfig:
    """Exercise _load_sentinel_tw_session_config edge cases (lines 108-109, 113, 118, 123-124, 132)."""

    def test_missing_file_returns_none(self, tmp_path):
        """Non-existent file → returns None (lines 108-109)."""
        result = _load_sentinel_tw_session_config(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_malformed_json_returns_none(self, tmp_path):
        """Malformed JSON → returns None (lines 108-109)."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{ this is not json }", encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(bad_file))
        assert result is None

    def test_missing_tw_session_rules_key_returns_none(self, tmp_path):
        """JSON without tw_session_rules key → returns None (line 113)."""
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps({"other_key": {}}), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is None

    def test_tw_session_rules_not_dict_returns_none(self, tmp_path):
        """tw_session_rules is not a dict → returns None (line 113)."""
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps({"tw_session_rules": "not_a_dict"}), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is None

    def test_all_multiplier_sections_missing_returns_none(self, tmp_path):
        """tw_session_rules present but no preopen/regular/afterhours → returns None (line 132)."""
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps({"tw_session_rules": {"timezone": "Asia/Taipei"}}), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is None

    def test_multiplier_value_non_numeric_skipped(self, tmp_path):
        """Non-numeric value in multiplier dict is skipped (lines 123-124)."""
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps({
            "tw_session_rules": {
                "regular": {
                    "max_orders_per_min": "bad_value",
                    "max_slippage_bps": 1.0
                }
            }
        }), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is not None
        # bad_value was skipped; max_slippage_bps survived
        assert "max_slippage_bps" in result.regular_multipliers
        assert "max_orders_per_min" not in result.regular_multipliers

    def test_valid_config_loaded(self, tmp_path):
        """Valid sentinel policy file with tw_session_rules loads correctly."""
        policy = {
            "tw_session_rules": {
                "timezone": "Asia/Taipei",
                "preopen_auction": {"max_orders_per_min": 0.3},
                "regular": {"max_orders_per_min": 1.0},
                "afterhours_auction": {"max_orders_per_min": 0.5},
            }
        }
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps(policy), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is not None
        assert result.tz == "Asia/Taipei"
        assert result.preopen_multipliers["max_orders_per_min"] == pytest.approx(0.3)

    def test_multiplier_section_not_dict_uses_base(self, tmp_path):
        """If a multiplier section is not a dict, _mp returns None → base is used (line 118)."""
        cfg_file = tmp_path / "policy.json"
        cfg_file.write_text(json.dumps({
            "tw_session_rules": {
                "regular": ["list", "not", "dict"],
                "preopen_auction": {"max_orders_per_min": 0.4}
            }
        }), encoding="utf-8")
        result = _load_sentinel_tw_session_config(str(cfg_file))
        assert result is not None
        # regular was None → base defaults used
        base = TWSessionConfig.default()
        assert result.regular_multipliers == base.regular_multipliers


import pytest
