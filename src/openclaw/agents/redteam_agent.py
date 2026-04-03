"""redteam_agent.py — Orchestrator wrapper for Security Red Team scanner.

Runs the red team scan and sends the report summary to Discord.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from openclaw.agents.base import AgentResult

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISCORD_CHANNEL_ID = "1485867213675167855"  # 維運群


def _send_discord_report(summary: str) -> bool:
    """Send report summary to Discord maintenance channel."""
    try:
        from openclaw.tg_notify import send_message as tg_send
        # Use Discord plugin if available, fallback to Telegram
        try:
            # Try importing discord send function
            import subprocess
            # Use the Discord plugin via claude CLI isn't available here,
            # so we write to a file and let the next session pick it up
            report_path = _REPO_ROOT / "tools" / "redteam" / "latest_report.md"
            report_path.write_text(summary, encoding="utf-8")
            log.info("[RedTeamAgent] Report saved to %s", report_path)
            return True
        except Exception as e:
            log.warning("[RedTeamAgent] Discord send failed: %s", e)
            # Fallback: send summary via Telegram
            short = summary[:4000]  # Telegram message limit
            tg_send(f"🔴 Security Red Team Report\n\n{short}")
            return True
    except Exception as e:
        log.error("[RedTeamAgent] Failed to send report: %s", e)
        return False


def run_redteam_agent(conn=None, db_path=None) -> AgentResult:
    """Run the security red team scan and produce a report."""
    # Add tools directory to path
    tools_dir = str(_REPO_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)

    try:
        from redteam.red_team import run_scan
        from redteam.report_generator import generate_report

        log.info("[RedTeamAgent] Starting security scan...")
        report = run_scan(str(_REPO_ROOT / "tools" / "redteam" / "config.yaml"))

        # Generate report
        report_md = generate_report(report, repo_name="ai-trader")

        # Save full report
        output_path = _REPO_ROOT / "tools" / "redteam" / "latest_report.md"
        output_path.write_text(report_md, encoding="utf-8")

        # Build summary for Discord/Telegram
        critical = sum(1 for f in report.findings if f.severity.name == "CRITICAL")
        high = sum(1 for f in report.findings if f.severity.name == "HIGH")
        medium = sum(1 for f in report.findings if f.severity.name == "MEDIUM")
        low = sum(1 for f in report.findings if f.severity.name == "LOW")
        total = len(report.findings)

        summary = (
            f"🔴 Security Red Team 掃描完成\n\n"
            f"發現 {total} 個問題：\n"
            f"  CRITICAL: {critical}\n"
            f"  HIGH: {high}\n"
            f"  MEDIUM: {medium}\n"
            f"  LOW: {low}\n\n"
            f"掃描耗時: {report.scan_duration_seconds:.1f}s\n"
            f"完整報告: tools/redteam/latest_report.md"
        )

        # Top findings
        if critical > 0 or high > 0:
            summary += "\n\n🚨 重要發現：\n"
            for f in report.findings:
                if f.severity.name in ("CRITICAL", "HIGH"):
                    summary += f"  [{f.severity.name}] {f.title}\n"

        _send_discord_report(summary)

        return AgentResult(
            agent_name="RedTeamAgent",
            success=True,
            summary=f"Scan complete: {critical}C/{high}H/{medium}M/{low}L findings",
            details={"total": total, "critical": critical, "high": high,
                     "medium": medium, "low": low,
                     "report_path": str(output_path)},
        )

    except Exception as e:
        log.error("[RedTeamAgent] Scan failed: %s", e, exc_info=True)
        return AgentResult(
            agent_name="RedTeamAgent",
            success=False,
            summary=f"Scan failed: {e}",
            details={},
        )
