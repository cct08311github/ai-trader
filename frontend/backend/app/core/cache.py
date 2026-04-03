from __future__ import annotations

import hashlib
import threading
from functools import wraps

from cachetools import TTLCache


def cached(ttl: int = 60, maxsize: int = 128):
    """TTL cache decorator with thread-safety and collision-free keys.

    Args:
        ttl: Time-to-live in seconds (default 60).
        maxsize: Maximum number of entries in the cache (default 128).

    Usage::

        @cached(ttl=300, maxsize=64)
        def expensive_lookup(symbol: str) -> dict:
            ...

    Notes:
        - Cache key includes the fully-qualified function name to prevent
          cross-function key collisions when different functions receive the
          same positional/keyword arguments.
        - A threading.Lock guards every cache read/write to ensure correctness
          under multi-threaded ASGI/WSGI servers.
    """
    cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
    lock = threading.Lock()

    def decorator(func):
        func_id = f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args, **kwargs):
            raw_key = f"{func_id}:{args}:{sorted(kwargs.items())}"
            key = hashlib.sha256(raw_key.encode()).hexdigest()

            with lock:
                if key in cache:
                    return cache[key]

            result = func(*args, **kwargs)

            with lock:
                cache[key] = result

            return result

        # Expose the underlying cache for inspection / manual invalidation.
        wrapper.cache = cache  # type: ignore[attr-defined]
        wrapper.cache_lock = lock  # type: ignore[attr-defined]
        return wrapper

    return decorator
