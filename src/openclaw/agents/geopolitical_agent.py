"""geopolitical_agent.py — Geopolitical Event Monitoring Agent.

掃描全球地緣政治風險事件，評估對金融市場的影響。
每 4 小時（平日）執行一次，結果存入 research.db / geopolitical_events。

Topics covered:
  - US-China trade tensions
  - Taiwan Strait developments
  - Middle East / Iran conflict
  - Fed monetary policy
  - European energy supply
  - OPEC production decisions
  - Semiconductor sanctions / export controls
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openclaw.agents.base import AgentResult, call_agent_llm, write_trace
from openclaw.path_utils import get_repo_root

log = logging.getLogger(__name__)

_REPO_ROOT = get_repo_root()

# ── Topic definitions ───────────────────────────────────────────────────────

TOPICS: Dict[str, Dict[str, Any]] = {
    "us_china_trade": {
        "label": "US-China Trade War",
        "region": "asia",
        "category": "trade_war",
        "queries": [
            "US China trade tariffs sanctions 2026 latest",
            "Biden Trump China trade war semiconductor export controls",
            "US China decoupling supply chain technology restrictions",
        ],
    },
    "taiwan_strait": {
        "label": "Taiwan Strait Tensions",
        "region": "asia",
        "category": "conflict",
        "queries": [
            "Taiwan Strait military tensions PLA navy exercises 2026",
            "Taiwan China geopolitical risk semiconductor TSMC",
            "Taiwan independence cross-strait relations US arms sale",
        ],
    },
    "middle_east_iran": {
        "label": "Middle East / Iran Conflict",
        "region": "middle_east",
        "category": "conflict",
        "queries": [
            "Iran nuclear deal sanctions oil market impact 2026",
            "Middle East conflict oil supply disruption shipping lanes",
            "Israel Iran tensions oil price geopolitical risk",
        ],
    },
    "fed_policy": {
        "label": "Fed Monetary Policy",
        "region": "americas",
        "category": "policy",
        "queries": [
            "Federal Reserve interest rate decision FOMC 2026",
            "Fed Powell rate cut inflation monetary policy outlook",
            "US Treasury yield curve Fed balance sheet quantitative tightening",
        ],
    },
    "european_energy": {
        "label": "European Energy Supply",
        "region": "europe",
        "category": "policy",
        "queries": [
            "Europe natural gas LNG supply Russia energy crisis 2026",
            "European energy security winter storage gas prices",
            "EU Russia sanctions energy transition renewable",
        ],
    },
    "opec": {
        "label": "OPEC Production Decisions",
        "region": "middle_east",
        "category": "policy",
        "queries": [
            "OPEC OPEC+ production cut oil output quota 2026",
            "Saudi Arabia Russia oil supply agreement crude price",
            "OPEC meeting output policy global oil market",
        ],
    },
    "semiconductor_sanctions": {
        "label": "Semiconductor Sanctions & Export Controls",
        "region": "asia",
        "category": "sanctions",
        "queries": [
            "US semiconductor export controls China chip ban ASML 2026",
            "NVIDIA advanced chip export restrictions AI GPU China",
            "semiconductor supply chain geopolitical risk TSMC Samsung",
        ],
    },
}

# Approximate lat/lng centroids for each region (for map markers)
_REGION_COORDS: Dict[str, Dict[str, float]] = {
    "asia":        {"lat": 25.0, "lng": 121.5},   # Taiwan-centric
    "middle_east": {"lat": 29.0, "lng": 48.0},    # Gulf region
    "americas":    {"lat": 38.9, "lng": -77.0},   # Washington DC
    "europe":      {"lat": 50.1, "lng": 10.0},    # Central Europe
    "africa":      {"lat": 1.0,  "lng": 20.0},    # Sub-Saharan center
    "global":      {"lat": 20.0, "lng": 0.0},
}

MAX_LLM_CALLS = 30
RETENTION_DAYS = 90

# ── DB schema migration ──────────────────────────────────────────────────────

_MIGRATION_SQL = [
    # Add columns that the original schema didn't have.
    # Each ALTER TABLE is wrapped in try/except at runtime because SQLite
    # doesn't support IF NOT EXISTS for columns.
    "ALTER TABLE geopolitical_events ADD COLUMN category TEXT",
    "ALTER TABLE geopolitical_events ADD COLUMN impact_score REAL DEFAULT 0",
    "ALTER TABLE geopolitical_events ADD COLUMN market_impact TEXT",   # JSON
    "ALTER TABLE geopolitical_events ADD COLUMN lat REAL",
    "ALTER TABLE geopolitical_events ADD COLUMN lng REAL",
    "ALTER TABLE geopolitical_events ADD COLUMN url_hash TEXT",
]

_CREATE_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_events_url_hash "
    "ON geopolitical_events (url_hash) WHERE url_hash IS NOT NULL"
)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Run migrations to add new columns. Silently skips if already present."""
    for stmt in _MIGRATION_SQL:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # Column already exists
    try:
        conn.execute(_CREATE_INDEX_SQL)
    except sqlite3.OperationalError:
        pass
    conn.commit()


