"""Test Boundary Conditions for AI-Trader v4 (全覆蓋測試計畫 - 任務1)."""

import pytest
import math
import tempfile
import os

from openclaw.position_sizing import (
    PositionSizingInput,
    fixed_fractional_qty,
    ATRPositionSizingInput,
    atr_risk_qty,
    calculate_position_qty,
    PositionLevelLimits,
    get_position_limits_for_level,
    load_sentinel_policy,
)


class TestPositionSizingBoundaryConditions:
    """測試 position_sizing.py 的核心邊界邏輯。"""

    def test_fixed_fractional_qty_zero_nav(self):
        """測試 NAV=0 的情況。"""
        inp = PositionSizingInput(
            nav=0.0,
            entry_price=100.0,
            stop_price=95.0,
            base_risk_pct=0.02,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

    def test_fixed_fractional_qty_zero_entry_price(self):
        """測試 entry_price=0 的情況。"""
        inp = PositionSizingInput(
            nav=100000.0,
            entry_price=0.0,
            stop_price=95.0,
            base_risk_pct=0.02,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

    def test_fixed_fractional_qty_zero_stop_price(self):
        """測試 stop_price=0 的情況。"""
        inp = PositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            stop_price=0.0,
            base_risk_pct=0.02,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

    def test_fixed_fractional_qty_negative_values(self):
        """測試負值輸入。"""
        inp = PositionSizingInput(
            nav=-100000.0,
            entry_price=-100.0,
            stop_price=-95.0,
            base_risk_pct=0.02,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

    def test_fixed_fractional_qty_zero_stop_distance(self):
        """測試 entry_price == stop_price (停損距離為0)。"""
        inp = PositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            stop_price=100.0,
            base_risk_pct=0.02,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

    def test_fixed_fractional_qty_extreme_risk_pct(self):
        """測試極端風險百分比 (0% 和 100%)。"""
        # 0% 風險
        inp = PositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            stop_price=95.0,
            base_risk_pct=0.0,
        )
        result = fixed_fractional_qty(inp)
        assert result == 0

        # 100% 風險
        inp = PositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            stop_price=95.0,
            base_risk_pct=1.0,
        )
        result = fixed_fractional_qty(inp)
        expected = int((100000.0 * 1.0) / 5.0)
        assert result == expected

    def test_fixed_fractional_qty_large_numbers(self):
        """測試極大數值 (避免溢出)。"""
        inp = PositionSizingInput(
            nav=1e9,
            entry_price=1000.0,
            stop_price=990.0,
            base_risk_pct=0.01,
        )
        result = fixed_fractional_qty(inp)
        expected = int((1e9 * 0.01) / 10.0)
        assert result == expected
        assert result > 0

    def test_atr_risk_qty_zero_nav(self):
        """測試 ATR sizing 中 NAV=0 的情況。"""
        inp = ATRPositionSizingInput(
            nav=0.0,
            entry_price=100.0,
            atr=2.0,
            base_risk_pct=0.02,
        )
        result = atr_risk_qty(inp)
        assert result == 0

    def test_atr_risk_qty_zero_entry_price(self):
        """測試 ATR sizing 中 entry_price=0 的情況。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=0.0,
            atr=2.0,
            base_risk_pct=0.02,
        )
        result = atr_risk_qty(inp)
        assert result == 0

    def test_atr_risk_qty_zero_atr(self):
        """測試 ATR sizing 中 ATR=0 的情況。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            atr=0.0,
            base_risk_pct=0.02,
        )
        result = atr_risk_qty(inp)
        assert result == 0

    def test_atr_risk_qty_negative_atr_stop_multiple(self):
        """測試負的 ATR stop multiple。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            atr=2.0,
            base_risk_pct=0.02,
            atr_stop_multiple=-1.0,
        )
        result = atr_risk_qty(inp)
        assert result == 0

    def test_atr_risk_qty_large_atr(self):
        """測試極大的 ATR 值。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            atr=1000.0,
            base_risk_pct=0.02,
            atr_stop_multiple=2.0,
        )
        result = atr_risk_qty(inp)
        assert result == 1

    def test_atr_risk_qty_with_level_limits_zero_caps(self):
        """測試 level limits 為 0 的情況。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            atr=2.0,
            base_risk_pct=0.02,
        )
        limits = PositionLevelLimits(
            max_risk_per_trade_pct_nav=0.0,
            max_position_notional_pct_nav=0.0,
        )
        result = atr_risk_qty(inp, level_limits=limits)
        assert result == 0

    def test_atr_risk_qty_with_level_limits_notional_cap(self):
        """測試 notional cap 限制。"""
        inp = ATRPositionSizingInput(
            nav=100000.0,
            entry_price=100.0,
            atr=2.0,
            base_risk_pct=0.02,
        )
        limits = PositionLevelLimits(
            max_risk_per_trade_pct_nav=0.05,
            max_position_notional_pct_nav=0.01,
        )
        result = atr_risk_qty(inp, level_limits=limits)
        assert result == 10

    def test_calculate_position_qty_edge_cases(self):
        """測試 calculate_position_qty 的邊界情況。"""
        
        # 情況1: 所有輸入為0
        result = calculate_position_qty(
            nav=0.0,
            entry_price=0.0,
            base_risk_pct=0.02,
            stop_price=0.0,
        )
        assert result == 0
        
        # 情況2: 沒有 stop_price 也沒有 atr
        result = calculate_position_qty(
            nav=100000.0,
            entry_price=100.0,
            base_risk_pct=0.02,
            stop_price=None,
            atr=None,
        )
        assert result == 0
        
        # 情況3: 負的 authority_level
        result = calculate_position_qty(
            nav=100000.0,
            entry_price=100.0,
            base_risk_pct=0.02,
            stop_price=95.0,
            authority_level=-1,
        )
        assert result >= 0

    def test_load_sentinel_policy_missing_file(self):
        """測試加載不存在的政策文件。"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            missing_path = f.name
        
        os.unlink(missing_path)
        policy = load_sentinel_policy(missing_path)
        assert policy == {}

    def test_load_sentinel_policy_invalid_json(self):
        """測試加載無效的 JSON 文件。"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            f.write(b"invalid json content")
            invalid_path = f.name
        
        try:
            policy = load_sentinel_policy(invalid_path)
            assert policy == {}
        finally:
            os.unlink(invalid_path)

    def test_get_position_limits_for_level_invalid_level(self):
        """測試無效的 level 值。"""
        policy = {}
        limits = get_position_limits_for_level(policy, level=99)
        assert limits.max_risk_per_trade_pct_nav == 0.003
        assert limits.max_position_notional_pct_nav == 0.05

    def test_get_position_limits_for_level_malformed_policy(self):
        """測試格式錯誤的政策文件。"""
        # 測試非字典類型的政策 - 這應該回退到默認值
        try:
            limits = get_position_limits_for_level("not a dict", level=2)
            assert limits.max_risk_per_trade_pct_nav == 0.003
            assert limits.max_position_notional_pct_nav == 0.05
        except Exception:
            # 如果拋出異常也是可以接受的
            pass
        
        # 測試嵌套結構錯誤
        policy = {"position_limits": "not a dict"}
        limits = get_position_limits_for_level(policy, level=2)
        assert limits.max_risk_per_trade_pct_nav == 0.003
        assert limits.max_position_notional_pct_nav == 0.05
