"""Daily smoke test for model allowlist + observability logging.

We do NOT call external LLM providers here; instead we validate:
- model pinning (alias -> pinned resolution) wiring
- response/tool payload shapes
- llm_traces persistence with metadata.smoke=true
"""

import json
import sqlite3
from pathlib import Path

from openclaw.decision_pipeline_v4 import run_news_sentiment_with_guard, run_pm_debate
from openclaw.llm_observability import LLMTrace, insert_llm_trace
from openclaw.model_registry import resolve_pinned_model_id


def test_smoke_llm_traces_and_tool_format():
    conn = sqlite3.connect(":memory:")
    migration = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sql"
        / "migration_v1_2_0_observability_and_drawdown.sql"
    ).read_text(encoding="utf-8")
    conn.executescript(migration)

    seen = {"models": []}

    def fake_llm_call(model: str, prompt: str):
        assert model.startswith("google/")
        assert isinstance(prompt, str) and prompt
        seen["models"].append(model)
        if "bull_case" in prompt:
            return {
                "bull_case": "ok",
                "bear_case": "ok",
                "adjudication": "ok",
                "confidence": 0.66,
                "input_tokens": 10,
                "output_tokens": 20,
                "latency_ms": 3,
            }
        return {
            "score": 0.2,
            "direction": "bullish",
            "confidence": 0.55,
            "input_tokens": 11,
            "output_tokens": 5,
            "latency_ms": 4,
        }

    model_alias_flash = "gemini-3.0-flash"
    model_alias_pro = "gemini-3.1-pro"

    news = run_news_sentiment_with_guard(
        conn,
        model=model_alias_flash,
        raw_news_text="台積電法說會優於預期，市場看法偏多",
        llm_call=fake_llm_call,
        decision_id="smoke-dec-001",
    )
    assert "confidence" in news

    debate = run_pm_debate(
        conn,
        model=model_alias_pro,
        context={"symbol": "2330", "news": news, "bull_case": True},
        llm_call=fake_llm_call,
        decision_id="smoke-dec-001",
    )
    assert "adjudication" in debate

    assert resolve_pinned_model_id(model_alias_flash) in seen["models"]
    assert resolve_pinned_model_id(model_alias_pro) in seen["models"]

    smoke_trace_id = insert_llm_trace(
        conn,
        LLMTrace(
            component="smoke",
            model=model_alias_pro,
            prompt_text="SMOKE: validate tool call persistence",
            response_text=json.dumps({"ok": True}, ensure_ascii=True),
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            tools=[{"name": "dummy_tool", "args": {"x": 1}, "result": {"y": 2}}],
            confidence=1.0,
            decision_id="smoke-dec-001",
            metadata={"smoke": True},
        ),
    )

    row = conn.execute(
        "SELECT component, model, tools_json, metadata_json FROM llm_traces WHERE trace_id = ?",
        (smoke_trace_id,),
    ).fetchone()
    assert row is not None

    tools = json.loads(row[2])
    meta = json.loads(row[3])
    assert isinstance(tools, list) and tools and tools[0]["name"] == "dummy_tool"
    assert meta.get("smoke") is True
