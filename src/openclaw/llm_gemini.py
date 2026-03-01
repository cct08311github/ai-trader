"""llm_gemini.py — Gemini LLM adapter for PM debate system.

Implements the llm_call(model, prompt) -> dict interface expected by
run_daily_pm_review() and run_debate().

Usage:
    from openclaw.llm_gemini import gemini_call
    state = run_daily_pm_review(context=ctx, llm_call=gemini_call, model="gemini-2.0-flash")

Env:
    GEMINI_API_KEY — required, set in .env or environment.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict


def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON dict from raw LLM response text.

    Handles:
    - Raw JSON
    - Markdown code blocks (```json ... ```)
    - JSON embedded in prose
    """
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fence
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Find first JSON object
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Cannot parse JSON from Gemini response: {text[:300]}")


def gemini_call(model: str, prompt: str) -> Dict[str, Any]:
    """Call Gemini and return parsed JSON dict.

    Args:
        model: Gemini model ID, e.g. "gemini-3.1-pro-preview".
        prompt: Full prompt string (built by build_debate_prompt).

    Returns:
        Parsed dict matching DebateDecisionV2 fields.
        Also includes '_raw_response' and '_prompt' for transparency logging.

    Raises:
        RuntimeError: GEMINI_API_KEY not set.
        ValueError: Response is not valid JSON.
    """
    import time
    import google.generativeai as genai  # lazy import

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in environment or .env")

    genai.configure(api_key=api_key)
    gen_model = genai.GenerativeModel(
        model,
        generation_config={"response_mime_type": "application/json"},
    )
    t0 = time.time()
    response = gen_model.generate_content(prompt)
    latency_ms = int((time.time() - t0) * 1000)

    raw_text = response.text
    result = _extract_json(raw_text)

    # Attach metadata for caller to log to llm_traces
    result["_prompt"] = prompt
    result["_raw_response"] = raw_text
    result["_latency_ms"] = latency_ms
    result["_model"] = model

    return result
