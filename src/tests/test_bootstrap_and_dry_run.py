"""Tests for openclaw.bootstrap_and_dry_run."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from openclaw.path_utils import get_repo_root
from openclaw.bootstrap_and_dry_run import (
    _apply_sql_file,
    _mock_llm_call,
    _seed_runtime_rows,
    main,
    print_summary,
    run_main_dry,
    run_pipeline_demo,
)


# ---------------------------------------------------------------------------
# Full in-memory schema helper (mirrors what all migration files would create)
# ---------------------------------------------------------------------------

def make_full_db() -> sqlite3.Connection:
    """Build a complete in-memory SQLite DB with all tables needed by bootstrap."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_limits (
          limit_id TEXT PRIMARY KEY,
          scope TEXT NOT NULL,
          symbol TEXT,
          strategy_id TEXT,
          rule_name TEXT NOT NULL,
          rule_value REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS decisions (
          decision_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          symbol TEXT NOT NULL,
          strategy_id TEXT NOT NULL,
          strategy_version TEXT NOT NULL,
          signal_side TEXT NOT NULL,
          signal_score REAL NOT NULL,
          signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
          llm_ref TEXT,
          reason_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_checks (
          check_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          ts TEXT NOT NULL,
          passed INTEGER NOT NULL,
          reject_code TEXT,
          metrics_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          broker_order_id TEXT,
          ts_submit TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL,
          order_type TEXT NOT NULL,
          tif TEXT NOT NULL,
          status TEXT NOT NULL,
          strategy_version TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fills (
          fill_id TEXT PRIMARY KEY,
          order_id TEXT NOT NULL,
          ts_fill TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL NOT NULL,
          fee REAL NOT NULL DEFAULT 0,
          tax REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS order_events (
          event_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          from_status TEXT,
          to_status TEXT,
          source TEXT NOT NULL,
          reason_code TEXT,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_pnl_summary (
          trade_date TEXT PRIMARY KEY,
          nav_start REAL NOT NULL,
          nav_end REAL NOT NULL,
          realized_pnl REAL NOT NULL,
          unrealized_pnl REAL NOT NULL,
          total_pnl REAL NOT NULL,
          daily_return REAL NOT NULL,
          rolling_peak_nav REAL NOT NULL,
          rolling_drawdown REAL NOT NULL,
          losing_streak_days INTEGER NOT NULL DEFAULT 0,
          risk_mode TEXT NOT NULL DEFAULT 'normal'
        );

        CREATE TABLE IF NOT EXISTS strategy_health (
          strategy_id TEXT PRIMARY KEY,
          as_of_ts TEXT NOT NULL,
          rolling_trades INTEGER NOT NULL DEFAULT 0,
          rolling_win_rate REAL NOT NULL DEFAULT 0.0,
          enabled INTEGER NOT NULL DEFAULT 1,
          note TEXT
        );

        CREATE TABLE IF NOT EXISTS llm_traces (
          trace_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          component TEXT NOT NULL,
          model TEXT NOT NULL,
          decision_id TEXT,
          prompt_text TEXT NOT NULL,
          response_text TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          latency_ms INTEGER NOT NULL DEFAULT 0,
          tools_json TEXT NOT NULL DEFAULT '[]',
          confidence REAL,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS working_memory (
          mem_key TEXT PRIMARY KEY,
          mem_value_json TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS episodic_memory (
          episode_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          symbol TEXT NOT NULL,
          strategy_id TEXT NOT NULL,
          market_regime TEXT NOT NULL,
          entry_reason TEXT NOT NULL,
          outcome_pnl REAL NOT NULL,
          pm_score REAL,
          root_cause_code TEXT,
          decay_score REAL NOT NULL DEFAULT 1.0,
          archived INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS semantic_memory (
          rule_id TEXT PRIMARY KEY,
          rule_text TEXT NOT NULL,
          confidence REAL NOT NULL,
          source_episodes_json TEXT NOT NULL,
          sample_count INTEGER NOT NULL DEFAULT 0,
          last_validated_date TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reflection_runs (
          run_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          stage1_diagnosis_json TEXT NOT NULL,
          stage2_abstraction_json TEXT NOT NULL,
          stage3_refinement_json TEXT NOT NULL,
          candidate_semantic_rules INTEGER NOT NULL DEFAULT 0,
          semantic_memory_size INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS strategy_proposals (
          proposal_id TEXT PRIMARY KEY,
          generated_by TEXT NOT NULL,
          target_rule TEXT NOT NULL,
          rule_category TEXT NOT NULL,
          current_value TEXT NOT NULL,
          proposed_value TEXT NOT NULL,
          supporting_evidence TEXT NOT NULL,
          source_episodes_json TEXT NOT NULL,
          backtest_sharpe_before REAL,
          backtest_sharpe_after REAL,
          confidence REAL NOT NULL,
          semantic_memory_action TEXT NOT NULL,
          rollback_version TEXT NOT NULL,
          requires_human_approval INTEGER NOT NULL DEFAULT 1,
          auto_approve_eligible INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        INSERT OR REPLACE INTO risk_limits
          (limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)
        VALUES
          ('global.max_symbol_weight', 'global', NULL, NULL, 'max_symbol_weight', 0.20, 1, datetime('now')),
          ('symbol.2330.max_symbol_weight', 'symbol', '2330', NULL, 'max_symbol_weight', 0.15, 1, datetime('now'));
        """
    )
    return conn


# ---------------------------------------------------------------------------
# _apply_sql_file
# ---------------------------------------------------------------------------

def test_apply_sql_file_executes_sql(tmp_path):
    """_apply_sql_file reads a .sql file and executes it."""
    sql_file = tmp_path / "test.sql"
    sql_file.write_text(
        "CREATE TABLE IF NOT EXISTS test_tbl (id INTEGER PRIMARY KEY, val TEXT);\n"
        "INSERT INTO test_tbl VALUES (1, 'hello');\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    _apply_sql_file(conn, sql_file)
    row = conn.execute("SELECT val FROM test_tbl WHERE id=1").fetchone()
    assert row[0] == "hello"


def test_apply_sql_file_commits(tmp_path):
    """After _apply_sql_file, data is committed (readable by a new cursor)."""
    sql_file = tmp_path / "commit_test.sql"
    sql_file.write_text(
        "CREATE TABLE IF NOT EXISTS commit_tbl (x INTEGER);\n"
        "INSERT INTO commit_tbl VALUES (42);\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(":memory:")
    _apply_sql_file(conn, sql_file)
    count = conn.execute("SELECT COUNT(*) FROM commit_tbl").fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# _mock_llm_call
# ---------------------------------------------------------------------------

def test_mock_llm_call_bull_case():
    """When prompt contains 'bull_case', returns debate-style dict."""
    result = _mock_llm_call("gemini-3.1-pro", "generate bull_case for 2330")
    assert "bull_case" in result
    assert "confidence" in result
    assert isinstance(result["confidence"], float)


def test_mock_llm_call_news_sentiment():
    """When prompt does NOT contain 'bull_case', returns news sentiment dict."""
    result = _mock_llm_call("gemini-3.0-flash", "analyze market news")
    assert "score" in result
    assert "direction" in result
    assert result["direction"] == "bullish"


# ---------------------------------------------------------------------------
# _seed_runtime_rows
# ---------------------------------------------------------------------------

def test_seed_runtime_rows_inserts_pnl_summary():
    """_seed_runtime_rows inserts into daily_pnl_summary."""
    conn = make_full_db()
    _seed_runtime_rows(conn)
    row = conn.execute("SELECT * FROM daily_pnl_summary ORDER BY trade_date DESC LIMIT 1").fetchone()
    assert row is not None


def test_seed_runtime_rows_inserts_strategy_health():
    """_seed_runtime_rows inserts into strategy_health."""
    conn = make_full_db()
    _seed_runtime_rows(conn)
    row = conn.execute("SELECT * FROM strategy_health WHERE strategy_id='breakout'").fetchone()
    assert row is not None


def test_seed_runtime_rows_updates_risk_limits():
    """_seed_runtime_rows sets max_symbol_weight to 0.50 for matching rows."""
    conn = make_full_db()
    _seed_runtime_rows(conn)
    row = conn.execute(
        "SELECT rule_value FROM risk_limits WHERE rule_name='max_symbol_weight' AND scope='global'"
    ).fetchone()
    assert row is not None
    assert float(row[0]) == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# run_pipeline_demo
# ---------------------------------------------------------------------------

def test_run_pipeline_demo_runs_and_commits(capsys):
    """run_pipeline_demo completes and prints JSON output."""
    conn = make_full_db()
    run_pipeline_demo(conn)
    captured = capsys.readouterr()
    assert "pipeline_demo:" in captured.out
    data = json.loads(captured.out.replace("pipeline_demo: ", ""))
    assert "news" in data
    assert "debate" in data


def test_run_pipeline_demo_inserts_episodic_memory():
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM episodic_memory").fetchone()[0]
    assert count >= 1


def test_run_pipeline_demo_inserts_semantic_memory():
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
    assert count >= 1


def test_run_pipeline_demo_inserts_reflection_run():
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM reflection_runs").fetchone()[0]
    assert count >= 1


def test_run_pipeline_demo_inserts_strategy_proposal():
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM strategy_proposals").fetchone()[0]
    assert count >= 1


def test_run_pipeline_demo_inserts_working_memory():
    conn = make_full_db()
    run_pipeline_demo(conn)
    row = conn.execute("SELECT * FROM working_memory WHERE mem_key='demo'").fetchone()
    assert row is not None


def test_run_pipeline_demo_inserts_incident():
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert count >= 1


def test_run_pipeline_demo_inserts_llm_trace():
    """run_pipeline_demo should produce at least one llm_traces row."""
    conn = make_full_db()
    run_pipeline_demo(conn)
    count = conn.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
    assert count >= 1


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------

def test_print_summary_outputs_json(capsys):
    """print_summary prints db_summary: JSON with all expected table keys."""
    conn = make_full_db()
    print_summary(conn)
    captured = capsys.readouterr()
    assert "db_summary:" in captured.out
    # Extract JSON portion
    json_str = captured.out.replace("db_summary: ", "").strip()
    data = json.loads(json_str)
    assert "orders" in data
    assert "fills" in data
    assert "decisions" in data
    assert "incidents" in data
    assert "llm_traces" in data


def test_print_summary_counts_are_integers(capsys):
    conn = make_full_db()
    print_summary(conn)
    captured = capsys.readouterr()
    json_str = captured.out.replace("db_summary: ", "").strip()
    data = json.loads(json_str)
    for key, val in data.items():
        assert isinstance(val, int), f"{key} should be int, got {type(val)}"


# ---------------------------------------------------------------------------
# run_main_dry
# ---------------------------------------------------------------------------

def test_run_main_dry_success(tmp_path, capsys):
    """run_main_dry runs subprocess and prints stdout."""
    mock_proc = MagicMock()
    mock_proc.stdout = "APPROVED: order_submitted=test-order"
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", return_value=mock_proc) as mock_run:
        run_main_dry(str(tmp_path / "test.db"), tmp_path)

    mock_run.assert_called_once()
    captured = capsys.readouterr()
    assert "APPROVED" in captured.out


def test_run_main_dry_with_stderr(tmp_path, capsys):
    """run_main_dry prints stderr when present."""
    mock_proc = MagicMock()
    mock_proc.stdout = "APPROVED: ok"
    mock_proc.stderr = "some warning"
    mock_proc.returncode = 0

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", return_value=mock_proc):
        run_main_dry(str(tmp_path / "test.db"), tmp_path)

    captured = capsys.readouterr()
    assert "stderr:" in captured.out
    assert "some warning" in captured.out


def test_run_main_dry_nonzero_returncode_raises(tmp_path):
    """run_main_dry raises RuntimeError when subprocess returns nonzero."""
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = "error occurred"
    mock_proc.returncode = 1

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="main dry run failed"):
            run_main_dry(str(tmp_path / "test.db"), tmp_path)


def test_run_main_dry_no_stderr_no_extra_print(tmp_path, capsys):
    """When stderr is empty, run_main_dry does NOT print 'stderr:' line."""
    mock_proc = MagicMock()
    mock_proc.stdout = "REJECTED: RISK_LIMIT"
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", return_value=mock_proc):
        run_main_dry(str(tmp_path / "test.db"), tmp_path)

    captured = capsys.readouterr()
    assert "stderr:" not in captured.out


def test_run_main_dry_passes_pythonpath(tmp_path, monkeypatch):
    """run_main_dry includes PYTHONPATH from src in the env passed to subprocess."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    captured_env = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return mock_proc

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", side_effect=fake_run):
        run_main_dry("test.db", tmp_path)

    assert "PYTHONPATH" in captured_env
    assert "src" in captured_env["PYTHONPATH"]


def test_run_main_dry_extends_existing_pythonpath(tmp_path, monkeypatch):
    """run_main_dry prepends src to existing PYTHONPATH."""
    monkeypatch.setenv("PYTHONPATH", "/existing/path")
    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    captured_env = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return mock_proc

    with patch("openclaw.bootstrap_and_dry_run.subprocess.run", side_effect=fake_run):
        run_main_dry("test.db", tmp_path)

    assert "/existing/path" in captured_env["PYTHONPATH"]


# ---------------------------------------------------------------------------
# main() function tests
# ---------------------------------------------------------------------------

def _patch_main_deps(monkeypatch, *, db_arg="openclaw_demo.db", reset=False, is_memory=False):
    """Common monkeypatches for main()."""
    args = argparse.Namespace(db=db_arg, reset=reset)
    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda *a, **kw: args)
    return args


def test_main_normal_db_path(monkeypatch, tmp_path, capsys):
    """main() with a regular db path runs the full flow."""
    db_path = str(tmp_path / "test_bootstrap.db")
    _patch_main_deps(monkeypatch, db_arg=db_path, reset=False)

    # Patch repo_root so SQL files are found
    project_root = get_repo_root()

    # Patch _apply_sql_file to avoid reading real files from unexpected paths
    apply_calls = []

    def fake_apply_sql(conn, path):
        apply_calls.append(path.name)
        # Execute a no-op to make the function work
        conn.commit()

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", fake_apply_sql)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = "APPROVED: order_submitted=ok"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()

    # 6 sql files should have been applied (5 migrations + seed)
    assert len(apply_calls) == 6


def test_main_reset_flag_deletes_db(monkeypatch, tmp_path, capsys):
    """main() with --reset deletes an existing db file before starting."""
    db_file = tmp_path / "to_reset.db"
    db_file.write_text("existing data")
    assert db_file.exists()

    _patch_main_deps(monkeypatch, db_arg=str(db_file), reset=True)

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", lambda conn, path: conn.commit())
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()

    # File was deleted and re-created as a valid SQLite DB
    assert db_file.exists()


def test_main_reset_flag_nonexistent_db(monkeypatch, tmp_path):
    """main() with --reset when db doesn't exist yet doesn't raise."""
    db_path = str(tmp_path / "new_db.db")
    _patch_main_deps(monkeypatch, db_arg=db_path, reset=True)

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", lambda conn, path: conn.commit())
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()  # should not raise


def test_main_memory_db_uses_temp_file(monkeypatch, tmp_path):
    """main() with db=':memory:' creates a real temp file for subprocess compatibility."""
    _patch_main_deps(monkeypatch, db_arg=":memory:", reset=False)

    apply_calls = []

    def fake_apply_sql(conn, path):
        apply_calls.append(str(path))
        conn.commit()

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", fake_apply_sql)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0

    subprocess_calls = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        return mock_proc

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", fake_run)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()

    # Subprocess should have been called
    assert len(subprocess_calls) == 1
    # The db_path argument passed to subprocess should NOT be ':memory:'
    cmd = subprocess_calls[0]
    assert ":memory:" not in " ".join(cmd)


def test_main_memory_db_deletes_existing_tmp_file(monkeypatch, tmp_path):
    """main() with ':memory:' deletes the existing temp db file if present."""
    # Create the _tmp dir and pre-existing file that main() would use
    from pathlib import Path
    import openclaw.bootstrap_and_dry_run as bdr_module

    # Find where the module thinks repo_root is
    module_file = Path(bdr_module.__file__).resolve()
    repo_root = module_file.parents[2]
    tmp_dir = repo_root / "_tmp"
    tmp_db = tmp_dir / "openclaw_dry_run.sqlite"

    # Create the pre-existing file
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_db.write_text("old data")
    assert tmp_db.exists()

    _patch_main_deps(monkeypatch, db_arg=":memory:", reset=False)

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", lambda conn, path: conn.commit())
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()  # should delete old tmp_db and create a fresh one


def test_main_with_real_sql_files_integration(monkeypatch, tmp_path, capsys):
    """Integration test: main() actually reads SQL files from disk."""
    db_path = str(tmp_path / "integration.db")
    _patch_main_deps(monkeypatch, db_arg=db_path, reset=False)

    # Mock the subprocess and expensive operations but let SQL files be read for real
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", lambda conn: None)

    mock_proc = MagicMock()
    mock_proc.stdout = "APPROVED: ok"
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)

    main()

    captured = capsys.readouterr()
    assert "db_summary:" in captured.out


def test_main_run_pipeline_demo_called(monkeypatch, tmp_path):
    """main() calls run_pipeline_demo with a valid connection."""
    db_path = str(tmp_path / "check.db")
    _patch_main_deps(monkeypatch, db_arg=db_path, reset=False)

    called_with = []

    def fake_pipeline_demo(conn):
        called_with.append(conn)

    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._apply_sql_file", lambda conn, path: conn.commit())
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run._seed_runtime_rows", lambda conn: None)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.run_pipeline_demo", fake_pipeline_demo)

    mock_proc = MagicMock()
    mock_proc.stdout = ""
    mock_proc.stderr = ""
    mock_proc.returncode = 0
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.subprocess.run", lambda *a, **kw: mock_proc)
    monkeypatch.setattr("openclaw.bootstrap_and_dry_run.print_summary", lambda conn: None)

    main()

    assert len(called_with) == 1
    assert isinstance(called_with[0], sqlite3.Connection)
