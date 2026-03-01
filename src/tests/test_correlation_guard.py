"""Test Correlation Guard (v4 #22)."""


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
