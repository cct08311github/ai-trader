from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


@dataclass
class Bucket:
    tokens: float
    last: float


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory token bucket rate limiter.

    - Per-client IP
    - Global across routes (except excluded paths)

    Notes:
    - In-memory only: suitable for single-process deployment.
    - Safe default: 120 req/min/IP.
    """

    def __init__(
        self,
        app,
        *,
        rpm: int = 120,
        burst: int | None = None,
        exclude_paths: Tuple[str, ...] = ("/api/health", "/docs", "/openapi.json", "/redoc"),
    ):
        super().__init__(app)
        self.rpm = max(1, int(rpm))
        self.capacity = float(burst if burst is not None else self.rpm)
        self.refill_per_sec = self.rpm / 60.0
        self.exclude_paths = exclude_paths
        self._buckets: Dict[str, Bucket] = {}

    def _client_key(self, request: Request) -> str:
        # Prefer X-Forwarded-For when running behind a reverse proxy (nginx, ALB, etc.)
        # to prevent bypass by clients that all appear as 127.0.0.1.
        # Take only the first (leftmost) IP which is the original client.
        forwarded_for = request.headers.get("X-Forwarded-For", "")
        host = (
            forwarded_for.split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        return host

    def _allow(self, key: str) -> bool:
        now = time.monotonic()
        b = self._buckets.get(key)
        if not b:
            self._buckets[key] = Bucket(tokens=self.capacity - 1.0, last=now)
            return True

        # refill
        elapsed = max(0.0, now - b.last)
        b.tokens = min(self.capacity, b.tokens + elapsed * self.refill_per_sec)
        b.last = now

        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(self.exclude_paths):
            return await call_next(request)

        key = self._client_key(request)
        if not self._allow(key):
            return Response(
                content='{"status":"error","detail":"Too Many Requests"}',
                status_code=429,
                media_type="application/json",
            )

        return await call_next(request)
