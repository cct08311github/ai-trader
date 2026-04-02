"""debate_formatter.py — Discord Markdown 格式化 Debate 報告。

將 DebateRecord 列表轉換為可讀的 Discord 訊息格式。
"""
from __future__ import annotations

from typing import List

from openclaw.debate_loop import DebateRecord


_REC_EMOJI = {
    "BUY": "\U0001f7e2",   # green circle
    "SELL": "\U0001f534",   # red circle
    "HOLD": "\U0001f7e1",   # yellow circle
    "REJECT": "\u26d4",     # no entry
    "VETOED": "\U0001f6ab",  # prohibited
}


def format_single_debate(record: DebateRecord) -> str:
    """Format a single debate record for Discord."""
    emoji = _REC_EMOJI.get(record.recommendation, "\u2753")
    lines = [
        f"### {emoji} {record.symbol} — {record.recommendation} (conf: {record.confidence:.0%})",
        "",
        f"**Bull** (conf: {record.bull_thesis.confidence:.0%})",
        f"> {record.bull_thesis.thesis[:200]}",
    ]

    if record.bull_thesis.entry_price > 0:
        lines.append(
            f"> Entry: {record.bull_thesis.entry_price:.1f} | "
            f"Target: {record.bull_thesis.target_price:.1f}"
        )

    lines.extend([
        "",
        f"**Bear** (conf: {record.bear_thesis.confidence:.0%})",
        f"> {record.bear_thesis.thesis[:200]}",
    ])

    if record.bear_thesis.stop_loss > 0:
        lines.append(f"> Stop-loss: {record.bear_thesis.stop_loss:.1f}")

    lines.extend([
        "",
        f"**Arbiter**: {record.arbiter_decision.rationale[:200]}",
    ])

    if not record.risk_check.passed:
        lines.append(f"\u26a0\ufe0f Risk Veto: {record.risk_check.reason}")

    lines.append(f"_elapsed: {record.elapsed_ms}ms_")
    return "\n".join(lines)


def format_debate_report(debates: List[DebateRecord], date_str: str = "") -> str:
    """Format full debate report for Discord channel posting."""
    if not debates:
        return "## Hedge Fund Debate Report\n\nNo debates executed today."

    header = f"## Hedge Fund Debate Report — {date_str or debates[0].debate_date}"

    # Summary stats
    buy_count = sum(1 for d in debates if d.recommendation == "BUY")
    sell_count = sum(1 for d in debates if d.recommendation == "SELL")
    hold_count = sum(1 for d in debates if d.recommendation == "HOLD")
    vetoed_count = sum(1 for d in debates if d.recommendation == "VETOED")
    reject_count = sum(1 for d in debates if d.recommendation == "REJECT")

    summary = (
        f"**Summary**: {len(debates)} symbols | "
        f"BUY: {buy_count} | SELL: {sell_count} | HOLD: {hold_count} | "
        f"REJECT: {reject_count} | VETOED: {vetoed_count}"
    )

    sections = [header, summary, "---"]

    for record in debates:
        sections.append(format_single_debate(record))
        sections.append("")

    # Discord message length limit: 2000 chars
    full_report = "\n".join(sections)
    if len(full_report) > 1900:
        # Truncate with indicator
        full_report = full_report[:1850] + "\n\n_... (truncated, see DB for full report)_"

    return full_report