# ── URL hash helper ──────────────────────────────────────────────────────────

def _url_hash(url: str) -> str:
    normalized = url.strip().lower().rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _title_hash(title: str) -> str:
    return hashlib.sha256(title.strip().lower().encode("utf-8")).hexdigest()[:32]


# ── Dedup helpers ────────────────────────────────────────────────────────────

def _is_duplicate(conn: sqlite3.Connection, url: str, title: str) -> bool:
    """Return True if url_hash or title_hash already present in geopolitical_events."""
    if url:
        h = _url_hash(url)
        row = conn.execute(
            "SELECT 1 FROM geopolitical_events WHERE url_hash = ? LIMIT 1", (h,)
        ).fetchone()
        if row:
            return True
    if title:
        h = _title_hash(title)
        row = conn.execute(
            "SELECT 1 FROM geopolitical_events WHERE url_hash = ? LIMIT 1", (h,)
        ).fetchone()
        if row:
            return True
    return False


# ── LLM prompt + parse ───────────────────────────────────────────────────────

def _build_prompt(topic_key: str, topic: Dict[str, Any], query: str) -> str:
    return f"""\
你是地緣政治風險分析師，專門評估全球宏觀事件對金融市場的影響。

## 搜尋主題
{query}

## 議題類別
- 主題：{topic['label']}
- 預設分類：{topic['category']}
- 主要地區：{topic['region']}

## 輸出格式（JSON）
請嚴格回傳以下 JSON，不要包含任何說明文字：
```json
{{
  "events": [
    {{
      "title": "事件標題（英文或繁體中文）",
      "summary": "2-3 句摘要，說明事件經過與市場意涵",
      "category": "trade_war|sanctions|conflict|policy|election",
      "region": "asia|europe|americas|middle_east|africa|global",
      "country": "主要國家（用於座標計算，例如 Taiwan、USA、Iran）",
      "impact_score": 7.5,
      "market_impact": {{
        "sectors": ["semiconductors", "energy"],
        "assets": ["TSMC", "crude_oil"],
        "direction": "bearish|bullish|neutral",
        "note": "簡短影響說明"
      }},
      "source_url": "來源 URL（若已知，否則空字串）",
      "event_date": "YYYY-MM-DD（若已知，否則今日）"
    }}
  ]
}}
```
- impact_score: 0（無影響）到 10（極度重大）
- 請回傳 1-2 則最相關、最新的事件
- 若無可靠資訊，回傳 {{"events": []}}
"""


# Country → approximate (lat, lng) override map for precise markers
_COUNTRY_COORDS: Dict[str, Dict[str, float]] = {
    "taiwan":        {"lat": 23.6, "lng": 120.9},
    "china":         {"lat": 35.0, "lng": 104.2},
    "usa":           {"lat": 38.9, "lng": -77.0},
    "iran":          {"lat": 32.4, "lng": 53.7},
    "israel":        {"lat": 31.0, "lng": 34.9},
    "russia":        {"lat": 61.5, "lng": 90.0},
    "ukraine":       {"lat": 48.4, "lng": 31.2},
    "saudi arabia":  {"lat": 23.9, "lng": 45.1},
    "germany":       {"lat": 51.2, "lng": 10.5},
    "japan":         {"lat": 36.2, "lng": 138.3},
    "south korea":   {"lat": 36.5, "lng": 127.5},
    "india":         {"lat": 20.6, "lng": 78.9},
}


