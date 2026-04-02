"""agents/arbiter_agent.py — Arbiter委員：仲裁者 Agent。

綜合 Bull 與 Bear 論點，做出最終委員會決議。
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from openclaw.agents.base import COMMITTEE_MODEL, call_agent_llm
from openclaw.agents.bull_agent import BullThesis
from openclaw.agents.bear_agent import BearThesis

log = logging.getLogger("arbiter_agent")

_ARBITER_SYSTEM_PROMPT = """\
你是 AI Hedge Fund 的 Arbiter委員（Committee Chair）。

## 角色
綜合 Bull 和 Bear 論點，做出客觀的最終委員會建議。

## 決策框架
1. 數據權重：客觀信號 > LLM 情緒
2. 不對稱性：偏好避免大虧損勝過追逐獲利
3. 市況意識：bear market 時，做多需要更高信心
4. 平手處理：Bull/Bear 勢均力敵時，預設 HOLD

## Bull委員論點
{bull_thesis}
（信心度：{bull_confidence}）

## Bear委員論點
{bear_thesis}
（信心度：{bear_confidence}）

## 技術信號摘要
{signal_summary}

## 任務
綜合雙方意見，給出最終建議。

輸出嚴格 JSON（不要加 markdown 標記）：
{{
  "symbol": "{symbol}",
  "recommendation": "BUY" 或 "SELL" 或 "HOLD" 或 "REJECT",
  "confidence": 0.0 到 1.0,
  "rationale": "2-3 句決策理由",
  "bull_score": 0 到 100,
  "bear_score": 0 到 100
}}
"""


@dataclass
class ArbiterDecision:
    symbol: str
    recommendation: str  # BUY / SELL / HOLD / REJECT
    confidence: float
    rationale: str
    bull_score: float = 50.0
    bear_score: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ArbiterAgent:
    """仲裁者 Agent：綜合 Bull/Bear 論點做出最終決議。"""

    VALID_RECOMMENDATIONS = {"BUY", "SELL", "HOLD", "REJECT"}

    def __init__(self, model: str = COMMITTEE_MODEL, timeout_s: float = 30.0):
        self.model = model
        self.timeout_s = timeout_s

    def build_prompt(
        self,
        symbol: str,
        bull: BullThesis,
        bear: BearThesis,
        signal_summary: str = "",
    ) -> str:
        return _ARBITER_SYSTEM_PROMPT.format(
            symbol=symbol,
            bull_thesis=bull.thesis,
            bull_confidence=bull.confidence,
            bear_thesis=bear.thesis,
            bear_confidence=bear.confidence,
            signal_summary=signal_summary or "（無額外信號摘要）",
        )

    def parse_response(self, raw: Dict[str, Any], symbol: str) -> ArbiterDecision:
        """Parse LLM response into ArbiterDecision."""
        rec = str(raw.get("recommendation", "HOLD")).upper()
        if rec not in self.VALID_RECOMMENDATIONS:
            rec = "HOLD"

        return ArbiterDecision(
            symbol=symbol,
            recommendation=rec,
            confidence=float(raw.get("confidence", 0.0)),
            rationale=str(raw.get("rationale", raw.get("summary", ""))),
            bull_score=float(raw.get("bull_score", 50)),
            bear_score=float(raw.get("bear_score", 50)),
        )

    def decide(
        self,
        bull: BullThesis,
        bear: BearThesis,
        signals: Dict[str, Any],
    ) -> ArbiterDecision:
        """Execute arbiter decision: receive theses -> call LLM -> final decision."""
        symbol = bull.symbol
        signal_summary = json.dumps(signals, ensure_ascii=False, default=str)[:500]
        prompt = self.build_prompt(symbol, bull, bear, signal_summary)
        raw = call_agent_llm(prompt, model=self.model)

        if raw.get("_error"):
            log.warning("[ArbiterAgent] LLM error for %s: %s", symbol, raw["_error"])
            return ArbiterDecision(
                symbol=symbol,
                recommendation="HOLD",
                confidence=0.0,
                rationale=f"LLM 呼叫失敗：{raw.get('_error', 'unknown')}",
            )

        return self.parse_response(raw, symbol)
