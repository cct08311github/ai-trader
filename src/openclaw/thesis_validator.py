"""thesis_validator.py — Thesis comparison engine for memory semiconductor triggers.

Three sell triggers:
1. Top 3 manufacturers start capex race (supply discipline breaks)
2. CXL memory pooling reaches commercial maturity
3. Memory contract prices show clear inflection point
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from openclaw.agents.base import call_agent_llm

log = logging.getLogger(__name__)


@dataclass
class TriggerResult:
    trigger_name: str
    triggered: bool
    confidence: int  # 0-100
    evidence: str
    source_urls: List[str] = field(default_factory=list)


def check_capex_race(intel_items: List[Dict]) -> TriggerResult:
    """Detect if 3+ manufacturers are announcing capacity expansion simultaneously.

    Trigger: supply discipline breaks — multiple DRAM/NAND makers launching
    aggressive capex plans in the same quarter.
    """
    if not intel_items:
        return TriggerResult(
            trigger_name="capex_race",
            triggered=False,
            confidence=0,
            evidence="No intel items to analyze",
        )

    summaries = "\n".join(
        f"- [{item.get('company', 'N/A')}] {item.get('title', '')}: {item.get('summary', '')}"
        for item in intel_items[:20]
    )
    source_urls = [item["url"] for item in intel_items if item.get("url")][:10]

    prompt = f"""\
你是半導體產業分析師。分析以下競品情報，判斷記憶體三大廠（SK Hynix、Micron、Samsung）
是否正在同時進行大規模資本支出擴張（capex race），導致供給紀律崩潰。

## 情報摘要
{summaries}

## 判斷標準
- 若 3 家中有 2 家以上同時宣佈擴產計畫，confidence >= 60
- 若僅 1 家擴產，其他維持紀律，confidence < 30
- 需考慮：新建 fab 公告、設備採購訂單、法人說明會 capex guidance

## 輸出格式（JSON）
```json
{{
  "triggered": true/false,
  "confidence": 0-100,
  "evidence": "一段摘要說明判斷依據"
}}
```
"""
    result = call_agent_llm(prompt)
    triggered = bool(result.get("triggered", False))
    confidence = int(result.get("confidence", 0))

    return TriggerResult(
        trigger_name="capex_race",
        triggered=triggered,
        confidence=confidence,
        evidence=str(result.get("evidence", result.get("summary", ""))),
        source_urls=source_urls,
    )


def check_cxl_maturity(intel_items: List[Dict]) -> TriggerResult:
    """Detect CXL memory pooling reaching commercial maturity.

    Trigger: CXL pooling moves from lab/prototype to production deployment
    at hyperscalers, threatening traditional memory pricing power.
    """
    if not intel_items:
        return TriggerResult(
            trigger_name="cxl_maturity",
            triggered=False,
            confidence=0,
            evidence="No intel items to analyze",
        )

    summaries = "\n".join(
        f"- [{item.get('company', 'N/A')}] {item.get('title', '')}: {item.get('summary', '')}"
        for item in intel_items[:20]
    )
    source_urls = [item["url"] for item in intel_items if item.get("url")][:10]

    prompt = f"""\
你是記憶體產業分析師。分析以下情報，判斷 CXL（Compute Express Link）記憶體池化技術
是否已達到商業成熟度，可能改變記憶體產業的競爭格局。

## 情報摘要
{summaries}

## 判斷標準
- CXL 3.0/3.1 記憶體池化是否有大型雲端廠商（AWS/Azure/GCP）開始量產部署
- 是否有主要伺服器 OEM 推出支援 CXL pooling 的商用產品
- 若仍處於實驗/POC 階段，confidence < 30
- 若已有商業部署案例，confidence >= 60

## 輸出格式（JSON）
```json
{{
  "triggered": true/false,
  "confidence": 0-100,
  "evidence": "一段摘要說明判斷依據"
}}
```
"""
    result = call_agent_llm(prompt)
    triggered = bool(result.get("triggered", False))
    confidence = int(result.get("confidence", 0))

    return TriggerResult(
        trigger_name="cxl_maturity",
        triggered=triggered,
        confidence=confidence,
        evidence=str(result.get("evidence", result.get("summary", ""))),
        source_urls=source_urls,
    )


def check_price_inflection(intel_items: List[Dict]) -> TriggerResult:
    """Detect DRAM/NAND contract price trend reversal.

    Trigger: contract prices that were rising start to plateau or decline,
    signaling a cycle top.
    """
    if not intel_items:
        return TriggerResult(
            trigger_name="price_inflection",
            triggered=False,
            confidence=0,
            evidence="No intel items to analyze",
        )

    summaries = "\n".join(
        f"- [{item.get('company', 'N/A')}] {item.get('title', '')}: {item.get('summary', '')}"
        for item in intel_items[:20]
    )
    source_urls = [item["url"] for item in intel_items if item.get("url")][:10]

    prompt = f"""\
你是記憶體市場價格分析師。分析以下情報，判斷 DRAM 和 NAND Flash 合約價格
是否出現明確的反轉訊號（從上漲轉為持平或下跌）。

## 情報摘要
{summaries}

## 判斷標準
- 關注 DRAMeXchange/TrendForce 合約價報價
- DRAM DDR5 spot/contract 價格是否連續 2 個月下跌
- NAND 合約價是否出現 QoQ 下跌
- 若價格仍在上漲通道，confidence < 20
- 若價格持平或開始鬆動，confidence 40-60
- 若明確反轉（連續下跌），confidence >= 70

## 輸出格式（JSON）
```json
{{
  "triggered": true/false,
  "confidence": 0-100,
  "evidence": "一段摘要說明判斷依據"
}}
```
"""
    result = call_agent_llm(prompt)
    triggered = bool(result.get("triggered", False))
    confidence = int(result.get("confidence", 0))

    return TriggerResult(
        trigger_name="price_inflection",
        triggered=triggered,
        confidence=confidence,
        evidence=str(result.get("evidence", result.get("summary", ""))),
        source_urls=source_urls,
    )


def run_all_checks(intel_items: List[Dict]) -> List[TriggerResult]:
    """Run all three thesis validation checks and return results."""
    return [
        check_capex_race(intel_items),
        check_cxl_maturity(intel_items),
        check_price_inflection(intel_items),
    ]
