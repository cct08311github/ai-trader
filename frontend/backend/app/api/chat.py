"""chat.py — AI 對話路由.

Endpoints:
  GET  /api/chat/history         最近 50 條對話（llm_traces agent='chat'）
  POST /api/chat/message         送訊息，回傳 SSE 串流（StreamingResponse）
  POST /api/chat/create-proposal 從對話建立策略提案
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db import READONLY_POOL
from app.services.chat_context import build_chat_context, parse_proposal_intent

router = APIRouter(prefix="/api/chat", tags=["Chat"])

# ─── Models ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []   # [{role: "user"|"assistant", content: "..."}]

class ProposalRequest(BaseModel):
    ai_response: str
    user_message: str

# ─── LLM provider selection ──────────────────────────────────────────────────

def _get_chat_model() -> str:
    """Read CHAT_LLM_MODEL at request time (same pattern as PM_LLM_MODEL)."""
    return os.environ.get("CHAT_LLM_MODEL", "")


async def _stream_claude(system: str, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
    """Stream response from Anthropic Claude."""
    import anthropic  # pragma: no cover
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()  # pragma: no cover
    if not api_key:  # pragma: no cover
        raise ValueError("ANTHROPIC_API_KEY not set")  # pragma: no cover
    client = anthropic.Anthropic(api_key=api_key)  # pragma: no cover
    with client.messages.stream(  # pragma: no cover
        model=model,
        max_tokens=1000,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:  # pragma: no cover
            yield text  # pragma: no cover


async def _stream_gemini(system: str, messages: list[dict], model: str) -> AsyncGenerator[str, None]:
    """Stream response from Google Gemini."""
    import google.generativeai as genai  # pragma: no cover
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()  # pragma: no cover
    if not api_key:  # pragma: no cover
        raise ValueError("GEMINI_API_KEY not set")  # pragma: no cover
    genai.configure(api_key=api_key)  # pragma: no cover
    # Prepend system as first user turn (Gemini doesn't have native system prompt in same way)
    gemini_messages = [{"role": "user", "parts": [system]},  # pragma: no cover
                       {"role": "model", "parts": ["了解，我是 OpenClaw AI 交易助手。"]}]
    for msg in messages:  # pragma: no cover
        role = "user" if msg["role"] == "user" else "model"  # pragma: no cover
        gemini_messages.append({"role": role, "parts": [msg["content"]]})  # pragma: no cover
    gmodel = genai.GenerativeModel(model)  # pragma: no cover
    response = gmodel.generate_content(  # pragma: no cover
        gemini_messages,
        stream=True,
        generation_config={"max_output_tokens": 1000}
    )
    for chunk in response:  # pragma: no cover
        if chunk.text:  # pragma: no cover
            yield chunk.text  # pragma: no cover


def _pick_streamer(model_override: str):
    """Return (streamer_fn, model_name) based on available keys."""
    # Explicit override via CHAT_LLM_MODEL env var
    if model_override:
        if "gemini" in model_override.lower():
            return _stream_gemini, model_override
        return _stream_claude, model_override

    # Auto-detect: prefer Claude if key set, else Gemini
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return _stream_claude, "claude-sonnet-4-6"
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return _stream_gemini, "gemini-3.1-pro-preview"
    return None, "none"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _write_trace(model: str, prompt: str, response: str, latency_ms: int) -> None:
    """Persist chat exchange to llm_traces for audit and quota tracking."""
    try:
        from app.db import get_conn_rw
        with get_conn_rw() as conn:
            conn.execute(
                """INSERT INTO llm_traces
                   (trace_id, agent, model, prompt, response, latency_ms,
                    prompt_tokens, completion_tokens, created_at)
                   VALUES (?, 'chat', ?, ?, ?, ?, 0, 0, ?)""",
                (
                    f"chat_{uuid.uuid4().hex[:12]}",
                    model,
                    prompt[:4000],       # truncate very long prompts
                    response[:4000],
                    latency_ms,
                    int(time.time()),
                )
            )
    except Exception:
        pass   # non-critical — don't break the chat response


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/history")
def chat_history():
    """Return last 50 chat exchanges from llm_traces."""
    try:
        with READONLY_POOL.conn() as conn:
            rows = conn.execute(
                """SELECT trace_id, model, prompt, response, latency_ms, created_at
                   FROM llm_traces
                   WHERE agent = 'chat'
                   ORDER BY created_at DESC LIMIT 50"""
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["trace_id"],
                "model": r["model"],
                "prompt": r["prompt"],
                "response": r["response"],
                "latency_ms": r["latency_ms"],
                "created_at": r["created_at"],
            })
        return {"history": result[::-1]}   # chronological order
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/message")
async def chat_message(req: ChatRequest):
    """Send a message to AI and stream the response via SSE."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    # Build context
    try:
        with READONLY_POOL.conn() as conn:
            system_prompt = build_chat_context(conn)
    except Exception:
        system_prompt = build_chat_context(None)

    # Prepare messages (include brief history for context)
    messages = []
    for h in req.history[-6:]:   # last 3 turns (6 messages)
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": req.message})

    # Pick LLM
    model_override = _get_chat_model()
    streamer, model_name = _pick_streamer(model_override)

    async def generate() -> AsyncGenerator[str, None]:
        full_response = ""
        start = time.time()
        try:
            if streamer is None:
                error_msg = "未設定 ANTHROPIC_API_KEY 或 GEMINI_API_KEY，無法使用 AI 對話功能。"
                yield f"data: {json.dumps({'type': 'chunk', 'text': error_msg})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'model': 'none'})}\n\n"
                return

            async for chunk in streamer(system_prompt, messages, model_name):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"

            # Detect proposal intent
            proposal = parse_proposal_intent(full_response)
            latency_ms = int((time.time() - start) * 1000)
            yield f"data: {json.dumps({'type': 'done', 'model': model_name, 'proposal': proposal})}\n\n"

            # Write trace asynchronously (fire and forget)
            _write_trace(model_name, f"[system]\n{system_prompt}\n\n[user]\n{req.message}",
                         full_response, latency_ms)

        except Exception as e:
            err = f"AI 呼叫失敗：{str(e)}"
            yield f"data: {json.dumps({'type': 'error', 'text': err})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/create-proposal")
