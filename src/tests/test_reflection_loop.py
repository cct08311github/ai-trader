import sqlite3

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
