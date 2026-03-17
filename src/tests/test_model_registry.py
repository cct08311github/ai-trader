"""Tests for model_registry.py — 0% → 100% coverage."""
import sqlite3
from pathlib import Path

import pytest

from openclaw.decision_pipeline_v4 import run_pm_debate
from openclaw.path_utils import get_repo_root
from openclaw.model_registry import (
    ALLOWED_MODELS,
    UnauthorizedModelError,
    is_model_allowed,
    resolve_pinned_model_id,
)


def test_is_model_allowed_canonical():
    assert is_model_allowed("google/gemini-1.5-pro-002") is True
    assert is_model_allowed("google/gemini-1.5-flash-002") is True
    assert is_model_allowed("google/gemini-3.0-flash-001") is True


def test_is_model_allowed_alias():
    assert is_model_allowed("gemini-3.1-pro") is True
    assert is_model_allowed("gemini-3.0-flash") is True


def test_is_model_allowed_unknown():
    assert is_model_allowed("gpt-4o") is False
    assert is_model_allowed("claude-3-5-sonnet") is False
    assert is_model_allowed("") is False


def test_is_model_allowed_non_string():
    assert is_model_allowed(None) is False   # type: ignore[arg-type]
    assert is_model_allowed(42) is False      # type: ignore[arg-type]


def test_is_model_allowed_strips_whitespace():
    # is_model_allowed strips input internally → whitespace-padded canonical ids are accepted
    assert is_model_allowed("  google/gemini-1.5-pro-002  ") is True


def test_resolve_pinned_returns_canonical():
    pinned = resolve_pinned_model_id("gemini-3.1-pro")
    assert pinned == "google/gemini-3.1-pro-001"


def test_resolve_pinned_canonical_passthrough():
    pinned = resolve_pinned_model_id("google/gemini-1.5-flash-002")
    assert pinned == "google/gemini-1.5-flash-002"


def test_resolve_pinned_raises_on_unknown():
    with pytest.raises(UnauthorizedModelError) as exc_info:
        resolve_pinned_model_id("gpt-4o")
    err = exc_info.value
    assert err.code == "LLM_MODEL_NOT_ALLOWED"
    assert err.model_id == "gpt-4o"
    assert "gpt-4o" not in err.allowed_models


def test_resolve_pinned_raises_on_empty():
    with pytest.raises(UnauthorizedModelError):
        resolve_pinned_model_id("")


def test_resolve_pinned_all_allowed_models_resolvable():
    for model_id in ALLOWED_MODELS:
        pinned = resolve_pinned_model_id(model_id)
        assert isinstance(pinned, str)
        assert pinned  # non-empty


def test_pipeline_blocks_unauthorized_model():
    conn = sqlite3.connect(":memory:")
    sql = (
        get_repo_root()
        / "src"
        / "sql"
        / "migration_v1_2_0_observability_and_drawdown.sql"
    ).read_text(encoding="utf-8")
    conn.executescript(sql)

    def llm_call(_model: str, _prompt: str):
        raise AssertionError("llm_call should not be invoked for unauthorized model")

    with pytest.raises(UnauthorizedModelError):
        run_pm_debate(conn, model="not-a-real-model", context={"x": 1}, llm_call=llm_call, decision_id="dec-1")
