"""intel_dedup.py — Intelligence deduplication for competitor monitoring.

URL hash dedup + title similarity (Jaccard > 0.7 = duplicate).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Dict, List, Optional, Set


def url_hash(url: str) -> str:
    """Compute SHA-256 hash of a normalized URL."""
    normalized = url.strip().lower().rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _tokenize(text: str) -> Set[str]:
    """Tokenize text into a set of lowercase words."""
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower()))


def jaccard_similarity(a: str, b: str) -> float:
    """Compute Jaccard similarity between two text strings."""
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def is_duplicate_by_title(
    title: str,
    existing_titles: List[str],
    threshold: float = 0.7,
) -> bool:
    """Check if title is a near-duplicate of any existing title."""
    for existing in existing_titles:
        if jaccard_similarity(title, existing) > threshold:
            return True
    return False


def is_duplicate_by_url(
    conn: sqlite3.Connection,
    check_url: str,
) -> bool:
    """Check if a URL (by hash) already exists in competitor_intel table."""
    h = url_hash(check_url)
    row = conn.execute(
        "SELECT 1 FROM competitor_intel WHERE url_hash = ? LIMIT 1", (h,)
    ).fetchone()
    return row is not None


def dedup_intel_items(
    conn: sqlite3.Connection,
    items: List[Dict],
) -> List[Dict]:
    """Filter out duplicate intel items by URL hash and title similarity.

    Each item should have 'url' and 'title' keys.
    Returns only non-duplicate items.
    """
    seen_urls: Set[str] = set()
    accepted_titles: List[str] = []
    result: List[Dict] = []

    for item in items:
        item_url = item.get("url", "")
        item_title = item.get("title", "")

        # Skip if URL already in DB
        if item_url and is_duplicate_by_url(conn, item_url):
            continue

        # Skip if URL already seen in this batch
        h = url_hash(item_url) if item_url else ""
        if h and h in seen_urls:
            continue

        # Skip if title is too similar to an accepted item
        if item_title and is_duplicate_by_title(item_title, accepted_titles):
            continue

        if h:
            seen_urls.add(h)
        if item_title:
            accepted_titles.append(item_title)
        result.append(item)

    return result
