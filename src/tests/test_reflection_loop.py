import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from openclaw.pm_debate import parse_debate_response, run_debate
from openclaw.reflection_loop import insert_reflection_run, validate_reflection_output


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE semantic_memory(rule_id TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE reflection_runs(
          run_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          stage1_diagnosis_json TEXT NOT NULL,
          stage2_abstraction_json TEXT NOT NULL,
          stage3_refinement_json TEXT NOT NULL,
          candidate_semantic_rules INTEGER NOT NULL DEFAULT 0,
          semantic_memory_size INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        INSERT INTO semantic_memory(rule_id, status) VALUES ('r1', 'active');
        """
    )
    return conn


def test_validate_and_insert_reflection():
    conn = _conn()
    out = validate_reflection_output(
        {
            "stage1_diagnosis": {"root_cause_code": "timing"},
            "stage2_abstraction": {"rule_text": "avoid chase", "confidence": 0.66},
            "stage3_refinement": {"decision": "proposal"},
        }
    )
    rid = insert_reflection_run(conn, "2026-02-27", out)
    row = conn.execute("SELECT candidate_semantic_rules, semantic_memory_size FROM reflection_runs WHERE run_id = ?", (rid,)).fetchone()
    assert row[0] == 1
    assert row[1] == 1


def test_validate_reflection_output_minimal():
    """正向測試：最簡輸出驗證。"""
    """正向測試：最簡輸出驗證。"""
    out = validate_reflection_output(
        {
            "stage1_diagnosis": {"root_cause_code": "test"},
            "stage2_abstraction": {"rule_text": "test", "confidence": 0.8},
            "stage3_refinement": {"decision": "proposal"},
        }
    )
    assert out.stage1_diagnosis["root_cause_code"] == "test"
    assert out.stage2_abstraction["rule_text"] == "test"
    assert out.stage3_refinement["decision"] == "proposal"
def test_insert_reflection_run_minimal():
    """正向測試：插入最簡反思運行。"""
    """正向測試：最簡插入。"""
    conn = _conn()
    out = validate_reflection_output(
        {
            "stage1_diagnosis": {"root_cause_code": "test"},
            "stage2_abstraction": {"rule_text": "test", "confidence": 0.8},
            "stage3_refinement": {"decision": "proposal"},
        }
    )
    rid = insert_reflection_run(conn, "2026-02-27", out)
    row = conn.execute("SELECT candidate_semantic_rules, semantic_memory_size FROM reflection_runs WHERE run_id = ?", (rid,)).fetchone()
    assert row[0] == 1
    assert row[1] == 1


# ── pm_debate tests ────────────────────────────────────────────────────────────

def test_parse_debate_response_non_list_consensus():
    """Line 94: consensus_points is a non-empty non-list value -> wrapped in list."""
    result = parse_debate_response({
        "bull_case": "up",
        "bear_case": "down",
        "neutral_case": "sideways",
        "consensus_points": "single consensus string",
        "divergence_points": ["d1"],
        "recommended_action": "observe",
        "confidence": 0.6,
    })
    assert result.consensus_points == ["single consensus string"]


def test_parse_debate_response_non_list_consensus_empty():
    """Line 94: consensus_points is a falsy non-list value -> empty list."""
    result = parse_debate_response({
        "bull_case": "up",
        "bear_case": "down",
        "neutral_case": "sideways",
        "consensus_points": "",
        "divergence_points": ["d1"],
        "recommended_action": "observe",
        "confidence": 0.5,
    })
    assert result.consensus_points == []


def test_parse_debate_response_non_list_divergence():
    """Line 98: divergence_points is a non-empty non-list value -> wrapped in list."""
    result = parse_debate_response({
        "bull_case": "up",
        "bear_case": "down",
        "neutral_case": "sideways",
        "consensus_points": ["c1"],
        "divergence_points": "single divergence string",
        "recommended_action": "observe",
        "confidence": 0.7,
    })
    assert result.divergence_points == ["single divergence string"]


def test_parse_debate_response_non_list_divergence_empty():
    """Line 98: divergence_points is a falsy non-list value -> empty list."""
    result = parse_debate_response({
        "bull_case": "up",
        "bear_case": "down",
        "neutral_case": "sideways",
        "consensus_points": ["c1"],
        "divergence_points": 0,
        "recommended_action": "observe",
        "confidence": 0.5,
    })
    assert result.divergence_points == []


def test_run_debate_passthrough():
    """Lines 131-133: run_debate builds prompt, calls llm_call, returns parsed result."""
    fake_llm_response = {
        "bull_case": "buy",
        "bear_case": "sell",
        "neutral_case": "hold",
        "consensus_points": ["stay calm"],
        "divergence_points": ["timing"],
        "recommended_action": "observe",
        "confidence": 0.75,
        "adjudication": "neutral",
    }

    calls = []

    def fake_llm_call(model: str, prompt: str):
        calls.append((model, prompt))
        return fake_llm_response

    context = {"symbol": "2330", "price": 900}
    result = run_debate(context, fake_llm_call, model="test-model")

    assert len(calls) == 1
    assert calls[0][0] == "test-model"
    assert "2330" in calls[0][1]
    assert result.recommended_action == "observe"
    assert result.confidence == 0.75


# ── _column_exists ─────────────────────────────────────────────────────────────

def test_column_exists_true():
    """Lines 13-21: _column_exists returns True when column found."""
    from openclaw.reflection_loop import _column_exists
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id TEXT, name TEXT)")
    assert _column_exists(conn, "t", "name") is True


def test_column_exists_false_missing_column():
    """Line 22: _column_exists returns False when column not found."""
    from openclaw.reflection_loop import _column_exists
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id TEXT)")
    assert _column_exists(conn, "t", "nonexistent") is False


def test_column_exists_exception():
    """Lines 17-18: _column_exists returns False when PRAGMA raises."""
    from openclaw.reflection_loop import _column_exists
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("db error")
    assert _column_exists(mock_conn, "t", "col") is False


# ── _table_exists ──────────────────────────────────────────────────────────────

def test_table_exists_true():
    """Lines 25-29: _table_exists returns True when table found."""
    from openclaw.reflection_loop import _table_exists
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE foo (x INT)")
    assert _table_exists(conn, "foo") is True


def test_table_exists_false():
    """Lines 25-29: _table_exists returns False when table not found."""
    from openclaw.reflection_loop import _table_exists
    conn = sqlite3.connect(":memory:")
    assert _table_exists(conn, "nonexistent") is False


# ── validate_reflection_output ─────────────────────────────────────────────────

def test_validate_missing_key_raises():
    """Line 42: raises ValueError when key is missing."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError, match="missing or invalid stage1_diagnosis"):
        validate_reflection_output({
            "stage2_abstraction": {"rule_text": "t", "confidence": 0.5},
            "stage3_refinement": {"decision": "proposal"},
        })


def test_validate_non_dict_value_raises():
    """Line 42: raises ValueError when value is not a dict."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError):
        validate_reflection_output({
            "stage1_diagnosis": "not_a_dict",
            "stage2_abstraction": {"rule_text": "t", "confidence": 0.5},
            "stage3_refinement": {"decision": "proposal"},
        })


def test_validate_missing_root_cause_code():
    """Line 49: raises ValueError when root_cause_code missing from stage1."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError, match="root_cause_code"):
        validate_reflection_output({
            "stage1_diagnosis": {},  # missing root_cause_code
            "stage2_abstraction": {"rule_text": "t", "confidence": 0.5},
            "stage3_refinement": {"decision": "proposal"},
        })


def test_validate_missing_rule_text():
    """Line 51: raises ValueError when rule_text or confidence missing from stage2."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError, match="rule_text/confidence"):
        validate_reflection_output({
            "stage1_diagnosis": {"root_cause_code": "x"},
            "stage2_abstraction": {"confidence": 0.5},  # missing rule_text
            "stage3_refinement": {"decision": "proposal"},
        })


def test_validate_missing_confidence():
    """Line 51: raises ValueError when confidence missing from stage2."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError, match="rule_text/confidence"):
        validate_reflection_output({
            "stage1_diagnosis": {"root_cause_code": "x"},
            "stage2_abstraction": {"rule_text": "t"},  # missing confidence
            "stage3_refinement": {"decision": "proposal"},
        })


def test_validate_missing_decision():
    """Line 53: raises ValueError when decision missing from stage3."""
    from openclaw.reflection_loop import validate_reflection_output
    with pytest.raises(ValueError, match="decision"):
        validate_reflection_output({
            "stage1_diagnosis": {"root_cause_code": "x"},
            "stage2_abstraction": {"rule_text": "t", "confidence": 0.5},
            "stage3_refinement": {},  # missing decision
        })


# ── insert_reflection_run (else branch, no created_at column) ─────────────────

def _conn_no_created_at() -> sqlite3.Connection:
    """reflection_runs table WITHOUT created_at column."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE semantic_memory(rule_id TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE reflection_runs(
          run_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          stage1_diagnosis_json TEXT NOT NULL,
          stage2_abstraction_json TEXT NOT NULL,
          stage3_refinement_json TEXT NOT NULL,
          candidate_semantic_rules INTEGER NOT NULL DEFAULT 0,
          semantic_memory_size INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO semantic_memory(rule_id, status) VALUES ('r1', 'active');
        """
    )
    return conn


def test_insert_reflection_run_no_created_at_column():
    """Line 85: uses INSERT without created_at when column is absent."""
    conn = _conn_no_created_at()
    out = validate_reflection_output({
        "stage1_diagnosis": {"root_cause_code": "timing"},
        "stage2_abstraction": {"rule_text": "avoid chase", "confidence": 0.66},
        "stage3_refinement": {"decision": "proposal"},
    })
    rid = insert_reflection_run(conn, "2026-02-27", out)
    row = conn.execute(
        "SELECT candidate_semantic_rules, semantic_memory_size FROM reflection_runs WHERE run_id = ?", (rid,)
    ).fetchone()
    assert row[0] == 1
    assert row[1] == 1


# ── check_reflection_threshold ─────────────────────────────────────────────────

def test_check_reflection_threshold_above():
    """Lines 114-116: confidence >= 0.7 -> True."""
    from openclaw.reflection_loop import check_reflection_threshold
    assert check_reflection_threshold({"confidence": 0.7}) is True
    assert check_reflection_threshold({"confidence": 0.9}) is True


def test_check_reflection_threshold_below():
    """Lines 114-116: confidence < 0.7 -> False."""
    from openclaw.reflection_loop import check_reflection_threshold
    assert check_reflection_threshold({"confidence": 0.69}) is False
    assert check_reflection_threshold({}) is False  # default 0.0 < 0.7


# ── create_proposal_from_reflection ───────────────────────────────────────────

def test_create_proposal_import_error():
    """Lines 126-131: ImportError -> returns None."""
    from openclaw.reflection_loop import create_proposal_from_reflection, ReflectionOutput

    conn = sqlite3.connect(":memory:")
    result = ReflectionOutput(
        stage1_diagnosis={"root_cause_code": "x"},
        stage2_abstraction={"rule_text": "t", "confidence": 0.8, "rule_category": "entry"},
        stage3_refinement={"decision": {"action": "propose"}},
    )

    with patch("openclaw.reflection_loop.__builtins__", {}), \
         patch.dict("sys.modules", {"openclaw.proposal_engine": None}):
        import sys
        original = sys.modules.get("openclaw.proposal_engine")
        sys.modules["openclaw.proposal_engine"] = None  # type: ignore
        try:
            pid = create_proposal_from_reflection(conn, result, "2026-01-01")
            # Without strategy_proposals table, returns None
            assert pid is None
        finally:
            if original is None:
                sys.modules.pop("openclaw.proposal_engine", None)
            else:
                sys.modules["openclaw.proposal_engine"] = original


def test_create_proposal_no_strategy_proposals_table():
    """Lines 134-135: strategy_proposals table absent -> returns None."""
    from openclaw.reflection_loop import create_proposal_from_reflection, ReflectionOutput

    conn = sqlite3.connect(":memory:")
    result = ReflectionOutput(
        stage1_diagnosis={"root_cause_code": "x"},
        stage2_abstraction={"rule_text": "t", "confidence": 0.8, "rule_category": "entry"},
        stage3_refinement={"decision": {"action": "propose"}},
    )
    pid = create_proposal_from_reflection(conn, result, "2026-01-01")
    assert pid is None


def test_create_proposal_with_strategy_proposals_table():
    """Lines 137-168: creates proposal when strategy_proposals table exists."""
    from openclaw.reflection_loop import create_proposal_from_reflection, ReflectionOutput

    conn = sqlite3.connect(":memory:")
    # Create strategy_proposals table (real schema from proposal_engine)
    conn.execute("""
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            auto_approve INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            decided_by TEXT,
            decision_reason TEXT,
            proposal_json TEXT NOT NULL DEFAULT '{}'
        )
    """)

    result = ReflectionOutput(
        stage1_diagnosis={"root_cause_code": "timing"},
        stage2_abstraction={
            "rule_text": "buy_threshold adjustment",
            "rule_category": "entry_parameters",
            "confidence": 0.85,
        },
        stage3_refinement={
            "decision": {
                "action": "propose",
                "current_value": "0.02",
                "proposed_value": "0.025",
                "supporting_evidence": "Backtest shows improvement",
            }
        },
    )
    pid = create_proposal_from_reflection(conn, result, "2026-01-01")
    assert pid is not None


def test_create_proposal_non_dict_decision():
    """Line 148-149: decision is not a dict -> converted to raw dict."""
    from openclaw.reflection_loop import create_proposal_from_reflection, ReflectionOutput

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            auto_approve INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            decided_by TEXT,
            decision_reason TEXT,
            proposal_json TEXT NOT NULL DEFAULT '{}'
        )
    """)

    result = ReflectionOutput(
        stage1_diagnosis={"root_cause_code": "x"},
        stage2_abstraction={"rule_text": "t", "confidence": 0.8, "rule_category": "misc"},
        stage3_refinement={"decision": "proposal"},  # non-dict decision
    )
    # Should not raise
    pid = create_proposal_from_reflection(conn, result, "2026-01-01")
    assert pid is not None


# ── record_day_episode ─────────────────────────────────────────────────────────

def test_record_day_episode_no_table():
    """Lines 173-181: episodic_memory table absent -> returns episode_id without inserting."""
    from openclaw.reflection_loop import record_day_episode

    conn = sqlite3.connect(":memory:")
    eid = record_day_episode(conn, "2026-01-01", "abc12345")
    assert eid == "day_2026-01-01_abc12345"


def test_record_day_episode_with_table():
    """Lines 183-192: inserts into episodic_memory when table exists."""
    from openclaw.reflection_loop import record_day_episode

    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            reflection_id TEXT,
            recorded_at TEXT NOT NULL
        )
    """)

    eid = record_day_episode(conn, "2026-01-01", "abc12345")
    assert eid == "day_2026-01-01_abc12345"
    row = conn.execute("SELECT episode_type, trade_date FROM episodic_memory WHERE episode_id = ?", (eid,)).fetchone()
    assert row is not None
    assert row[0] == "day"
    assert row[1] == "2026-01-01"