def chat_create_proposal(req: ProposalRequest):
    """Parse AI response for trade intent and create a strategy proposal."""
    intent = parse_proposal_intent(req.ai_response)
    if not intent:
        raise HTTPException(status_code=400, detail="AI 回應中未偵測到明確的交易建議")

    try:
        from app.db import get_conn_rw
        with get_conn_rw() as conn:
            proposal_id = f"chat_{uuid.uuid4().hex[:10]}"
            now = int(time.time())
            proposal_json = json.dumps({
                "action": intent["action"],
                "symbol": intent["symbol"],
                "qty": intent["qty"],
                "price": intent["price"],
                "source": "chat",
                "user_message": req.user_message[:300],
            }, ensure_ascii=False)
            conn.execute(
                """INSERT INTO strategy_proposals
                   (proposal_id, generated_by, target_rule, rule_category,
                    current_value, proposed_value, supporting_evidence,
                    confidence, requires_human_approval, status,
                    proposal_json, created_at)
                   VALUES (?, 'chat', 'TRADE_ORDER', 'execution',
                    NULL, ?, ?, 0.6, 1, 'pending', ?, ?)""",
                (
                    proposal_id,
                    f"{intent['action'].upper()} {intent['symbol']} {intent['qty']}股 @{intent['price']}",
                    f"來自 AI 對話：{req.user_message[:200]}",
                    proposal_json,
                    now,
                )
            )
        return {
            "status": "ok",
            "proposal_id": proposal_id,
            "intent": intent,
            "message": f"提案已建立（{intent['action'].upper()} {intent['symbol']} {intent['qty']}股 @{intent['price']}），請至 Strategy 頁面審核。"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
