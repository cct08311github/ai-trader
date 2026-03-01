"""Auth API — login endpoint.

Simple credential-based login that returns a Bearer token.
Credentials are configured via env vars:
    AUTH_USERNAME (default: admin)
    AUTH_PASSWORD (required, no default)
    AUTH_TOKEN    (the token returned on successful login)
"""
from __future__ import annotations

import os
import hmac
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    status: str = "ok"
    token: str
    message: str = "登入成功"


def _get_credentials() -> tuple[str, str]:
    username = os.environ.get("AUTH_USERNAME", "admin").strip()
    password = os.environ.get("AUTH_PASSWORD", "").strip()
    return username, password


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest):
    """Authenticate and return a Bearer token.

    This is a simple single-user auth. The token returned is the same
    AUTH_TOKEN used by the middleware — effectively a session-less design
    suited for a single-operator trading dashboard behind Tailscale VPN.
    """
    expected_user, expected_pass = _get_credentials()

    if not expected_pass:
        raise HTTPException(
            status_code=503,
            detail="AUTH_PASSWORD 未設定，請在 .env 中設定 AUTH_PASSWORD",
        )

    # Constant-time comparison
    user_ok = hmac.compare_digest(req.username.encode(), expected_user.encode())
    pass_ok = hmac.compare_digest(req.password.encode(), expected_pass.encode())

    if not (user_ok and pass_ok):
        logger.warning("Failed login attempt: username=%s", req.username)
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    # Return the auth token (same one the middleware validates)
    from app.middleware.auth import AuthMiddleware
    token = os.environ.get("AUTH_TOKEN", "").strip()

    # If token was auto-generated, retrieve from the middleware instance
    # For simplicity, just read from env
    if not token:
        raise HTTPException(
            status_code=503,
            detail="AUTH_TOKEN 未設定，請在 .env 中設定 AUTH_TOKEN",
        )

    return LoginResponse(token=token)


@router.get("/check")
def check_auth():
    """Check if the current token is valid.

    This endpoint IS protected by the auth middleware, so if the request
    reaches here, the token is valid.
    """
    return {"status": "ok", "authenticated": True}
