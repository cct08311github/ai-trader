from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
import subprocess
from datetime import datetime
from pathlib import Path

from openclaw.decision_pipeline import run_news_sentiment_with_guard, run_pm_debate
from openclaw.memory_store import EpisodicRecord, SemanticRule, insert_episodic_memory, upsert_semantic_rule
from openclaw.reflection_loop import insert_reflection_run, validate_reflection_output


def _apply_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    sql_text = path.read_text(encoding="utf-8")
    conn.executescript(sql_text)
    conn.commit()


def _seed_runtime_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_pnl_summary (
          trade_date, nav_start, nav_end, realized_pnl, unrealized_pnl, total_pnl,
          daily_return, rolling_peak_nav, rolling_drawdown, losing_streak_days, risk_mode
        ) VALUES (date('now'), 1000000, 995000, -5000, 0, -5000, -0.005, 1020000, 0.0245, 1, 'normal')
        """
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO strategy_health (
          strategy_id, as_of_ts, rolling_trades, rolling_win_rate, enabled, note
        ) VALUES ('breakout', datetime('now'), 30, 0.52, 1, 'healthy')
        """
    )
    # Demo tuning so one order can pass through full lifecycle path.
    conn.execute(
        """
        UPDATE risk_limits
        SET rule_value = 0.50, updated_at = datetime('now')
        WHERE rule_name = 'max_symbol_weight' AND scope IN ('global', 'symbol')
        """
    )
    conn.commit()


def _mock_llm_call(model: str, prompt: str) -> dict:
    if "bull_case" in prompt:
        return {
            "bull_case": "volume expansion confirms trend",
            "bear_case": "macro risk remains elevated",
            "adjudication": "small long with tight stop",
            "confidence": 0.64,
            "input_tokens": 180,
            "output_tokens": 95,
            "latency_ms": 420,
        }
    return {
        "score": 0.3,
        "direction": "bullish",
        "confidence": 0.58,
        "input_tokens": 120,
        "output_tokens": 40,
        "latency_ms": 210,
    }