# ── run_daily_reflection ───────────────────────────────────────────────────────

def _full_conn() -> sqlite3.Connection:
    """Full in-memory DB with all required tables for run_daily_reflection."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE semantic_memory(rule_id TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE reflection_runs(
          run_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          stage1_diagnosis_json TEXT NOT NULL,
          stage2_abstraction_json TEXT NOT NULL,
          stage3_refinement_json TEXT NOT NULL,
          candidate_semantic_rules INTEGER NOT NULL DEFAULT 0,
          semantic_memory_size INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE episodic_memory (
            episode_id TEXT PRIMARY KEY,
            episode_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            reflection_id TEXT,
            recorded_at TEXT NOT NULL
        );
        INSERT INTO semantic_memory(rule_id, status) VALUES ('r1', 'active');
    """)
    return conn


def test_run_daily_reflection_no_strategy_proposals():
    """Lines 201-252: run_daily_reflection executes without strategy_proposals -> proposal_id=None."""
    from openclaw.reflection_loop import run_daily_reflection

    conn = _full_conn()
    result = run_daily_reflection(conn, "2026-02-28")
    assert "run_id" in result
    assert "episode_id" in result
    assert result["threshold_passed"] is True
    # No strategy_proposals table -> proposal_id=None
    assert result["proposal_id"] is None


