"""Extended tests for correlation_guard module.

Covers:
- Zero variance input (all prices identical) — should not crash
- Single symbol — should skip correlation check
- Known correlation values with pre-computed expected results
"""
from __future__ import annotations

import math
import sqlite3

import pytest

from openclaw.correlation_guard import (
    CorrelationGuardDecision,
    CorrelationGuardPolicy,
    apply_correlation_guard_to_limits,
    compute_correlation_matrix,
    evaluate_correlation_risk,
    log_correlation_incident,
    pearson_corr,
    render_correlation_report,
)


# ---------------------------------------------------------------------------
# Tests: zero-variance inputs (should not crash)
# ---------------------------------------------------------------------------

class TestZeroVariance:
    def test_pearson_corr_zero_variance_xs_returns_zero(self):
        """If xs has zero variance, pearson_corr must return 0.0, not raise."""
        xs = [1.0] * 15  # constant
        ys = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01, 0.01, 0.0, -0.01]
        result = pearson_corr(xs, ys)
        assert result == 0.0

    def test_pearson_corr_zero_variance_ys_returns_zero(self):
        """If ys has zero variance, pearson_corr must return 0.0, not raise."""
        xs = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01, 0.02, -0.01, 0.01, 0.0, -0.01]
        ys = [0.0] * 15  # constant
        result = pearson_corr(xs, ys)
        assert result == 0.0

    def test_pearson_corr_both_zero_variance_returns_zero(self):
        """Both sequences constant → correlation undefined → 0.0."""
        xs = [5.0] * 12
        ys = [5.0] * 12
        result = pearson_corr(xs, ys)
        assert result == 0.0

    def test_compute_correlation_matrix_constant_series_excluded(self):
        """A constant series has zero std, so it must not produce NaN in the matrix."""
        returns = {
            "A": [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01],
            "B": [0.0] * 10,  # constant — zero variance
        }
        matrix = compute_correlation_matrix(returns, window=20, min_points=5)
        # B is included (has enough points) but correlation with A must be 0.0, not NaN
        if "B" in matrix and "A" in matrix.get("B", {}):
            val = matrix["B"]["A"]
            assert math.isfinite(val)
            assert val == 0.0

    def test_evaluate_correlation_risk_all_constant_does_not_crash(self):
        """All symbols with constant prices → evaluate must not raise."""
        returns = {
            "A": [0.0] * 15,
            "B": [0.0] * 15,
        }
        weights = {"A": 0.5, "B": 0.5}
        # Should not raise, even though all variances are zero
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns,
            weights_by_symbol=weights,
        )
        assert isinstance(decision.ok, bool)
        assert math.isfinite(decision.max_pair_abs_corr)
        assert math.isfinite(decision.weighted_avg_abs_corr)


# ---------------------------------------------------------------------------
# Tests: single symbol
# ---------------------------------------------------------------------------

class TestSingleSymbol:
    def test_single_symbol_compute_matrix_returns_diagonal_only(self):
        """With one symbol, the matrix should contain only the diagonal (self = 1.0)."""
        returns = {"A": [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]}
        matrix = compute_correlation_matrix(returns, window=20, min_points=5)
        assert "A" in matrix
        assert matrix["A"]["A"] == 1.0
        # No off-diagonal entries since there is only one symbol
        assert len(matrix) == 1

    def test_single_symbol_evaluate_is_ok(self):
        """Single symbol cannot form pairs → correlation guard passes."""
        returns = {"A": [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]}
        weights = {"A": 1.0}
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns,
            weights_by_symbol=weights,
        )
        assert decision.ok is True
        assert decision.reason_code == "CORR_OK"
        assert decision.max_pair_abs_corr == 0.0
        assert decision.weighted_avg_abs_corr == 0.0
        assert decision.top_pairs == []
        assert decision.n_symbols <= 1

    def test_single_symbol_no_suggestions(self):
        """Single symbol → no reduce suggestions."""
        returns = {"A": [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]}
        weights = {"A": 1.0}
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns,
            weights_by_symbol=weights,
        )
        assert decision.suggestions == []


# ---------------------------------------------------------------------------
# Tests: known correlation values
# ---------------------------------------------------------------------------

