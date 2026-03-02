"""Test Correlation Guard (v4 #22)."""

import json
import math
import sqlite3
import tempfile
import os
from pathlib import Path


# ── _safe_float ────────────────────────────────────────────────────────────────

def test_safe_float_non_finite():
    """Lines 29-30, 32: _safe_float returns default for inf/nan and conversion errors."""
    from openclaw.correlation_guard import _safe_float
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("-inf")) is None
    assert _safe_float(float("nan")) is None
    assert _safe_float("not_a_number") is None
    assert _safe_float("not_a_number", default=0.0) == 0.0


# ── _std ───────────────────────────────────────────────────────────────────────

def test_std_single_element():
    """Line 42: _std returns 0.0 when fewer than 2 elements."""
    from openclaw.correlation_guard import _std
    assert _std([1.0]) == 0.0
    assert _std([]) == 0.0


# ── pearson_corr ───────────────────────────────────────────────────────────────

def test_pearson_corr_less_than_2():
    """Line 56: pearson_corr returns 0.0 with fewer than 2 common points."""
    from openclaw.correlation_guard import pearson_corr
    assert pearson_corr([], []) == 0.0
    assert pearson_corr([1.0], [1.0]) == 0.0


def test_pearson_corr_zero_variance():
    """Line 65: pearson_corr returns 0.0 when std dev is zero."""
    from openclaw.correlation_guard import pearson_corr
    # All same values -> zero variance
    xs = [1.0] * 10
    ys = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
    assert pearson_corr(xs, ys) == 0.0


# ── compute_correlation_matrix ─────────────────────────────────────────────────

def test_correlation_matrix_filters_invalid():
    """Line 85: invalid float values in returns are skipped."""
    from openclaw.correlation_guard import compute_correlation_matrix
    returns = {
        "A": [0.01, "bad", float("nan"), 0.02, -0.01, 0.01, 0.02, -0.02, 0.01, -0.01],
        "B": [0.01, 0.02, 0.03, 0.02, -0.01, 0.01, 0.02, -0.02, 0.01, -0.01],
    }
    # Should not crash, just skip invalid entries
    m = compute_correlation_matrix(returns, window=20, min_points=5)
    assert isinstance(m, dict)


def test_correlation_matrix_fewer_than_min_points():
    """Symbol filtered out when not enough valid points."""
    from openclaw.correlation_guard import compute_correlation_matrix
    returns = {
        "A": [0.01, 0.02],  # only 2 valid, min_points=10 -> filtered
        "B": [0.01] * 12,
    }
    m = compute_correlation_matrix(returns, window=60, min_points=10)
    assert "A" not in m


# ── _normalize_weights ─────────────────────────────────────────────────────────

def test_normalize_weights_invalid_values():
    """Lines 135-138: non-float and non-positive weights are skipped."""
    from openclaw.correlation_guard import _normalize_weights
    w = _normalize_weights({"A": "bad", "B": -1.0, "C": 0.0, "D": 0.5})
    # A is non-float, B and C are non-positive, only D should remain
    assert "A" not in w
    assert "B" not in w
    assert "C" not in w
    assert "D" in w


def test_normalize_weights_all_invalid():
    """Line 142: empty dict returned when all weights are zero/negative/invalid."""
    from openclaw.correlation_guard import _normalize_weights
    w = _normalize_weights({"A": 0.0, "B": -1.0})
    assert w == {}


# ── _weighted_avg_abs_corr ─────────────────────────────────────────────────────

def test_weighted_avg_abs_corr_single_symbol():
    """Line 149: returns 0.0 when fewer than 2 symbols overlap."""
    from openclaw.correlation_guard import _weighted_avg_abs_corr
    matrix = {"A": {"A": 1.0}}
    weights = {"A": 1.0}
    assert _weighted_avg_abs_corr(matrix, weights) == 0.0


