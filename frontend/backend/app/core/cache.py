from __future__ import annotations

from functools import wraps

from cachetools import TTLCache


def cached(ttl: int = 60, maxsize: int = 128):
    """TTL cache decorator.

    Args:
        ttl: Time-to-live in seconds (default 60).
        maxsize: Maximum number of entries in the cache (default 128).

    Usage::

        @cached(ttl=300, maxsize=64)
        def expensive_lookup(symbol: str) -> dict:
            ...
    """
    cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = str(args) + str(sorted(kwargs.items()))
            if key in cache:
                return cache[key]
            result = func(*args, **kwargs)
            cache[key] = result
            return result

        # Expose the underlying cache for inspection / manual invalidation.
        wrapper.cache = cache  # type: ignore[attr-defined]
        return wrapper

    return decorator