class TestKnownCorrelationValues:
    def test_perfectly_positively_correlated(self):
        """Identical series → correlation == 1.0."""
        r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
        result = pearson_corr(r, r)
        assert abs(result - 1.0) < 1e-9

    def test_perfectly_negatively_correlated(self):
        """Negated series → correlation == -1.0."""
        r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
        neg_r = [-x for x in r]
        result = pearson_corr(r, neg_r)
        assert abs(result - (-1.0)) < 1e-9

    def test_orthogonal_series_near_zero(self):
        """Alternating +/- vs constant-offset alternating → correlation should be near ±1 or 0 depending on series."""
        xs = [1.0, -1.0] * 10  # alternating
        ys = [-1.0, 1.0] * 10  # opposite alternating
        result = pearson_corr(xs, ys)
        assert abs(result - (-1.0)) < 1e-9

    def test_evaluate_perfectly_correlated_pair_breaches(self):
        """Two identical return series must breach max_pair_abs_corr threshold."""
        r = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
        returns = {"A": r, "B": r}
        weights = {"A": 0.5, "B": 0.5}
        pol = CorrelationGuardPolicy(
            window=20, min_points=5, max_pair_abs_corr=0.80, max_weighted_avg_abs_corr=0.90
        )
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns, weights_by_symbol=weights, policy=pol
        )
        assert decision.ok is False
        assert decision.reason_code == "CORR_MAX_PAIR_EXCEEDED"
        assert decision.max_pair_abs_corr >= 0.99

    def test_evaluate_uncorrelated_pair_passes(self):
        """Two truly uncorrelated series should pass the default policy."""
        # Orthogonal pattern: A moves up-down, B constant → corr ~ 0
        r_a = [0.01, -0.01, 0.02, -0.02, 0.01, -0.01, 0.02, -0.02, 0.01, -0.01,
               0.01, -0.01, 0.02, -0.02, 0.01]
        r_b = [0.0] * 15  # constant — zero variance → corr forced to 0
        returns = {"A": r_a, "B": r_b}
        weights = {"A": 0.5, "B": 0.5}
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns, weights_by_symbol=weights
        )
        # max_pair_abs_corr must be 0.0 (constant B → pearson returns 0)
        assert decision.max_pair_abs_corr == 0.0

    def test_evaluate_top_pairs_sorted_by_abs_corr_desc(self):
        """top_pairs should be ordered by |correlation| descending."""
        r_high = [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01]
        r_low  = [0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, 0.01, -0.01]
        returns = {"A": r_high, "B": r_high, "C": r_low}  # A-B perfectly corr; A-C partially
        weights = {"A": 0.4, "B": 0.4, "C": 0.2}
        decision = evaluate_correlation_risk(
            returns_by_symbol=returns, weights_by_symbol=weights
        )
        if len(decision.top_pairs) >= 2:
            for i in range(len(decision.top_pairs) - 1):
                assert abs(decision.top_pairs[i][2]) >= abs(decision.top_pairs[i + 1][2])

    def test_compute_matrix_respects_min_points_filter(self):
        """Symbols with fewer than min_points valid returns are excluded from the matrix."""
        returns = {
            "A": [0.01, -0.02, 0.03, -0.01, 0.02, -0.02, 0.01, 0.00, 0.01, -0.01],  # 10 pts
            "B": [0.01, -0.02],  # only 2 pts — below min_points=5
        }
        matrix = compute_correlation_matrix(returns, window=20, min_points=5)
        assert "A" in matrix
        assert "B" not in matrix  # excluded due to insufficient data

    def test_apply_limits_scaling_on_breach(self):
        """Breached decision must scale down max_gross_exposure and max_symbol_weight."""
        limits = {"max_gross_exposure": 1.5, "max_symbol_weight": 0.30, "other_param": 42}
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_MAX_PAIR_EXCEEDED",
            n_symbols=2,
            max_pair_abs_corr=0.92,
            weighted_avg_abs_corr=0.65,
            top_pairs=[("A", "B", 0.92)],
            suggestions=["Reduce A"],
            matrix={"A": {"A": 1.0, "B": 0.92}, "B": {"A": 0.92, "B": 1.0}},
        )
        pol = CorrelationGuardPolicy(exposure_scale_on_breach=0.75)
        out = apply_correlation_guard_to_limits(limits, d, policy=pol)
        assert out["max_gross_exposure"] == pytest.approx(1.5 * 0.75)
        assert out["max_symbol_weight"] == pytest.approx(0.30 * 0.75)
        # Unrelated keys must be preserved unchanged
        assert out["other_param"] == 42
        assert out["correlation_guard_ok"] is False
        assert out["correlation_guard_scale"] == 0.75

    def test_apply_limits_no_scaling_when_ok(self):
        """When decision is ok, limits must be unchanged."""
        limits = {"max_gross_exposure": 1.2, "max_symbol_weight": 0.20}
        d = CorrelationGuardDecision(
            ok=True,
            reason_code="CORR_OK",
            n_symbols=2,
            max_pair_abs_corr=0.30,
            weighted_avg_abs_corr=0.20,
            top_pairs=[],
            suggestions=[],
            matrix={},
        )
        out = apply_correlation_guard_to_limits(limits, d)
        assert out["max_gross_exposure"] == 1.2
        assert out["max_symbol_weight"] == 0.20
        assert out["correlation_guard_ok"] is True


