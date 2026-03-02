"""Test Edge Metrics (v4 #16)."""

import math
import os
import sqlite3
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


# ── _safe_float branch coverage (lines 33-34, 36) ──────────────────────────

def test_safe_float_invalid_returns_default():
    """Line 33-34: float() raises exception, returns default."""
    from openclaw.edge_metrics import _safe_float
    result = _safe_float("not-a-number", default=42.0)
    assert result == 42.0


def test_safe_float_none_returns_default():
    """Line 33-34: float(None) raises TypeError, returns default."""
    from openclaw.edge_metrics import _safe_float
    result = _safe_float(None)
    assert result is None


def test_safe_float_inf_returns_default():
    """Line 36: math.isfinite check for inf value."""
    from openclaw.edge_metrics import _safe_float
    result = _safe_float(float("inf"), default=0.0)
    assert result == 0.0


def test_safe_float_nan_returns_default():
    """Line 36: math.isfinite check for nan value."""
    from openclaw.edge_metrics import _safe_float
    result = _safe_float(float("nan"), default=-1.0)
    assert result == -1.0


# ── _extract_trade_pnl_and_return branch coverage (lines 84-116) ───────────

def test_extract_trade_from_mapping_pnl_key():
    """Lines 87-100: Mapping with 'pnl' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"pnl": 100.0})
    assert pnl == 100.0
    assert ret is None


def test_extract_trade_from_mapping_profit_key():
    """Lines 87-100: Mapping with 'profit' key (fallback from pnl)."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"profit": 50.0})
    assert pnl == 50.0


def test_extract_trade_from_mapping_realized_pnl_key():
    """Lines 87-100: Mapping with 'realized_pnl' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"realized_pnl": 30.0})
    assert pnl == 30.0


def test_extract_trade_from_mapping_net_pnl_key():
    """Lines 87-100: Mapping with 'net_pnl' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"net_pnl": 20.0})
    assert pnl == 20.0


def test_extract_trade_from_mapping_with_return_pct():
    """Lines 94-100: Mapping with 'return_pct' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"pnl": 10.0, "return_pct": 0.05})
    assert pnl == 10.0
    assert ret == 0.05


def test_extract_trade_from_mapping_with_ret_key():
    """Lines 94-100: Mapping with 'ret' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"pnl": 10.0, "ret": 0.03})
    assert ret == 0.03


def test_extract_trade_from_mapping_with_r_key():
    """Lines 94-100: Mapping with 'r' key."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"pnl": 10.0, "r": 2.0})
    assert ret == 2.0


def test_extract_trade_from_mapping_invalid_pnl():
    """Lines 87-100: Mapping with invalid pnl value (non-finite)."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return
    pnl, ret = _extract_trade_pnl_and_return({"pnl": "bad"})
    assert pnl is None


def test_extract_trade_from_object_attributes():
    """Lines 102-116: Object with attributes (not a Mapping)."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return

    class TradeLike:
        pnl = 75.0
        return_pct = 0.10

    pnl, ret = _extract_trade_pnl_and_return(TradeLike())
    assert pnl == 75.0
    assert ret == 0.10


def test_extract_trade_from_object_profit_attr():
    """Lines 102-116: Object with 'profit' attribute."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return

    class TradeLike:
        profit = 40.0

    pnl, ret = _extract_trade_pnl_and_return(TradeLike())
    assert pnl == 40.0
    assert ret is None


