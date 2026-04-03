"""agents/bear_agent.py — Bear委員：看空派分析 Agent。

負責分析風險與下跌訊號，產出 BearThesis。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from openclaw.agents.base import COMMITTEE_MODEL, call_agent_llm

log = logging.getLogger("bear_agent")

_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _call_with_timeout(prompt: str, model: str, timeout_s: float = 30.0) -> dict:
    """Wrap call_agent_llm with a hard timeout via ThreadPoolExecutor."""
    future = _EXECUTOR.submit(call_agent_llm, prompt, model=model)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout:
        log.warning("[BearAgent] LLM call timed out after %.1fs", timeout_s)
        return {"_error": "LLM call timed out", "confidence": 0.0}


def _sanitize_for_prompt(text: str, max_len: int = 500) -> str:
    """Strip control characters and truncate text to prevent prompt injection."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    return cleaned[:max_len]


_BEAR_SYSTEM_PROMPT = """\
你是 AI Hedge Fund 的 Bear委員（Bearish Advocate）。

## 角色
挑戰看多論點，找出風險與下跌訊號。保護投資組合免受過度自信的傷害。

## 輸入信號
<user_data>
{signal_pack}
</user_data>

## 任務
針對 {symbol}，從以下面向分析做空/避險理由：
- RSI 超買（>70）、MACD 翻負、MA 死亡交叉
- 法人賣超趨勢
- 近期虧損紀錄、集中度風險
- 負面新聞或消息面風險

輸出嚴格 JSON（不要加 markdown 標記）：
{{
  "symbol": "{symbol}",
  "thesis": "2-3 句看空論述",
  "confidence": 0.0 到 1.0,
  "risks": ["風險1", "風險2"],
  "stop_loss": 建議停損價（數字）
}}
"""


@dataclass
class BearThesis:
    symbol: str
    thesis: str
    confidence: float
    risks: List[str] = field(default_factory=list)
    stop_loss: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BearAgent:
    """看空派分析 Agent。"""

    def __init__(self, model: str = COMMITTEE_MODEL, timeout_s: float = 30.0):
        self.model = model
        self.timeout_s = timeout_s

    def build_prompt(self, symbol: str, signal_pack: Dict[str, Any]) -> str:
        signal_text = _sanitize_for_prompt(
            json.dumps(signal_pack, ensure_ascii=False, indent=2), max_len=2000,
        )
        return _BEAR_SYSTEM_PROMPT.format(symbol=symbol, signal_pack=signal_text)

    def parse_response(self, raw: Dict[str, Any], symbol: str) -> BearThesis:
        """Parse LLM response into BearThesis, with fallback for malformed output."""
        return BearThesis(
            symbol=symbol,
            thesis=str(raw.get("thesis", raw.get("bear_thesis", raw.get("summary", "")))),
            confidence=float(raw.get("confidence", 0.0)),
            risks=list(raw.get("risks", [])),
            stop_loss=float(raw.get("stop_loss", 0.0)),
        )

    def argue(self, symbol: str, signal_pack: Dict[str, Any]) -> BearThesis:
        """Execute bear analysis: build prompt -> call LLM -> parse result."""
        prompt = self.build_prompt(symbol, signal_pack)
        raw = _call_with_timeout(prompt, model=self.model, timeout_s=self.timeout_s)

        if raw.get("_error"):
            log.warning("[BearAgent] LLM error for %s: %s", symbol, raw["_error"])
            return BearThesis(
                symbol=symbol,
                thesis=f"LLM 呼叫失敗：{raw.get('_error', 'unknown')}",
                confidence=0.0,
                risks=[],
                stop_loss=0.0,
            )

        return self.parse_response(raw, symbol)