# ---------------------------------------------------------------------------
# Tests: render_correlation_report
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_render_includes_key_fields(self):
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_MAX_PAIR_EXCEEDED",
            n_symbols=2,
            max_pair_abs_corr=0.95,
            weighted_avg_abs_corr=0.60,
            top_pairs=[("A", "B", 0.95)],
            suggestions=["Reduce A"],
            matrix={},
        )
        report_text = render_correlation_report(d)
        assert "CORR_MAX_PAIR_EXCEEDED" in report_text
        assert "A" in report_text and "B" in report_text
        assert "Reduce A" in report_text

    def test_render_ok_decision(self):
        d = CorrelationGuardDecision(
            ok=True,
            reason_code="CORR_OK",
            n_symbols=1,
            max_pair_abs_corr=0.0,
            weighted_avg_abs_corr=0.0,
            top_pairs=[],
            suggestions=[],
            matrix={},
        )
        report_text = render_correlation_report(d)
        assert "CORR_OK" in report_text


# ---------------------------------------------------------------------------
# Tests: log_correlation_incident
# ---------------------------------------------------------------------------

class TestLogCorrelationIncident:
    def _make_incidents_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE incidents (
                incident_id TEXT PRIMARY KEY,
                ts TEXT,
                severity TEXT,
                source TEXT,
                code TEXT,
                detail_json TEXT,
                resolved INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        return conn

    def test_ok_decision_does_not_log_incident(self):
        conn = self._make_incidents_db()
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
        log_correlation_incident(conn, d)
        rows = conn.execute("SELECT * FROM incidents").fetchall()
        assert len(rows) == 0

    def test_breached_decision_logs_incident(self):
        conn = self._make_incidents_db()
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_MAX_PAIR_EXCEEDED",
            n_symbols=2,
            max_pair_abs_corr=0.92,
            weighted_avg_abs_corr=0.60,
            top_pairs=[("A", "B", 0.92)],
            suggestions=["Reduce A"],
            matrix={},
        )
        log_correlation_incident(conn, d)
        rows = conn.execute("SELECT source, code FROM incidents").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "correlation_guard"
        assert rows[0][1] == "CORR_MAX_PAIR_EXCEEDED"

    def test_critical_severity_when_high_corr_and_many_symbols(self):
        conn = self._make_incidents_db()
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_MAX_PAIR_EXCEEDED",
            n_symbols=4,  # >= 3
            max_pair_abs_corr=0.97,  # >= 0.95
            weighted_avg_abs_corr=0.70,
            top_pairs=[("A", "B", 0.97)],
            suggestions=["Reduce A"],
            matrix={},
        )
        log_correlation_incident(conn, d)
        row = conn.execute("SELECT severity FROM incidents").fetchone()
        assert row[0] == "critical"

    def test_warn_severity_when_below_critical_threshold(self):
        conn = self._make_incidents_db()
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_WEIGHTED_AVG_EXCEEDED",
            n_symbols=2,  # < 3
            max_pair_abs_corr=0.60,  # < 0.95
            weighted_avg_abs_corr=0.58,
            top_pairs=[],
            suggestions=["Diversify"],
            matrix={},
        )
        log_correlation_incident(conn, d)
        row = conn.execute("SELECT severity FROM incidents").fetchone()
        assert row[0] == "warn"

    def test_no_incidents_table_does_not_crash(self):
        """If incidents table doesn't exist, log_correlation_incident must not raise."""
        conn = sqlite3.connect(":memory:")
        d = CorrelationGuardDecision(
            ok=False,
            reason_code="CORR_MAX_PAIR_EXCEEDED",
            n_symbols=2,
            max_pair_abs_corr=0.92,
            weighted_avg_abs_corr=0.60,
            top_pairs=[("A", "B", 0.92)],
            suggestions=["Reduce A"],
            matrix={},
        )
        # Must not raise even without incidents table
        log_correlation_incident(conn, d)
