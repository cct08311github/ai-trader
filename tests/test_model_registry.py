import sqlite3
from pathlib import Path

import pytest

from openclaw.model_registry import UnauthorizedModelError, is_model_allowed, resolve_pinned_model_id
from openclaw.decision_pipeline_v4 import run_pm_debate


def test_is_model_allowed_and_resolve():
    assert is_model_allowed("gemini-3.1-pro") is True
    pinned = resolve_pinned_model_id("gemini-3.1-pro")
    assert pinned.startswith("google/")

    assert is_model_allowed("not-a-real-model") is False
    with pytest.raises(UnauthorizedModelError) as e:
        resolve_pinned_model_id("not-a-real-model")
    assert e.value.code == "LLM_MODEL_NOT_ALLOWED"


def test_pipeline_blocks_unauthorized_model():
    conn = sqlite3.connect(":memory:")
    sql = (Path(__file__).resolve().parents[1] / "src" / "sql" / "migration_v1_2_0_observability_and_drawdown.sql").read_text(
        encoding="utf-8"
    )
    conn.executescript(sql)

    def llm_call(_model: str, _prompt: str):
        raise AssertionError("llm_call should not be invoked for unauthorized model")

    with pytest.raises(UnauthorizedModelError):
        run_pm_debate(conn, model="not-a-real-model", context={"x": 1}, llm_call=llm_call, decision_id="dec-1")
