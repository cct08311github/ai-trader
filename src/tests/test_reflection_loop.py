import sqlite3

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