def test_weighted_avg_abs_corr_zero_den():
    """Line 162: returns 0.0 when denominator is zero."""
    from openclaw.correlation_guard import _weighted_avg_abs_corr
    # Two symbols in matrix but zero weights
    matrix = {"A": {"A": 1.0, "B": 0.5}, "B": {"A": 0.5, "B": 1.0}}
    weights = {"A": 0.0, "B": 0.0}
    # Normalizing would produce empty, but test the internal branch directly
    # To test it, pass weights with zero product
    result = _weighted_avg_abs_corr(matrix, {"A": 0.0, "B": 0.0})
    assert result == 0.0


# ── evaluate_correlation_risk (avg breach, both, fallback) ────────────────────

def test_evaluate_correlation_risk_avg_breach_only():
    """Line 219: CORR_WEIGHTED_AVG_EXCEEDED when only avg is breached (pair threshold not reached)."""
    from openclaw.correlation_guard import evaluate_correlation_risk, CorrelationGuardPolicy

    # Perfectly correlated returns so avg abs corr will be > 0
    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01]
    returns = {"A": r, "B": r}
    weights = {"A": 0.5, "B": 0.5}
    # Set max_pair just above 1.0 (won't trip), avg threshold below actual avg
    pol = CorrelationGuardPolicy(
        window=50, min_points=10,
        max_pair_abs_corr=1.01,       # won't trip (corr <= 1.0)
        max_weighted_avg_abs_corr=0.0,  # always trips
    )
    d = evaluate_correlation_risk(returns_by_symbol=returns, weights_by_symbol=weights, policy=pol)
    assert d.reason_code == "CORR_WEIGHTED_AVG_EXCEEDED"


def test_evaluate_correlation_risk_both_breached():
    """Lines 217, 219: both pair and avg breached -> reason stays CORR_MAX_PAIR_EXCEEDED, avg suggestion appended."""
    from openclaw.correlation_guard import evaluate_correlation_risk, CorrelationGuardPolicy

    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01]
    returns = {"A": r, "B": r}
    weights = {"A": 0.5, "B": 0.5}
    pol = CorrelationGuardPolicy(
        window=50, min_points=10,
        max_pair_abs_corr=0.5,    # trips pair
        max_weighted_avg_abs_corr=0.0,  # trips avg
    )
    d = evaluate_correlation_risk(returns_by_symbol=returns, weights_by_symbol=weights, policy=pol)
    assert d.reason_code == "CORR_MAX_PAIR_EXCEEDED"
    # Both suggestions present
    joined = " ".join(d.suggestions)
    assert "diversification" in joined.lower() or "uncorrelated" in joined.lower()


def test_evaluate_correlation_risk_pair_breach_no_top_pairs():
    """Line 225: suggestions fallback when pair is breached but top_pairs is empty."""
    from openclaw.correlation_guard import evaluate_correlation_risk, CorrelationGuardPolicy

    # Use enough data points to pass min_points, but set max_pair_abs_corr <= 0
    # so breached_pair is True even with max_abs=0. Weights don't overlap matrix symbols
    # to keep top_pairs empty.
    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01]
    returns = {"A": r, "B": r}
    # Weights for symbols NOT in returns -> no overlap -> syms=[], top_pairs=[]
    weights = {"X": 0.5, "Y": 0.5}
    pol = CorrelationGuardPolicy(
        window=50, min_points=10,
        max_pair_abs_corr=-0.01,    # breached_pair = True (max_abs=0 >= -0.01)
        max_weighted_avg_abs_corr=99.0,  # avg not breached
    )
    d = evaluate_correlation_risk(returns_by_symbol=returns, weights_by_symbol=weights, policy=pol)
    assert d.ok is False
    assert "Reduce correlated exposures." in d.suggestions


def test_evaluate_correlation_risk_ok():
    """Test the ok=True path with uncorrelated data."""
    from openclaw.correlation_guard import evaluate_correlation_risk, CorrelationGuardPolicy
    import random
    random.seed(42)
    r1 = [random.gauss(0, 0.01) for _ in range(20)]
    r2 = [random.gauss(0, 0.01) for _ in range(20)]
    returns = {"A": r1, "B": r2}
    weights = {"A": 0.5, "B": 0.5}
    pol = CorrelationGuardPolicy(
        window=60, min_points=5,
        max_pair_abs_corr=0.99,
        max_weighted_avg_abs_corr=0.99,
    )
    d = evaluate_correlation_risk(returns_by_symbol=returns, weights_by_symbol=weights, policy=pol)
    assert d.ok is True
    assert d.reason_code == "CORR_OK"


