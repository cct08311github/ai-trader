"""competitor_monitor.py — Competitor Monitoring Agent main loop.

Monitors memory semiconductor competitors for investment thesis validation.
Runs daily at 08:00 TWN (weekdays) before market open.

Output:
- Discord: daily summary report (2-3 sentences per company, sentiment tag)
- Telegram: trigger alerts when confidence > 60
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from openclaw.agents.base import (
    call_agent_llm,
    open_conn,
    write_trace,
)
from openclaw.intel_dedup import dedup_intel_items, url_hash
from openclaw.path_utils import get_repo_root
from openclaw.thesis_validator import TriggerResult, run_all_checks

log = logging.getLogger(__name__)

_REPO_ROOT = get_repo_root()
_TZ_TWN = timezone(timedelta(hours=8))

# ── Competitor definitions ──────────────────────────────────────────────────

COMPETITORS: Dict[str, Dict] = {
    "TSMC": {"ticker": "2330.TW", "market": "TWSE", "sector": "foundry"},
    "SK Hynix": {"ticker": "000660.KS", "market": "KRX", "sector": "memory"},
    "Micron": {"ticker": "MU", "market": "NASDAQ", "sector": "memory"},
    "Samsung": {"ticker": "005930.KS", "market": "KRX", "sector": "memory/foundry"},
}

MAX_QUERIES_PER_COMPANY = 5
INTEL_RETENTION_DAYS = 180
TRIGGER_ALERT_THRESHOLD = 60

# ── DB schema ───────────────────────────────────────────────────────────────

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS competitor_intel (
    intel_id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT,
    url TEXT,
    url_hash TEXT,
    summary TEXT,
    sentiment TEXT,
    source TEXT,
    published_at TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(url_hash)
)"""


def ensure_table(conn: sqlite3.Connection) -> None:
    """Create competitor_intel table if it doesn't exist.

    Uses single-statement execute to avoid the implicit COMMIT
    that multi-statement script execution would cause.
    """
    conn.execute(_CREATE_TABLE_SQL)
    conn.commit()


# ── Sanitisation helpers ─────────────────────────────────────────────────────

_DISCORD_SPECIAL_RE = re.compile(r"(\*\*|`|@everyone|@here|<@[!&]?\d+>)")
_URL_RE = re.compile(r"https?://\S+")
_MD_RE = re.compile(r"[*_~`|>]")


def _strip_discord_chars(text: str) -> str:
    """Remove Discord markdown special characters that could break formatting."""
    return _DISCORD_SPECIAL_RE.sub("", text)


def _sanitize_evidence_for_alert(text: str, max_len: int = 100) -> str:
    """Sanitize LLM evidence before sending to Telegram.

    Strips markdown, removes URLs, and truncates to max_len.
    """
    cleaned = _MD_RE.sub("", text)
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())  # collapse whitespace
    return cleaned[:max_len]


# ── Search query generation ─────────────────────────────────────────────────

def _generate_search_queries(company: str, info: Dict) -> List[str]:
    """Generate 3-5 search queries per company covering key intel categories."""
    ticker = info["ticker"]
    queries = [
        f"{company} {ticker} earnings revenue quarterly results 2026",
        f"{company} executive changes CEO CTO leadership",
        f"{company} capacity expansion new fab capex investment",
        f"{company} DRAM NAND contract price trend",
    ]
    if info["sector"] in ("memory", "memory/foundry"):
        queries.append(f"{company} CXL memory pooling HBM technology")
    return queries[:MAX_QUERIES_PER_COMPANY]


# ── Intel gathering ─────────────────────────────────────────────────────────