def test_run_daily_reflection_with_strategy_proposals():
    """Lines 201-252: run_daily_reflection creates proposal when strategy_proposals exists."""
    from openclaw.reflection_loop import run_daily_reflection

    conn = _full_conn()
    conn.execute("""
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            rule_category TEXT NOT NULL,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            auto_approve INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT,
            decided_by TEXT,
            decision_reason TEXT,
            proposal_json TEXT NOT NULL DEFAULT '{}'
        )
    """)

    result = run_daily_reflection(conn, "2026-02-28")
    assert "run_id" in result
    assert result["threshold_passed"] is True
    assert result["proposal_id"] is not None


def test_run_daily_reflection_below_threshold():
    """Lines 241-242: else branch when threshold is not passed (confidence < 0.7)."""
    from openclaw.reflection_loop import run_daily_reflection
    import openclaw.reflection_loop as rl_module

    conn = _full_conn()
    # Patch check_reflection_threshold to return False so the else branch runs
    original_fn = rl_module.check_reflection_threshold
    rl_module.check_reflection_threshold = lambda s2: False
    try:
        result = run_daily_reflection(conn, "2026-02-28")
        assert result["threshold_passed"] is False
        assert result["proposal_id"] is None
    finally:
        rl_module.check_reflection_threshold = original_fn
