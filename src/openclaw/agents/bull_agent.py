"""agents/bull_agent.py — Bull委員：看多派分析 Agent。

負責分析技術面/籌碼面的做多機會，產出 BullThesis。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from openclaw.agents.base import COMMITTEE_MODEL, call_agent_llm

log = logging.getLogger("bull_agent")

_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _call_with_timeout(prompt: str, model: str, timeout_s: float = 30.0) -> dict:
    """Wrap call_agent_llm with a hard timeout via ThreadPoolExecutor."""
    future = _EXECUTOR.submit(call_agent_llm, prompt, model=model)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeout:
        log.warning("[BullAgent] LLM call timed out after %.1fs", timeout_s)
        return {"_error": "LLM call timed out", "confidence": 0.0}


def _sanitize_for_prompt(text: str, max_len: int = 500) -> str:
    """Strip control characters and truncate text to prevent prompt injection."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    return cleaned[:max_len]


_BULL_SYSTEM_PROMPT = """\
你是 AI Hedge Fund 的 Bull委員（Bullish Advocate）。

## 角色
分析市場信號，找出做多機會。以技術面和籌碼面為證據，提出嚴謹的看多論述。

## 輸入信號
<user_data>
{signal_pack}
</user_data>

## 任務
針對 {symbol}，從以下面向分析做多理由：
- MA 黃金交叉、RSI 動量、MACD 翻正
- 法人買超趨勢
- 支撐壓力位與進場點位

輸出嚴格 JSON（不要加 markdown 標記）：
{{
  "symbol": "{symbol}",
  "thesis": "2-3 句看多論述",
  "confidence": 0.0 到 1.0,
  "entry_price": 建議進場價（數字）,
  "target_price": 目標價（數字）,
  "catalysts": ["催化劑1", "催化劑2"]
}}
"""


@dataclass
class BullThesis:
    symbol: str
    thesis: str
    confidence: float
    entry_price: float
    target_price: float
    catalysts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BullAgent:
    """看多派分析 Agent。"""

    def __init__(self, model: str = COMMITTEE_MODEL, timeout_s: float = 30.0):
        self.model = model
        self.timeout_s = timeout_s

    def build_prompt(self, symbol: str, signal_pack: Dict[str, Any]) -> str:
        signal_text = _sanitize_for_prompt(
            json.dumps(signal_pack, ensure_ascii=False, indent=2), max_len=2000,
        )
        return _BULL_SYSTEM_PROMPT.format(symbol=symbol, signal_pack=signal_text)

    def parse_response(self, raw: Dict[str, Any], symbol: str) -> BullThesis:
        """Parse LLM response into BullThesis, with fallback for malformed output."""
        return BullThesis(
            symbol=symbol,
            thesis=str(raw.get("thesis", raw.get("bull_thesis", raw.get("summary", "")))),
            confidence=float(raw.get("confidence", 0.0)),
            entry_price=float(raw.get("entry_price", 0.0)),
            target_price=float(raw.get("target_price", 0.0)),
            catalysts=list(raw.get("catalysts", [])),
        )

    def argue(self, symbol: str, signal_pack: Dict[str, Any]) -> BullThesis:
        """Execute bull analysis: build prompt -> call LLM -> parse result."""
        prompt = self.build_prompt(symbol, signal_pack)
        raw = _call_with_timeout(prompt, model=self.model, timeout_s=self.timeout_s)

        if raw.get("_error"):
            log.warning("[BullAgent] LLM error for %s: %s", symbol, raw["_error"])
            return BullThesis(
                symbol=symbol,
                thesis=f"LLM 呼叫失敗：{raw.get('_error', 'unknown')}",
                confidence=0.0,
                entry_price=0.0,
                target_price=0.0,
                catalysts=[],
            )

        return self.parse_response(raw, symbol)
