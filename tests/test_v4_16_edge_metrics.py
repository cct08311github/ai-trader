"""Test Edge Metrics (v4 #16)."""

import os
import tempfile


def test_compute_edge_metrics_basic():
    from openclaw.edge_metrics import compute_edge_metrics

    metrics = compute_edge_metrics([10, -5, 5, -5])

    assert metrics.n_trades == 4
    assert metrics.win_rate == 0.5
    assert metrics.avg_win == 7.5
    assert metrics.avg_loss == 5.0

    # expectancy = 0.5*7.5 - 0.5*5 = 1.25
    assert abs(metrics.expectancy - 1.25) < 1e-9

    # profit factor = 15/10 = 1.5
    assert abs(metrics.profit_factor - 1.5) < 1e-9


def test_edge_score_bounds():
    from openclaw.edge_metrics import compute_edge_metrics, edge_score

    m0 = compute_edge_metrics([])
    assert edge_score(m0) == 0.0

    m1 = compute_edge_metrics([10, -1, 10, -1, 10, -1])
    s = edge_score(m1)
    assert 0.0 <= s <= 100.0


def test_persist_edge_metrics_to_strategy_version():
    from openclaw.strategy_registry import StrategyRegistry
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        registry = StrategyRegistry(db_path)
        v = registry.create_version({"foo": "bar"}, "pm", version_tag="V1")

        metrics = compute_edge_metrics([10, -5, 5, -5])
        ok = persist_edge_metrics_to_strategy_version(db_path=db_path, version_id=v["version_id"], metrics=metrics)
        assert ok is True

        vinfo = registry.get_version(v["version_id"])
        cfg = vinfo["strategy_config"]

        assert "edge_metrics" in cfg
        assert cfg["edge_metrics"]["n_trades"] == 4
        assert "edge_score" in cfg

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