def _gather_intel_for_company(
    company: str,
    info: Dict,
) -> List[Dict]:
    """Gather intelligence for a single company via LLM-based search synthesis.

    Uses call_agent_llm to synthesize search results into structured intel.
    """
    queries = _generate_search_queries(company, info)
    all_items: List[Dict] = []

    for idx, query in enumerate(queries):
        # Rate-limit LLM calls: avoid hitting provider rate limits when
        # processing multiple queries sequentially.
        if idx > 0:
            time.sleep(1.0)

        prompt = f"""\
你是半導體產業情報分析員。請根據以下搜尋主題，提供最新的相關情報。

## 搜尋主題
{query}

## 公司資訊
- 公司：{company}
- 代號：{info['ticker']}
- 市場：{info['market']}

## 輸出格式（JSON）
```json
{{
  "items": [
    {{
      "title": "新聞/事件標題",
      "url": "來源 URL（若已知）",
      "summary": "2-3 句摘要",
      "sentiment": "positive/negative/neutral",
      "category": "earnings/executive/patent/capacity/pricing/technology",
      "published_at": "YYYY-MM-DD（若已知，否則 null）"
    }}
  ]
}}
```
請回傳 1-3 則最相關的情報。若無可靠資訊，回傳空列表。
"""
        result = call_agent_llm(prompt)
        items = result.get("items", [])
        for item in items:
            item["company"] = company
            item.setdefault("category", "general")
            item.setdefault("sentiment", "neutral")
            item.setdefault("source", "llm_synthesis")
        all_items.extend(items)

    return all_items


# ── Intel storage ───────────────────────────────────────────────────────────

