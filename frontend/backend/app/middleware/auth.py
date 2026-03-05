"""Bearer Token authentication middleware.

Design doc §5.2: "FastAPI 後端加入基本認證（Bearer Token），即便 Tailscale
網路被突破，仍有第二層保護。"

Configuration via .env:
    AUTH_TOKEN=<your-secret-token>
    AUTH_ENABLED=true  (default: true)

Excluded paths (no auth required):
    - POST /api/auth/login
    - GET  /api/health
    - /docs, /openapi.json, /redoc
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_EXCLUDE_PREFIXES = (
    "/api/auth/login",
    "/api/health",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _constant_time_compare(a: str, b: str) -> bool:
    """Prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


class AuthMiddleware(BaseHTTPMiddleware):
    """Simple Bearer Token middleware.

    If AUTH_TOKEN env is not set, a random token is generated on startup and
    printed to stdout (convenient for first-time setup).
    """

    def __init__(self, app, *, enabled: bool = True):
        super().__init__(app)
        self.enabled = enabled
        self.token = os.environ.get("AUTH_TOKEN", "").strip()

        if self.enabled and not self.token:
            self.token = secrets.token_urlsafe(32)
            logger.warning(
                "AUTH_TOKEN not set — auto-generated token: %s  "
                "(add AUTH_TOKEN=<token> to .env to persist)",
                self.token,
            )

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        path = request.url.path

        # Skip auth for excluded paths
        if any(path.startswith(p) for p in _EXCLUDE_PREFIXES):
            return await call_next(request)

        # Extract Bearer token (from header or query parameter for SSE)
        auth_header = request.headers.get("authorization", "")
        provided_token = ""
        
        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:]
        elif path.startswith("/api/stream/") or "/proposals/" in path:
            # SSE streams and proposal approve/reject URL buttons use token query param
            provided_token = request.query_params.get("token", "")

        if not provided_token:
            return JSONResponse(
                status_code=401,
                content={"status": "error", "detail": "未授權：缺少 Bearer Token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not _constant_time_compare(provided_token, self.token):
            return JSONResponse(
                status_code=401,
                content={"status": "error", "detail": "未授權：無效的 Token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