def test_extract_trade_from_object_ret_attr():
    """Lines 109-114: Object with 'ret' return attribute."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return

    class TradeLike:
        pnl = 10.0
        ret = 0.02

    pnl, ret = _extract_trade_pnl_and_return(TradeLike())
    assert ret == 0.02


def test_extract_trade_from_object_no_pnl_attrs():
    """Lines 102-116: Object with no recognizable pnl attributes returns None."""
    from openclaw.edge_metrics import _extract_trade_pnl_and_return

    class EmptyTrade:
        pass

    pnl, ret = _extract_trade_pnl_and_return(EmptyTrade())
    assert pnl is None
    assert ret is None


# ── compute_edge_metrics branch coverage (lines 133, 136, 165-166, 176) ─────

def test_compute_edge_metrics_skips_invalid_pnl():
    """Lines 133-134: Trades with invalid pnl (None) are skipped."""
    from openclaw.edge_metrics import compute_edge_metrics
    # Dict with no pnl keys at all → skipped
    metrics = compute_edge_metrics([{"foo": "bar"}, {"baz": 1}])
    assert metrics.n_trades == 0


def test_compute_edge_metrics_with_return_pct():
    """Lines 135-136: ret is not None → appended to rets list."""
    from openclaw.edge_metrics import compute_edge_metrics
    trades = [
        {"pnl": 10.0, "return_pct": 0.05},
        {"pnl": -5.0, "return_pct": -0.02},
    ]
    metrics = compute_edge_metrics(trades)
    assert metrics.avg_return_pct is not None
    assert abs(metrics.avg_return_pct - 0.015) < 1e-9


def test_compute_edge_metrics_all_wins_profit_factor_inf():
    """Lines 165-166: No losses → profit_factor=inf, payoff_ratio=inf."""
    from openclaw.edge_metrics import compute_edge_metrics
    import math
    metrics = compute_edge_metrics([10.0, 20.0, 5.0])
    assert math.isinf(metrics.profit_factor)
    assert math.isinf(metrics.payoff_ratio)


def test_compute_edge_metrics_all_wins_no_avg_win():
    """Lines 165-166: profit_factor=0 when total_win==0 (all zero trades)."""
    from openclaw.edge_metrics import compute_edge_metrics
    # All zero trades — pnl==0 means neither win nor loss
    metrics = compute_edge_metrics([0.0, 0.0])
    assert metrics.profit_factor == 0.0
    assert metrics.payoff_ratio == 0.0


def test_compute_edge_metrics_with_avg_return_pct_line_176():
    """Line 176: rets list non-empty → avg_return_pct computed."""
    from openclaw.edge_metrics import compute_edge_metrics

    class T:
        pnl = 100.0
        r = 1.5

    metrics = compute_edge_metrics([T()])
    assert metrics.avg_return_pct == 1.5


# ── edge_score branch coverage (line 200) ───────────────────────────────────

def test_edge_score_with_infinite_profit_factor():
    """Line 200: pf is inf → pf_score = 1.0."""
    from openclaw.edge_metrics import EdgeMetrics, edge_score
    import math

    m = EdgeMetrics(
        n_trades=5,
        win_rate=1.0,
        avg_win=10.0,
        avg_loss=0.0,
        expectancy=10.0,
        profit_factor=float("inf"),
        payoff_ratio=float("inf"),
        total_pnl=50.0,
        avg_pnl=10.0,
    )
    score = edge_score(m)
    assert score > 0.0


# ── persist_edge_metrics_to_strategy_version extra branches (lines 237-238,
#    246, 250-251, 275-276, 280-281, 285-286) ─────────────────────────────────

def test_persist_bad_db_path_returns_false():
    """Lines 237-238: sqlite3.connect fails → returns False."""
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version
    metrics = compute_edge_metrics([10.0, -5.0])
    result = persist_edge_metrics_to_strategy_version(
        db_path="/nonexistent/path/db.db",
        version_id="v1",
        metrics=metrics,
    )
    assert result is False


def test_persist_missing_version_id_returns_false():
    """Line 246: row is None → returns False."""
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE strategy_versions (version_id TEXT, strategy_config_json TEXT)"
        )
        conn.commit()
        conn.close()

        metrics = compute_edge_metrics([10.0, -5.0])
        result = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id="nonexistent-id",
            metrics=metrics,
        )
        assert result is False
    finally:
        os.unlink(db_path)


def test_persist_with_null_strategy_config_json():
    """Lines 250-251: row[0] is None/empty → cfg = {}."""
    from openclaw.strategy_registry import StrategyRegistry
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        registry = StrategyRegistry(db_path)
        v = registry.create_version({"x": 1}, "test_user", version_tag="V2")
        vid = v["version_id"]

        # Manually set config to empty/null to hit the empty-cfg branch
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE strategy_versions SET strategy_config_json = '' WHERE version_id = ?",
            (vid,)
        )
        conn.commit()
        conn.close()

        metrics = compute_edge_metrics([10.0, -5.0])
        result = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id=vid,
            metrics=metrics,
        )
        assert result is True
    finally:
        os.unlink(db_path)


def test_persist_with_invalid_json_config():
    """Lines 250-251: row[0] is invalid JSON → cfg = {}."""
    from openclaw.strategy_registry import StrategyRegistry
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        registry = StrategyRegistry(db_path)
        v = registry.create_version({"x": 1}, "test_user", version_tag="V3")
        vid = v["version_id"]

        # Corrupt the JSON in the DB
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE strategy_versions SET strategy_config_json = 'NOT-JSON' WHERE version_id = ?",
            (vid,)
        )
        conn.commit()
        conn.close()

        metrics = compute_edge_metrics([10.0, -5.0])
        result = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id=vid,
            metrics=metrics,
        )
        assert result is True
    finally:
        os.unlink(db_path)


def test_persist_with_notes():
    """Lines 263-276: audit log with notes parameter."""
    from openclaw.strategy_registry import StrategyRegistry
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        registry = StrategyRegistry(db_path)
        v = registry.create_version({"x": 1}, "test_user", version_tag="V4")
        vid = v["version_id"]

        metrics = compute_edge_metrics([10.0, -5.0])
        result = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id=vid,
            metrics=metrics,
            notes="test notes",
            performed_by="tester",
        )
        assert result is True
    finally:
        os.unlink(db_path)


def test_persist_audit_log_table_missing_still_succeeds():
    """Lines 275-276: audit log insert fails (table missing) → still returns True."""
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version
    import json

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Create a DB with strategy_versions but NO version_audit_log table
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE strategy_versions (version_id TEXT, strategy_config_json TEXT)"
        )
        vid = "test-ver-1"
        conn.execute(
            "INSERT INTO strategy_versions VALUES (?, ?)",
            (vid, json.dumps({"foo": "bar"}))
        )
        conn.commit()
        conn.close()

        metrics = compute_edge_metrics([10.0, -5.0])
        result = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id=vid,
            metrics=metrics,
        )
        # audit log fails silently, UPDATE still committed → True
        assert result is True
    finally:
        os.unlink(db_path)


def test_persist_update_fails_returns_false():
    """Lines 280-281: outer try/except catches DB error → returns False."""
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version
    from unittest.mock import patch, MagicMock

    metrics = compute_edge_metrics([10.0, -5.0])

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        import sqlite3
        # Patch sqlite3.connect to return a conn whose execute raises on UPDATE
        real_conn = sqlite3.connect(db_path)
        real_conn.execute("CREATE TABLE strategy_versions (version_id TEXT, strategy_config_json TEXT)")
        vid = "test-ver-2"
        real_conn.execute("INSERT INTO strategy_versions VALUES (?, ?)", (vid, '{"x":1}'))
        real_conn.commit()
        real_conn.close()

        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: '{"x":1}'
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        # Make the UPDATE call raise
        call_count = [0]
        original_execute = mock_conn.execute

        def side_effect(sql, *args, **kwargs):
            if "UPDATE" in sql:
                raise RuntimeError("forced failure")
            return original_execute(sql, *args, **kwargs)

        mock_conn.execute.side_effect = side_effect

        with patch("sqlite3.connect", return_value=mock_conn):
            result = persist_edge_metrics_to_strategy_version(
                db_path=db_path,
                version_id=vid,
                metrics=metrics,
            )
        assert result is False
    finally:
        os.unlink(db_path)


def test_persist_conn_close_exception_handled():
    """Lines 285-286: finally block conn.close() raises → handled silently."""
    from openclaw.edge_metrics import compute_edge_metrics, persist_edge_metrics_to_strategy_version
    from unittest.mock import patch, MagicMock
    import json

    metrics = compute_edge_metrics([10.0, -5.0])

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        # Set up a minimal DB
        import sqlite3
        conn_setup = sqlite3.connect(db_path)
        conn_setup.execute("CREATE TABLE strategy_versions (version_id TEXT, strategy_config_json TEXT)")
        vid = "test-ver-3"
        conn_setup.execute("INSERT INTO strategy_versions VALUES (?, ?)", (vid, json.dumps({"x": 1})))
        conn_setup.commit()
        conn_setup.close()

        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: json.dumps({"x": 1})
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_conn.commit.return_value = None
        mock_conn.close.side_effect = Exception("close error")

        with patch("sqlite3.connect", return_value=mock_conn):
            result = persist_edge_metrics_to_strategy_version(
                db_path=db_path,
                version_id=vid,
                metrics=metrics,
            )
        # Even if close raises, the function should have returned True (commit happened)
        assert result is True
    finally:
        os.unlink(db_path)
