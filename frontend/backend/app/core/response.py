from __future__ import annotations

from typing import Any, Optional


def api_response(
    data: Any,
    *,
    total: Optional[int] = None,
    page: int = 1,
    per_page: int = 50,
    source: Optional[str] = None,
    freshness: Optional[str] = None,
    cache_hit: bool = False,
) -> dict:
    """Build a unified API response envelope.

    Args:
        data: The primary payload (list, dict, or scalar).
        total: Total record count for paginated responses.
        page: Current page number (1-indexed).
        per_page: Records per page.
        source: Data origin label (e.g. ``"sqlite"``, ``"yfinance"``).
        freshness: ISO-8601 timestamp or human label for data age.
        cache_hit: Whether the result was served from cache.

    Returns:
        A dict with ``status``, ``data``, and ``meta`` keys.

    Example::

        return api_response(rows, total=len(rows), source="sqlite", cache_hit=True)
    """
    return {
        "status": "ok",
        "data": data,
        "meta": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "data_freshness": freshness,
            "source": source,
            "cache_hit": cache_hit,
        },
    }