def _resolve_coords(
    country: str, region: str
) -> tuple[Optional[float], Optional[float]]:
    """Return (lat, lng) for a country/region string."""
    key = country.lower().strip() if country else ""
    if key in _COUNTRY_COORDS:
        c = _COUNTRY_COORDS[key]
        return c["lat"], c["lng"]
    rc = _REGION_COORDS.get(region.lower(), _REGION_COORDS["global"])
    return rc["lat"], rc["lng"]


# ── Intel gather per topic ───────────────────────────────────────────────────

def _gather_topic_events(
    topic_key: str,
    topic: Dict[str, Any],
    llm_calls_used: List[int],
) -> List[Dict[str, Any]]:
    """Run LLM queries for a topic, return list of raw event dicts."""
    events: List[Dict[str, Any]] = []
    for query in topic["queries"]:
        if llm_calls_used[0] >= MAX_LLM_CALLS:
            log.warning("Max LLM calls (%d) reached, stopping.", MAX_LLM_CALLS)
            break

        prompt = _build_prompt(topic_key, topic, query)
        result = call_agent_llm(prompt)
        llm_calls_used[0] += 1

        # call_agent_llm returns parsed dict; the LLM may return {"events": [...]}
        raw_events = result.get("events", [])
        if not isinstance(raw_events, list):
            raw_events = []

        for ev in raw_events:
            if not isinstance(ev, dict):
                continue
            # Merge topic defaults into event
            ev.setdefault("category", topic["category"])
            ev.setdefault("region", topic["region"])
            ev.setdefault("topic_key", topic_key)
        events.extend(raw_events)

        time.sleep(0.5)  # gentle rate limit between queries

    return events


# ── Storage ──────────────────────────────────────────────────────────────────