def _store_intel(conn: sqlite3.Connection, items: List[Dict]) -> int:
    """Store deduped intel items into competitor_intel table. Returns count stored."""
    stored = 0
    now_ts = int(time.time())
    for item in items:
        intel_id = str(uuid.uuid4())
        item_url = item.get("url", "")
        # Use title-based hash when URL is empty so dedup still works;
        # random uuid would bypass the UNIQUE(url_hash) constraint.
        item_hash = (
            url_hash(item_url)
            if item_url
            else hashlib.sha256(item.get("title", "").encode()).hexdigest()[:32]
        )
        try:
            conn.execute(
                """INSERT OR IGNORE INTO competitor_intel
                   (intel_id, company, category, title, url, url_hash,
                    summary, sentiment, source, published_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    intel_id,
                    item.get("company", ""),
                    item.get("category", "general"),
                    item.get("title", ""),
                    item_url,
                    item_hash,
                    item.get("summary", ""),
                    item.get("sentiment", "neutral"),
                    item.get("source", "llm_synthesis"),
                    item.get("published_at"),
                    now_ts,
                ),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass  # duplicate url_hash — skip
    conn.commit()
    return stored


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_old_intel(conn: sqlite3.Connection, retention_days: int = INTEL_RETENTION_DAYS) -> int:
    """Delete intel older than retention_days. Returns count deleted."""
    cutoff = int(time.time()) - (retention_days * 86400)
    cursor = conn.execute(
        "DELETE FROM competitor_intel WHERE created_at < ?", (cutoff,)
    )
    conn.commit()
    return cursor.rowcount


# ── Report generation ───────────────────────────────────────────────────────

def _generate_daily_report(
    conn: sqlite3.Connection,
    trigger_results: List[TriggerResult],
) -> str:
    """Generate daily Discord summary report."""
    # Use proper calendar-day start in TWN timezone instead of a
    # rolling 24h window, so the report always covers "today".
    now_twn = datetime.now(tz=_TZ_TWN)
    today_start_twn = now_twn.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = int(today_start_twn.timestamp())

    lines = [f"[竸品日報] {now_twn.strftime('%Y-%m-%d')}\n"]

    for company in COMPETITORS:
        rows = conn.execute(
            """SELECT title, summary, sentiment FROM competitor_intel
               WHERE company = ? AND created_at >= ?
               ORDER BY created_at DESC LIMIT 5""",
            (company, today_start),
        ).fetchall()

        if rows:
            sentiments = [r[2] for r in rows if r[2]]
            dominant = max(set(sentiments), key=sentiments.count) if sentiments else "neutral"
            # Strip Discord special chars from LLM-generated summary
            summaries = "; ".join(
                _strip_discord_chars(r[1]) for r in rows[:2] if r[1]
            )
            emoji = {"positive": "+", "negative": "-", "neutral": "~"}.get(dominant, "~")
            lines.append(f"{company} [{emoji}{dominant}]: {summaries}")
        else:
            lines.append(f"{company} [~neutral]: 今日無新情報")

    # Trigger status
    lines.append("\n-- 論文驗證 --")
    for tr in trigger_results:
        status = "TRIGGERED" if tr.triggered else "safe"
        lines.append(f"- {tr.trigger_name}: {status} (confidence={tr.confidence}%)")
        if tr.evidence:
            evidence_clean = _strip_discord_chars(tr.evidence[:120])
            lines.append(f"  evidence: {evidence_clean}")
        # Mark source URLs as unverified in the report
        if tr.source_urls:
            for url in tr.source_urls[:3]:
                display_url = url.replace("[UNVERIFIED] ", "")
                lines.append(f"  [未驗證] {display_url}")

    return "\n".join(lines)


def _send_trigger_alerts(trigger_results: List[TriggerResult]) -> None:
    """Send Telegram alerts for triggers with confidence > threshold."""
    try:
        from openclaw.tg_notify import send_message as tg_send
    except ImportError:
        log.warning("tg_notify not available, skipping trigger alerts")
        return

    for tr in trigger_results:
        if tr.confidence >= TRIGGER_ALERT_THRESHOLD:
            # Sanitize evidence: strip markdown, URLs, limit length to
            # prevent raw LLM output from leaking into Telegram messages.
            safe_evidence = _sanitize_evidence_for_alert(tr.evidence, max_len=100)
            msg = (
                f"[竸品監控] {tr.trigger_name} 可能觸發 "
                f"(confidence={tr.confidence}%) -- "
                f"{safe_evidence} -- "
                f"建議：檢視減碼條件"
            )
            try:
                tg_send(msg)
                log.info("Trigger alert sent: %s", tr.trigger_name)
            except Exception as e:
                log.error("Failed to send trigger alert: %s", e)


def _send_discord_report(report: str) -> None:
    """Send daily report to Discord via notifier (falls back to log)."""
    try:
        from openclaw.notifier import notify
        notify(report)
        log.info("Discord daily report sent (%d chars)", len(report))
    except Exception as e:
        log.warning("Failed to send Discord report: %s — logging instead", e)
        log.info("Daily report:\n%s", report)


# ── Main entry point ────────────────────────────────────────────────────────

def run_competitor_monitor(
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> Dict:
    """Run the full competitor monitoring cycle.

    1. Ensure DB table exists
    2. Gather intel for each competitor
    3. Dedup and store
    4. Run thesis validation checks
    5. Generate report + send alerts

    Returns summary dict.
    """
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)

    try:
        ensure_table(_conn)

        # Gather intel
        all_items: List[Dict] = []
        for company, info in COMPETITORS.items():
            log.info("Gathering intel for %s ...", company)
            items = _gather_intel_for_company(company, info)
            all_items.extend(items)

        # Dedup
        deduped = dedup_intel_items(_conn, all_items)
        log.info("Intel gathered: %d raw, %d after dedup", len(all_items), len(deduped))

        # Store
        stored = _store_intel(_conn, deduped)
        log.info("Stored %d new intel items", stored)

        # Thesis validation
        trigger_results = run_all_checks(deduped)

        # Write trace
        write_trace(
            _conn,
            agent="CompetitorMonitorAgent",
            prompt=f"competitor_monitor run: {len(deduped)} items",
            result={
                "summary": f"Monitored {len(COMPETITORS)} companies, {stored} new intel, "
                           f"{sum(1 for t in trigger_results if t.triggered)} triggers fired",
                "confidence": max((t.confidence for t in trigger_results), default=0) / 100,
                "action_type": "observe",
                "proposals": [],
            },
        )

        # Reports
        report = _generate_daily_report(_conn, trigger_results)
        _send_discord_report(report)
        _send_trigger_alerts(trigger_results)

        # Cleanup old data
        deleted = cleanup_old_intel(_conn)
        if deleted:
            log.info("Cleaned up %d old intel items (>%d days)", deleted, INTEL_RETENTION_DAYS)

        return {
            "companies_monitored": len(COMPETITORS),
            "raw_items": len(all_items),
            "deduped_items": len(deduped),
            "stored_items": stored,
            "triggers": [
                {
                    "name": t.trigger_name,
                    "triggered": t.triggered,
                    "confidence": t.confidence,
                }
                for t in trigger_results
            ],
            "report_length": len(report),
        }

    finally:
        if conn is None:
            _conn.close()