# ── apply_correlation_guard_to_limits ─────────────────────────────────────────

def test_apply_limits_ok_path():
    """Lines 254-256: ok=True path sets correlation_guard_ok=True and returns."""
    from openclaw.correlation_guard import apply_correlation_guard_to_limits, CorrelationGuardDecision

    d = CorrelationGuardDecision(
        ok=True,
        reason_code="CORR_OK",
        n_symbols=2,
        max_pair_abs_corr=0.3,
        weighted_avg_abs_corr=0.2,
        top_pairs=[],
        suggestions=[],
        matrix={},
    )
    limits = {"max_gross_exposure": 1.0, "max_symbol_weight": 0.2}
    out = apply_correlation_guard_to_limits(limits, d)
    assert out["correlation_guard_ok"] is True
    assert out["correlation_guard_reason"] == "CORR_OK"
    # Values unchanged
    assert out["max_gross_exposure"] == 1.0


def test_apply_limits_missing_keys():
    """Line 262: keys not in limits are skipped without error."""
    from openclaw.correlation_guard import apply_correlation_guard_to_limits, CorrelationGuardDecision

    d = CorrelationGuardDecision(
        ok=False,
        reason_code="CORR_MAX_PAIR_EXCEEDED",
        n_symbols=2,
        max_pair_abs_corr=0.95,
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95)],
        suggestions=["Reduce"],
        matrix={},
    )
    # limits dict lacks max_gross_exposure and max_symbol_weight
    out = apply_correlation_guard_to_limits({"other_key": 99}, d)
    assert out["correlation_guard_ok"] is False
    assert out["other_key"] == 99


def test_apply_limits_non_numeric_value():
    """Lines 265-266: non-numeric limit value caught and continue."""
    from openclaw.correlation_guard import apply_correlation_guard_to_limits, CorrelationGuardDecision

    d = CorrelationGuardDecision(
        ok=False,
        reason_code="CORR_MAX_PAIR_EXCEEDED",
        n_symbols=2,
        max_pair_abs_corr=0.95,
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95)],
        suggestions=["Reduce"],
        matrix={},
    )
    limits = {"max_gross_exposure": "not_a_number", "max_symbol_weight": 0.2}
    out = apply_correlation_guard_to_limits(limits, d)
    # max_gross_exposure couldn't be scaled, stays as original
    assert out["max_gross_exposure"] == "not_a_number"
    # max_symbol_weight was scaled
    assert out["max_symbol_weight"] < 0.2


# ── load_correlation_guard_policy ─────────────────────────────────────────────

def test_load_policy_valid_file(tmp_path):
    """Lines 285-307: load_correlation_guard_policy reads valid JSON."""
    from openclaw.correlation_guard import load_correlation_guard_policy

    policy_data = {
        "window": 30,
        "min_points": 5,
        "max_pair_abs_corr": 0.90,
        "max_weighted_avg_abs_corr": 0.60,
        "exposure_scale_on_breach": 0.75,
    }
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(policy_data))

    pol = load_correlation_guard_policy(str(p))
    assert pol.window == 30
    assert pol.min_points == 5
    assert pol.max_pair_abs_corr == 0.90
    assert pol.exposure_scale_on_breach == 0.75


def test_load_policy_file_not_found():
    """Lines 288-289: returns default when file not found."""
    from openclaw.correlation_guard import load_correlation_guard_policy, CorrelationGuardPolicy

    pol = load_correlation_guard_policy("/nonexistent/path/policy.json")
    default = CorrelationGuardPolicy.default()
    assert pol.window == default.window


def test_load_policy_invalid_json(tmp_path):
    """Lines 288-289: returns default for invalid JSON."""
    from openclaw.correlation_guard import load_correlation_guard_policy, CorrelationGuardPolicy

    p = tmp_path / "bad.json"
    p.write_text("not valid json!!")
    pol = load_correlation_guard_policy(str(p))
    default = CorrelationGuardPolicy.default()
    assert pol.window == default.window


