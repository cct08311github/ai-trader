"""Tests for signal_logic.py hard kill trailing stop (#598)."""
import sys
from pathlib import Path

# Ensure src/ is importable
_src = Path(__file__).resolve().parents[1] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from openclaw.signal_logic import evaluate_exit, SignalParams


class TestHardKillTrailingStop:
    """#598: hard kill at -15% DD from HWM regardless of profit tier."""

    def test_hard_kill_triggers_at_15pct_dd(self):
        """DD = 18.6% from HWM 94.7 → must trigger hard_kill."""
        closes = [90.0, 85.0, 80.0, 77.1]
        result = evaluate_exit(closes, avg_price=79.98, high_water_mark=94.7)
        assert result.signal == "sell"
        assert "hard_kill" in result.reason

    def test_hard_kill_exactly_at_threshold(self):
        """DD = exactly 15% → must trigger."""
        hwm = 100.0
        price = 85.0  # exactly -15%
        result = evaluate_exit([price], avg_price=80.0, high_water_mark=hwm)
        assert result.signal == "sell"
        assert "hard_kill" in result.reason

    def test_hard_kill_below_threshold_no_trigger(self):
        """DD = 14% → must NOT trigger hard_kill."""
        hwm = 100.0
        price = 86.0  # -14%, below threshold
        result = evaluate_exit([price], avg_price=80.0, high_water_mark=hwm)
        # Might still trigger tiered trailing stop or take_profit, but NOT hard_kill
        if result.signal == "sell":
            assert "hard_kill" not in result.reason

    def test_hard_kill_fires_before_tiered_trailing(self):
        """Hard kill should fire BEFORE the 3-tier trailing stop."""
        # HWM=100, avg=60, profit_pct_at_hwm=66.7% → tight tier (3%)
        # Tiered trigger: 100 * 0.97 = 97
        # Hard kill trigger: 100 * 0.85 = 85
        # Price = 84 → both should trigger, but hard_kill goes first
        result = evaluate_exit([84.0], avg_price=60.0, high_water_mark=100.0)
        assert result.signal == "sell"
        assert "hard_kill" in result.reason

    def test_no_hard_kill_without_hwm(self):
        """Without HWM, hard kill doesn't fire."""
        result = evaluate_exit([50.0], avg_price=80.0, high_water_mark=None)
        # Should trigger stop_loss instead
        assert result.signal == "sell"
        assert "stop_loss" in result.reason

    def test_hard_kill_custom_threshold(self):
        """Custom hard_kill_dd_pct=0.10 should trigger at -10% DD."""
        params = SignalParams(hard_kill_dd_pct=0.10)
        result = evaluate_exit([90.0], avg_price=80.0, high_water_mark=100.0, params=params)
        assert result.signal == "sell"
        assert "hard_kill" in result.reason

    def test_1303_real_scenario(self):
        """Real 1303 scenario: HWM=94.7, avg=79.98, current=77.1."""
        # Build realistic close series
        closes = [84.2, 78.4, 73.8, 72.3, 76.0, 74.8, 74.2, 81.4, 81.4, 78.7, 77.1]
        result = evaluate_exit(closes, avg_price=79.98, high_water_mark=94.7)
        assert result.signal == "sell"
        assert "hard_kill" in result.reason
        # DD = (94.7 - 77.1) / 94.7 = 18.6% > 15%

    def test_existing_trailing_stop_still_works(self):
        """Ensure tiered trailing stop still fires for smaller DDs."""
        # HWM=100, avg=60, profit_pct=66.7% → tight tier (3%)
        # Trigger at 100 * 0.97 = 97
        # Price = 96 → below tiered trigger, above hard_kill (85)
        result = evaluate_exit([96.0], avg_price=60.0, high_water_mark=100.0)
        assert result.signal == "sell"
        assert "trailing_stop" in result.reason

    def test_stop_loss_still_works(self):
        """Stop loss (3% below avg) still fires when no HWM set."""
        closes = [76.0]  # 76 < 79.98 * 0.97 = 77.58
        result = evaluate_exit(closes, avg_price=79.98, high_water_mark=None)
        assert result.signal == "sell"
        assert "stop_loss" in result.reason
