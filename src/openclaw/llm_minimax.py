"""llm_minimax.py — MiniMax LLM adapter（OpenAI-compatible API）。

LLM 呼叫介面：
    minimax_call(model, prompt) -> dict

Env:
    MINIMAX_API_KEY — 從 frontend/backend/.env 或環境變數載入。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict

import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://api.minimax.io/v1"
_DEFAULT_MODEL = "MiniMax-M2.7"
_TIMEOUT = 120  # seconds


def _extract_json(text: str) -> Dict[str, Any]:
    """從 LLM 回應文字中提取 JSON dict。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Cannot parse JSON from MiniMax response: {text[:300]}")


_LATENCY_WARN_MS = int(os.environ.get("LLM_LATENCY_WARN_MS", "30000"))  # 30s default


def minimax_call(model: str, prompt: str, temperature: float = 0.1) -> Dict[str, Any]:
    """呼叫 MiniMax，回傳解析後的 JSON dict。

    Args:
        model: MiniMax 模型 ID，e.g. "MiniMax-M2.7"。
        prompt: 完整 prompt 字串。
        temperature: 生成溫度，預設 0.1（#391: 降低決策隨機性）。

    Returns:
        解析後的 dict，包含 '_raw_response', '_prompt', '_latency_ms', '_model'。

    Raises:
        RuntimeError: MINIMAX_API_KEY 未設定。
        ValueError: 回應無法解析為 JSON。
        requests.HTTPError: API 回傳非 2xx 狀態碼。
    """
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        # 嘗試從 frontend/backend/.env 讀取
        _load_minimax_key_from_dotenv()
        api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY 未設定（請在 frontend/backend/.env 設定）")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": 16384,
    }

    t0 = time.time()
    resp = requests.post(
        f"{_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    latency_ms = int((time.time() - t0) * 1000)

    body = resp.json()
    raw_text = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {})

    parsed = _extract_json(raw_text)

    if isinstance(parsed, list):
        result: Dict[str, Any] = {"items": parsed}
    else:
        result = parsed

    result["_prompt"] = prompt
    result["_raw_response"] = raw_text
    result["_latency_ms"] = latency_ms
    result["_model"] = model
    result["_temperature"] = temperature
    result["_input_tokens"] = usage.get("prompt_tokens", 0)
    result["_output_tokens"] = usage.get("completion_tokens", 0)

    # Latency warning (#391)
    if latency_ms > _LATENCY_WARN_MS:
        log.warning(
            "LLM call slow: model=%s latency=%dms (threshold=%dms) tokens_in=%d tokens_out=%d",
            model, latency_ms, _LATENCY_WARN_MS,
            result["_input_tokens"], result["_output_tokens"],
        )

    return result


def _load_minimax_key_from_dotenv() -> None:
    """嘗試從 frontend/backend/.env 載入 MINIMAX_API_KEY 至環境變數。"""
    from openclaw.path_utils import get_repo_root
    dotenv_path = get_repo_root() / "frontend" / "backend" / ".env"
    if not dotenv_path.exists():
        return
    try:
        with open(dotenv_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("MINIMAX_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    os.environ["MINIMAX_API_KEY"] = val
                    break
    except OSError:
        pass
