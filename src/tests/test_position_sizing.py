import json
from pathlib import Path
from openclaw.position_sizing import (
    PositionSizingInput,
    fixed_fractional_qty,
    ATRPositionSizingInput,
    atr_risk_qty,
    PositionLevelLimits,
    get_position_limits_for_level,
    load_sentinel_policy,
    _apply_level_caps,
    _safe_float,
    calculate_position_qty,
)


def test_fixed_fractional_qty_base():
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    assert qty == 166


def test_low_confidence_scales_down_qty():
    base = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    low_conf = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.4,
            confidence_threshold=0.6,
            low_confidence_scale=0.5,
        )
    )
    assert low_conf == int(base * 0.5)


def test_fixed_fractional_zero_risk():
    """邊界測試：零風險百分比，應返回0。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.0,
            confidence=0.9,
        )
    )
    assert qty == 0


def test_fixed_fractional_negative_stop():
    """反向測試：止損價高於入場價（多頭頭寸無效）。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=1010,  # 高於入場價
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    # 風險為負，應返回 0 或負數。我們接受 <= 0。
    assert qty <= 0


def test_fixed_fractional_high_confidence():
    """正向測試：信心高於閾值，應使用完整規模。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.8,
            confidence_threshold=0.7,
        )
    )
    # 計算預期數量：nav * base_risk_pct / (entry_price - stop_price)
    expected = int(500_000 * 0.01 / (1000 - 970))
    assert qty == expected


# ── fixed_fractional_qty edge cases (lines 37, 43) ───────────────────────────

def test_fixed_fractional_zero_nav():
    """Line 37: nav <= 0 returns 0."""
    qty = fixed_fractional_qty(
        PositionSizingInput(nav=0, entry_price=1000, stop_price=970, base_risk_pct=0.01)
    )
    assert qty == 0


def test_fixed_fractional_equal_entry_stop():
    """Line 43: stop_distance == 0 returns 0."""
    qty = fixed_fractional_qty(
        PositionSizingInput(nav=500_000, entry_price=1000, stop_price=1000, base_risk_pct=0.01)
    )
    assert qty == 0


# ── load_sentinel_policy (lines 90-94) ──────────────────────────────────────

def test_load_sentinel_policy_valid(tmp_path):
    """Lines 90-93: loads a valid policy JSON."""
    policy_data = {
        "position_limits": {
            "levels": {
                "2": {"max_risk_per_trade_pct_nav": 0.003, "max_position_notional_pct_nav": 0.05}
            }
        }
    }
    policy_file = tmp_path / "sentinel_policy.json"
    policy_file.write_text(json.dumps(policy_data))
    policy = load_sentinel_policy(str(policy_file))
    assert isinstance(policy, dict)
    assert "position_limits" in policy


def test_load_sentinel_policy_missing_file():
    """Line 94: returns {} when file does not exist."""
    policy = load_sentinel_policy("/nonexistent/path/sentinel_policy.json")
    assert policy == {}


# ── get_position_limits_for_level (lines 115-136) ───────────────────────────

def test_get_position_limits_defaults_for_non_mapping():
    """Lines 117-118: returns defaults when policy is not a Mapping."""
    limits = get_position_limits_for_level(None, 2)  # type: ignore[arg-type]
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    assert limits == _DEFAULT_LEVEL_LIMITS[2]


def test_get_position_limits_no_position_limits_key():
    """Lines 121-122: returns defaults when policy has no 'position_limits'."""
    limits = get_position_limits_for_level({}, 2)
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    assert limits == _DEFAULT_LEVEL_LIMITS[2]


def test_get_position_limits_no_levels_key():
    """Lines 124-125: returns defaults when 'levels' key is absent."""
    limits = get_position_limits_for_level({"position_limits": {}}, 2)
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    assert limits == _DEFAULT_LEVEL_LIMITS[2]


def test_get_position_limits_no_level_entry():
    """Lines 128-130: returns defaults when level key not found in levels."""
    policy = {"position_limits": {"levels": {}}}
    limits = get_position_limits_for_level(policy, 3)
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    assert limits == _DEFAULT_LEVEL_LIMITS[3]


def test_get_position_limits_from_policy():
    """Lines 132-136: reads limits from policy and clamps to [0, 1]."""
    policy = {
        "position_limits": {
            "levels": {
                "2": {
                    "max_risk_per_trade_pct_nav": 0.003,
                    "max_position_notional_pct_nav": 0.05,
                }
            }
        }
    }
    limits = get_position_limits_for_level(policy, 2)
    assert limits.max_risk_per_trade_pct_nav == 0.003
    assert limits.max_position_notional_pct_nav == 0.05


def test_get_position_limits_clamps_values():
    """Lines 134-135: values clamped to [0, 1]."""
    policy = {
        "position_limits": {
            "levels": {
                "1": {
                    "max_risk_per_trade_pct_nav": -0.5,   # below 0 → clamped to 0
                    "max_position_notional_pct_nav": 5.0,  # above 1 → clamped to 1
                }
            }
        }
    }
    limits = get_position_limits_for_level(policy, 1)
    assert limits.max_risk_per_trade_pct_nav == 0.0
    assert limits.max_position_notional_pct_nav == 1.0


def test_get_position_limits_unknown_level_uses_level2_default():
    """Lines 115-116: unknown level falls back to level-2 defaults."""
    limits = get_position_limits_for_level({}, 99)
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    assert limits == _DEFAULT_LEVEL_LIMITS[2]


# ── _apply_level_caps (lines 166-179) ────────────────────────────────────────

def test_apply_level_caps_zero_qty():
    """Line 167: qty <= 0 returns 0."""
    result = _apply_level_caps(qty=0, entry_price=100.0, nav=1_000_000, level_limits=None)
    assert result == 0


def test_apply_level_caps_zero_entry_price():
    """Line 169: entry_price <= 0 returns 0."""
    limits = PositionLevelLimits(max_risk_per_trade_pct_nav=0.005, max_position_notional_pct_nav=0.1)
    result = _apply_level_caps(qty=100, entry_price=0.0, nav=1_000_000, level_limits=limits)
    assert result == 0


def test_apply_level_caps_no_limits():
    """Line 171: level_limits=None returns qty unchanged."""
    result = _apply_level_caps(qty=50, entry_price=100.0, nav=1_000_000, level_limits=None)
    assert result == 50


def test_apply_level_caps_zero_max_notional():
    """Line 175-176: max_notional <= 0 returns 0."""
    limits = PositionLevelLimits(max_risk_per_trade_pct_nav=0.0, max_position_notional_pct_nav=0.0)
    result = _apply_level_caps(qty=100, entry_price=100.0, nav=1_000_000, level_limits=limits)
    assert result == 0


def test_apply_level_caps_caps_qty():
    """Lines 178-179: qty capped by notional limit."""
    # 1_000_000 * 0.10 = 100_000 notional; at 1000/share = 100 shares max
    limits = PositionLevelLimits(max_risk_per_trade_pct_nav=0.005, max_position_notional_pct_nav=0.10)
    result = _apply_level_caps(qty=500, entry_price=1000.0, nav=1_000_000, level_limits=limits)
    assert result == 100


# ── atr_risk_qty (lines 183-206) ─────────────────────────────────────────────

def test_atr_risk_qty_basic():
    """Lines 183-206: ATR-based sizing."""
    inp = ATRPositionSizingInput(
        nav=1_000_000,
        entry_price=500.0,
        atr=5.0,
        base_risk_pct=0.01,
        atr_stop_multiple=2.0,
        confidence=0.9,
    )
    qty = atr_risk_qty(inp)
    # max_loss = 1_000_000 * 0.01 = 10_000; stop_distance = 5 * 2 = 10; qty = 10_000/10 = 1000
    assert qty == 1000


def test_atr_risk_qty_zero_nav():
    """Line 183: returns 0 when nav <= 0."""
    inp = ATRPositionSizingInput(nav=0, entry_price=500.0, atr=5.0, base_risk_pct=0.01)
    assert atr_risk_qty(inp) == 0


def test_atr_risk_qty_zero_atr():
    """Line 183: returns 0 when atr <= 0."""
    inp = ATRPositionSizingInput(nav=1_000_000, entry_price=500.0, atr=0.0, base_risk_pct=0.01)
    assert atr_risk_qty(inp) == 0


def test_atr_risk_qty_zero_atr_multiple():
    """Line 188: returns 0 when stop_distance <= 0."""
    inp = ATRPositionSizingInput(
        nav=1_000_000, entry_price=500.0, atr=5.0, base_risk_pct=0.01, atr_stop_multiple=0.0
    )
    assert atr_risk_qty(inp) == 0


def test_atr_risk_qty_with_level_limits():
    """Lines 191-192: effective_risk_pct limited by level limits."""
    limits = PositionLevelLimits(max_risk_per_trade_pct_nav=0.001, max_position_notional_pct_nav=1.0)
    inp = ATRPositionSizingInput(
        nav=1_000_000, entry_price=500.0, atr=5.0, base_risk_pct=0.01, atr_stop_multiple=2.0
    )
    qty = atr_risk_qty(inp, level_limits=limits)
    # effective_risk_pct clamped to 0.001; max_loss = 1000; stop_distance = 10; qty = 100
    assert qty == 100


def test_atr_risk_qty_zero_effective_risk():
    """Line 194-195: returns 0 when effective_risk_pct <= 0."""
    limits = PositionLevelLimits(max_risk_per_trade_pct_nav=0.0, max_position_notional_pct_nav=1.0)
    inp = ATRPositionSizingInput(
        nav=1_000_000, entry_price=500.0, atr=5.0, base_risk_pct=0.01, atr_stop_multiple=2.0
    )
    assert atr_risk_qty(inp, level_limits=limits) == 0


def test_atr_risk_qty_low_confidence_scales_down():
    """Lines 202-203: low confidence scales down qty."""
    inp = ATRPositionSizingInput(
        nav=1_000_000, entry_price=500.0, atr=5.0, base_risk_pct=0.01,
        atr_stop_multiple=2.0, confidence=0.3, confidence_threshold=0.6, low_confidence_scale=0.5,
    )
    qty = atr_risk_qty(inp)
    # base qty = 1000; low_confidence → 500
    assert qty == 500


def test_atr_risk_qty_small_loss_yields_zero():
    """Line 199-200: returns 0 when qty <= 0 after division."""
    inp = ATRPositionSizingInput(
        nav=1, entry_price=500.0, atr=5.0, base_risk_pct=0.001, atr_stop_multiple=2.0
    )
    assert atr_risk_qty(inp) == 0


# ── calculate_position_qty (lines 235-274) ───────────────────────────────────

def test_calculate_position_qty_atr_method():
    """Lines 241-255: ATR method dispatch."""
    qty = calculate_position_qty(
        nav=1_000_000,
        entry_price=500.0,
        base_risk_pct=0.01,
        atr=5.0,
        method="atr",
    )
    assert qty == 1000


def test_calculate_position_qty_fixed_fractional_no_stop_returns_zero():
    """Line 258-259: stop_price=None with fixed_fractional returns 0."""
    qty = calculate_position_qty(
        nav=1_000_000,
        entry_price=500.0,
        base_risk_pct=0.01,
        stop_price=None,
        method="fixed_fractional",
    )
    assert qty == 0


def test_calculate_position_qty_fixed_fractional_with_stop():
    """Lines 260-273: fixed_fractional with stop_price and level caps."""
    qty = calculate_position_qty(
        nav=1_000_000,
        entry_price=1000.0,
        base_risk_pct=0.01,
        stop_price=970.0,
        method="fixed_fractional",
    )
    # (1_000_000 * 0.01) / 30 = 333
    assert qty == 333


def test_calculate_position_qty_with_authority_level(tmp_path):
    """Lines 236-238: loads sentinel policy when authority_level is set."""
    policy_data = {
        "position_limits": {
            "levels": {
                "3": {"max_risk_per_trade_pct_nav": 0.005, "max_position_notional_pct_nav": 0.10}
            }
        }
    }
    policy_file = tmp_path / "sentinel_policy.json"
    policy_file.write_text(json.dumps(policy_data))
    qty = calculate_position_qty(
        nav=1_000_000,
        entry_price=500.0,
        base_risk_pct=0.005,
        atr=5.0,
        method="atr",
        authority_level=3,
        sentinel_policy_path=str(policy_file),
    )
    # max_loss = 1_000_000 * 0.005 = 5000; stop = 10; qty = 500; notional cap = 100_000/500 = 200
    assert qty == 200


def test_calculate_position_qty_atr_method_variants():
    """Line 241: 'atr_risk' and 'atr_based' method names also route to ATR."""
    qty1 = calculate_position_qty(
        nav=1_000_000, entry_price=500.0, base_risk_pct=0.01, atr=5.0, method="atr_risk"
    )
    qty2 = calculate_position_qty(
        nav=1_000_000, entry_price=500.0, base_risk_pct=0.01, atr=5.0, method="atr_based"
    )
    assert qty1 == qty2 == 1000


# ── _safe_float (lines 79-80) ────────────────────────────────────────────────

def test_safe_float_non_numeric_returns_default():
    """Lines 79-80: non-convertible value returns default."""
    result = _safe_float("not_a_number", 0.5)
    assert result == 0.5


def test_safe_float_none_returns_default():
    """Lines 79-80: None can't convert to float → returns default."""
    result = _safe_float(None, 99.0)
    assert result == 99.0


def test_get_position_limits_with_non_numeric_policy_values():
    """Lines 79-80: non-numeric field values in policy use _safe_float fallback."""
    policy = {
        "position_limits": {
            "levels": {
                "2": {
                    "max_risk_per_trade_pct_nav": "bad_value",
                    "max_position_notional_pct_nav": "also_bad",
                }
            }
        }
    }
    # Should fall back to defaults (not crash)
    from openclaw.position_sizing import _DEFAULT_LEVEL_LIMITS
    limits = get_position_limits_for_level(policy, 2)
    assert limits.max_risk_per_trade_pct_nav == _DEFAULT_LEVEL_LIMITS[2].max_risk_per_trade_pct_nav