def test_load_policy_with_invalid_int_field(tmp_path):
    """Lines 296-299: _geti fallback when field not convertible to int."""
    from openclaw.correlation_guard import load_correlation_guard_policy, CorrelationGuardPolicy

    policy_data = {
        "window": "not_an_int",   # will fail int() -> use default
        "max_pair_abs_corr": "also_bad",  # will fail float() -> use default
    }
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(policy_data))

    default = CorrelationGuardPolicy.default()
    pol = load_correlation_guard_policy(str(p), default=default)
    assert pol.window == default.window
    assert pol.max_pair_abs_corr == default.max_pair_abs_corr


def test_load_policy_with_custom_default(tmp_path):
    """Lines 285: use provided default when file is unreadable."""
    from openclaw.correlation_guard import load_correlation_guard_policy, CorrelationGuardPolicy

    custom_default = CorrelationGuardPolicy(window=120)
    pol = load_correlation_guard_policy("/nonexistent/file.json", default=custom_default)
    assert pol.window == 120


# ── render_correlation_report ─────────────────────────────────────────────────

def test_render_correlation_report_with_pairs_and_suggestions():
    """Lines 313-330: render report with top_pairs and suggestions."""
    from openclaw.correlation_guard import render_correlation_report, CorrelationGuardDecision

    d = CorrelationGuardDecision(
        ok=False,
        reason_code="CORR_MAX_PAIR_EXCEEDED",
        n_symbols=2,
        max_pair_abs_corr=0.95,
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95), ("C", "D", 0.80)],
        suggestions=["Reduce exposure on A.", "Increase diversification."],
        matrix={},
    )
    report = render_correlation_report(d)
    assert "Correlation Guard Report" in report
    assert "A/B" in report
    assert "Reduce exposure on A." in report
    assert "Increase diversification." in report


def test_render_correlation_report_no_pairs_no_suggestions():
    """Lines 313-318: render report with empty top_pairs and suggestions."""
    from openclaw.correlation_guard import render_correlation_report, CorrelationGuardDecision

    d = CorrelationGuardDecision(
        ok=True,
        reason_code="CORR_OK",
        n_symbols=0,
        max_pair_abs_corr=0.0,
        weighted_avg_abs_corr=0.0,
        top_pairs=[],
        suggestions=[],
        matrix={},
    )
    report = render_correlation_report(d)
    assert "Correlation Guard Report" in report
    assert "CORR_OK" in report


# ── _table_exists ──────────────────────────────────────────────────────────────

def test_table_exists():
    """Lines 334-338: _table_exists returns True/False correctly."""
    from openclaw.correlation_guard import _table_exists

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE foo (x INT)")
    assert _table_exists(conn, "foo") is True
    assert _table_exists(conn, "bar") is False


# ── log_correlation_incident ──────────────────────────────────────────────────

def test_log_incident_ok_decision_skipped():
    """Line 344-345: ok=True decision does not insert."""
    from openclaw.correlation_guard import log_correlation_incident, CorrelationGuardDecision

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE incidents(incident_id TEXT, ts TEXT, severity TEXT,
           source TEXT, code TEXT, detail_json TEXT, resolved INTEGER)"""
    )

    d = CorrelationGuardDecision(
        ok=True, reason_code="CORR_OK", n_symbols=2,
        max_pair_abs_corr=0.3, weighted_avg_abs_corr=0.2,
        top_pairs=[], suggestions=[], matrix={},
    )
    log_correlation_incident(conn, d)
    count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert count == 0


def test_log_incident_no_table():
    """Line 346-347: no incidents table -> returns silently."""
    from openclaw.correlation_guard import log_correlation_incident, CorrelationGuardDecision

    conn = sqlite3.connect(":memory:")  # no incidents table
    d = CorrelationGuardDecision(
        ok=False, reason_code="CORR_MAX_PAIR_EXCEEDED", n_symbols=2,
        max_pair_abs_corr=0.95, weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95)], suggestions=["Reduce"], matrix={},
    )
    # Should not raise
    log_correlation_incident(conn, d)


def test_log_incident_warn_severity():
    """Lines 349-368: logs 'warn' severity for moderate breach."""
    from openclaw.correlation_guard import log_correlation_incident, CorrelationGuardDecision

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE incidents(incident_id TEXT, ts TEXT, severity TEXT,
           source TEXT, code TEXT, detail_json TEXT, resolved INTEGER)"""
    )

    d = CorrelationGuardDecision(
        ok=False, reason_code="CORR_MAX_PAIR_EXCEEDED", n_symbols=2,
        max_pair_abs_corr=0.90,  # < 0.95, so warn
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.90)], suggestions=["Reduce"], matrix={},
    )
    log_correlation_incident(conn, d)
    row = conn.execute("SELECT severity FROM incidents").fetchone()
    assert row is not None
    assert row[0] == "warn"