def _store_events(
    conn: sqlite3.Connection,
    events: List[Dict[str, Any]],
) -> int:
    """Store deduplicated events into geopolitical_events. Returns stored count."""
    stored = 0
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    for ev in events:
        url = ev.get("source_url", "") or ""
        title = ev.get("title", "") or ""

        if not title:
            continue
        if _is_duplicate(conn, url, title):
            continue

        # Determine url_hash (prefer url; fall back to title)
        uhash = _url_hash(url) if url else _title_hash(title)
        event_date = ev.get("event_date") or today
        category = ev.get("category", "policy")
        region = ev.get("region", "global")
        impact_score = float(ev.get("impact_score", 0.0))
        market_impact = ev.get("market_impact")
        market_impact_json = (
            json.dumps(market_impact, ensure_ascii=False)
            if isinstance(market_impact, dict)
            else None
        )
        country = ev.get("country", "")
        lat, lng = _resolve_coords(country, region)

        # The existing geopolitical_events table uses 'severity' not 'impact_score'.
        # Map impact_score → severity for backward compat.
        if impact_score >= 8:
            severity = "critical"
        elif impact_score >= 6:
            severity = "high"
        elif impact_score >= 3:
            severity = "medium"
        else:
            severity = "low"

        tags_json = json.dumps([category, region], ensure_ascii=False)

        try:
            conn.execute(
                """INSERT OR IGNORE INTO geopolitical_events
                   (event_date, title, summary, region, severity, tags,
                    source_url, category, impact_score, market_impact,
                    lat, lng, url_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_date,
                    title,
                    ev.get("summary", ""),
                    region,
                    severity,
                    tags_json,
                    url or None,
                    category,
                    impact_score,
                    market_impact_json,
                    lat,
                    lng,
                    uhash,
                ),
            )
            stored += 1
        except sqlite3.IntegrityError:
            pass  # duplicate url_hash unique index

    conn.commit()
    return stored


# ── Cleanup ──────────────────────────────────────────────────────────────────

def _cleanup_old_events(conn: sqlite3.Connection, days: int = RETENTION_DAYS) -> int:
    """Delete events older than `days`. Returns count deleted."""
    cutoff = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    # SQLite date arithmetic: subtract days from today
    cursor = conn.execute(
        "DELETE FROM geopolitical_events WHERE event_date < date('now', ?)",
        (f"-{days} days",),
    )
    conn.commit()
    return cursor.rowcount


# ── Open research.db connection ──────────────────────────────────────────────

def _open_research_conn() -> sqlite3.Connection:
    """Open research.db connection.

    Tries app.db.research_db first (available when PYTHONPATH includes
    frontend/backend, which is the standard runtime setup). Falls back to
    building the default path from REPO_ROOT for unit-test contexts.
    """
    try:
        from app.db.research_db import RESEARCH_DB_PATH, connect_research  # noqa: PLC0415
        return connect_research(RESEARCH_DB_PATH)
    except ImportError:
        # Fallback: construct the default path directly
        import sqlite3 as _sqlite3

        db_path = _REPO_ROOT / "data" / "sqlite" / "research.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = _sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = _sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


# ── Main entry point ─────────────────────────────────────────────────────────

def run_geopolitical_agent(
    conn: Optional[sqlite3.Connection] = None,
) -> AgentResult:
    """Run the geopolitical monitoring agent.

    Steps:
    1. Open research.db and ensure schema migrations applied
    2. For each topic, generate LLM search queries and collect events
    3. Dedup and store into geopolitical_events
    4. Write agent trace
    5. Return AgentResult

    Args:
        conn: Optional pre-opened sqlite3 connection to research.db.
              If None, opens its own connection.
    """
    _own_conn = conn is None
    _conn = conn

    try:
        if _conn is None:
            _conn = _open_research_conn()

        # Ensure extended columns exist
        _ensure_schema(_conn)

        llm_calls_used = [0]
        all_events: List[Dict[str, Any]] = []

        for topic_key, topic in TOPICS.items():
            if llm_calls_used[0] >= MAX_LLM_CALLS:
                break
            log.info("[GeopoliticalAgent] Processing topic: %s", topic["label"])
            events = _gather_topic_events(topic_key, topic, llm_calls_used)
            all_events.extend(events)

        log.info(
            "[GeopoliticalAgent] Collected %d raw events across %d topics, %d LLM calls used",
            len(all_events),
            len(TOPICS),
            llm_calls_used[0],
        )

        stored = _store_events(_conn, all_events)
        log.info("[GeopoliticalAgent] Stored %d new events", stored)

        # Cleanup
        deleted = _cleanup_old_events(_conn)
        if deleted:
            log.info("[GeopoliticalAgent] Cleaned up %d old events (>%d days)", deleted, RETENTION_DAYS)

        summary = (
            f"Geopolitical scan complete: {len(all_events)} raw events, "
            f"{stored} stored, {llm_calls_used[0]} LLM calls, "
            f"{deleted} old events cleaned"
        )

        # Write trace to research.db
        write_trace(
            _conn,
            agent="GeopoliticalAgent",
            prompt=f"geopolitical_agent run: {len(TOPICS)} topics",
            result={
                "summary": summary,
                "confidence": min(stored / max(len(all_events), 1), 1.0) if all_events else 0.0,
                "action_type": "observe",
                "proposals": [],
                "raw_events": len(all_events),
                "stored_events": stored,
                "llm_calls": llm_calls_used[0],
            },
        )

        return AgentResult(
            summary=summary,
            confidence=0.7 if stored > 0 else 0.3,
            action_type="observe",
            proposals=[],
            raw={
                "topics_scanned": len(TOPICS),
                "raw_events": len(all_events),
                "stored_events": stored,
                "llm_calls": llm_calls_used[0],
                "deleted_old": deleted,
            },
            success=True,
        )

    except Exception as e:
        log.error("[GeopoliticalAgent] Fatal error: %s", e, exc_info=True)
        return AgentResult(
            summary=f"GeopoliticalAgent failed: {e}",
            confidence=0.0,
            action_type="observe",
            proposals=[],
            raw={"error": str(e)},
            success=False,
        )

    finally:
        if _own_conn and _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