def run_pipeline_demo(conn: sqlite3.Connection) -> None:
    news_result = run_news_sentiment_with_guard(
        conn,
        model="gemini-3.0-flash",
        raw_news_text="台積電法說會優於預期，市場看法偏多",
        llm_call=_mock_llm_call,
        decision_id="demo-decision-001",
    )
    debate_result = run_pm_debate(
        conn,
        model="gemini-3.1-pro",
        context={"symbol": "2330", "news": news_result},
        llm_call=_mock_llm_call,
        decision_id="demo-decision-001",
    )
    episode_id = insert_episodic_memory(
        conn,
        EpisodicRecord(
            trade_date=datetime.now().strftime("%Y-%m-%d"),
            symbol="2330",
            strategy_id="breakout",
            market_regime="trending",
            entry_reason="volume breakout",
            outcome_pnl=1200.0,
            pm_score=0.72,
            root_cause_code="timing",
        ),
    )
    upsert_semantic_rule(
        conn,
        SemanticRule(
            rule_text="When foreign buy streak >=3 days and trend is strong, reduce chase at open.",
            confidence=0.68,
            source_episodes=[episode_id],
            sample_count=1,
            last_validated_date=datetime.now().strftime("%Y-%m-%d"),
            status="review",
        ),
    )
    insert_reflection_run(
        conn,
        datetime.now().strftime("%Y-%m-%d"),
        validate_reflection_output(
            {
                "stage1_diagnosis": {"root_cause_code": "timing", "note": "open session false breakout"},
                "stage2_abstraction": {"rule_text": "avoid first 15 min chase", "confidence": 0.66},
                "stage3_refinement": {"decision": "proposal", "note": "raise open threshold"},
            }
        ),
    )

    conn.execute(
        """
        INSERT INTO strategy_proposals (
          proposal_id, generated_by, target_rule, rule_category,
          current_value, proposed_value, supporting_evidence,
          source_episodes_json, backtest_sharpe_before, backtest_sharpe_after,
          confidence, semantic_memory_action, rollback_version,
          requires_human_approval, auto_approve_eligible, expires_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{datetime.now().strftime('%Y%m%d')}-001",
            "PM_ReflectionLoop_23:00",
            "open_session_entry_threshold",
            "entry_threshold",
            "2.0%",
            "3.5%",
            "false breakout ratio increased in last 10 sessions",
            json.dumps([episode_id] * 20, ensure_ascii=True),
            0.82,
            1.14,
            0.88,
            "UPDATE",
            "v2026-02-20",
            1,
            0,
            datetime.now().strftime("%Y-%m-%d"),
            "pending",
        ),
    )
    # Ensure demo rows exist for tables that the main pipeline might not touch in one run.
    conn.execute(
        "INSERT OR REPLACE INTO working_memory(mem_key, mem_value_json, updated_at) VALUES (?, ?, datetime('now'))",
        ("demo", json.dumps({"note": "bootstrap"}, ensure_ascii=True)),
    )
    conn.execute(
        "INSERT INTO incidents(incident_id, ts, severity, source, code, detail_json, resolved)"
        " VALUES (?, datetime('now'), ?, ?, ?, ?, 0)",
        (str(uuid.uuid4()), "info", "bootstrap", "DEMO_INCIDENT", json.dumps({"msg": "dry run"}, ensure_ascii=True)),
    )

    conn.commit()
    print("pipeline_demo:", json.dumps({"news": news_result, "debate": debate_result}, ensure_ascii=True))


def run_main_dry(db_path: str, repo_root: Path) -> None:
    cmd = ["python3", "-m", "openclaw.main", "--db", db_path]
    env = dict(**__import__('os').environ)
    env['PYTHONPATH'] = str(repo_root / 'src') + ((':' + env['PYTHONPATH']) if env.get('PYTHONPATH') else '')
    proc = subprocess.run(cmd, cwd=str(repo_root), check=False, text=True, capture_output=True, env=env)
    print(proc.stdout.strip())
    if proc.stderr.strip():
        print("stderr:", proc.stderr.strip())
    if proc.returncode != 0:
        raise RuntimeError(f"main dry run failed: rc={proc.returncode}")


def print_summary(conn: sqlite3.Connection) -> None:
    tables = [
        "llm_traces",
        "working_memory",
        "episodic_memory",
        "semantic_memory",
        "reflection_runs",
        "strategy_proposals",
        "decisions",
        "risk_checks",
        "orders",
        "fills",
        "order_events",
        "incidents",
    ]
    summary = {}
    for t in tables:
        row = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        summary[t] = int(row[0] if row else 0)
    print("db_summary:", json.dumps(summary, ensure_ascii=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap OpenClaw DB and run one dry-run cycle.")
    parser.add_argument("--db", default="openclaw_demo.db", help="SQLite db path for demo")
    parser.add_argument("--reset", action="store_true", help="Remove db file before bootstrap")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]

    # NOTE: support SQLite in-memory db for CI / quick validation
    if args.db == ':memory:':
        # Use a temp *file* DB so the subsequent subprocess (openclaw.main) can read the same data.
        tmp_dir = repo_root / '_tmp'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        db_file = tmp_dir / 'openclaw_dry_run.sqlite'
        if db_file.exists():
            db_file.unlink()
        db_path = str(db_file)
    else:
        db_file = Path(args.db).resolve()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        if args.reset and db_file.exists():
            db_file.unlink()
        db_path = str(db_file)

    sql_dir = repo_root / 'src' / 'sql'

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    migration_files = [
        sql_dir / "migration_v1_1_0_core.sql",
        sql_dir / "migration_v1_1_1_order_events.sql",
        sql_dir / "migration_v1_2_0_observability_and_drawdown.sql",
        sql_dir / "migration_v1_2_1_eod_data.sql",
        sql_dir / "migration_v1_2_2_memory_reflection_proposals.sql",
    ]
    for m in migration_files:
        _apply_sql_file(conn, m)
    _apply_sql_file(conn, sql_dir / "risk_limits_seed_v1_1.sql")
    _seed_runtime_rows(conn)

    run_pipeline_demo(conn)
    run_main_dry(db_path, repo_root)
    print_summary(conn)


if __name__ == "__main__":
    main()