def test_log_incident_critical_severity():
    """Lines 350-351: logs 'critical' severity for severe breach with 3+ symbols."""
    from openclaw.correlation_guard import log_correlation_incident, CorrelationGuardDecision

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE incidents(incident_id TEXT, ts TEXT, severity TEXT,
           source TEXT, code TEXT, detail_json TEXT, resolved INTEGER)"""
    )

    d = CorrelationGuardDecision(
        ok=False, reason_code="CORR_MAX_PAIR_EXCEEDED", n_symbols=3,
        max_pair_abs_corr=0.96,  # >= 0.95 + n_symbols >= 3 -> critical
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.96)], suggestions=["Reduce"], matrix={},
    )
    log_correlation_incident(conn, d)
    row = conn.execute("SELECT severity FROM incidents").fetchone()
    assert row is not None
    assert row[0] == "critical"


# ── correlation_guard_policy default() ────────────────────────────────────────

def test_policy_default():
    """Basic smoke test for CorrelationGuardPolicy.default()."""
    from openclaw.correlation_guard import CorrelationGuardPolicy
    p = CorrelationGuardPolicy.default()
    assert p.window == 60
    assert p.max_pair_abs_corr == 0.85


def test_correlation_matrix_basic():
    from openclaw.correlation_guard import compute_correlation_matrix

    # Perfectly correlated sequences.
    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
    returns = {"A": r, "B": r}

    m = compute_correlation_matrix(returns, window=10, min_points=5)
    assert abs(m["A"]["B"] - 1.0) < 1e-9


def test_evaluate_correlation_risk_breach_pair():
    from openclaw.correlation_guard import evaluate_correlation_risk, CorrelationGuardPolicy

    r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01]
    returns = {"A": r, "B": r, "C": [0.01] * len(r)}  # C has zero variance -> corr 0

    weights = {"A": 0.5, "B": 0.4, "C": 0.1}
    pol = CorrelationGuardPolicy(window=50, min_points=10, max_pair_abs_corr=0.80, max_weighted_avg_abs_corr=0.60)

    d = evaluate_correlation_risk(returns_by_symbol=returns, weights_by_symbol=weights, policy=pol)
    assert d.ok is False
    assert d.max_pair_abs_corr >= 0.99
    assert d.reason_code in {"CORR_MAX_PAIR_EXCEEDED", "CORR_WEIGHTED_AVG_EXCEEDED"}
    assert d.suggestions


def test_apply_correlation_guard_to_limits_scales():
    from openclaw.correlation_guard import apply_correlation_guard_to_limits, CorrelationGuardDecision

    limits = {"max_gross_exposure": 1.2, "max_symbol_weight": 0.2}

    d = CorrelationGuardDecision(
        ok=False,
        reason_code="CORR_MAX_PAIR_EXCEEDED",
        n_symbols=2,
        max_pair_abs_corr=0.95,
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95)],
        suggestions=["Reduce exposure"],
        matrix={"A": {"A": 1.0, "B": 0.95}, "B": {"A": 0.95, "B": 1.0}},
    )

    out = apply_correlation_guard_to_limits(limits, d)
    assert out["max_gross_exposure"] < limits["max_gross_exposure"]
    assert out["max_symbol_weight"] < limits["max_symbol_weight"]
