from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.agents import router as agents_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.control import router as control_router
from app.api.pm import router as pm_router
from app.api.portfolio import router as portfolio_router
from app.api.settings import router as settings_router
from app.api.strategy import router as strategy_router
from app.api.stream import router as stream_router
from app.api.system import router as system_router
from app.api.system import inventory_router, capital_router
from app.core.config import get_settings
from app.core.errors import http_exception_handler, unhandled_exception_handler
from app.core.logging import setup_logging
from app.db import DB_PATH, READONLY_POOL, init_readonly_pool
from app.middleware.auth import AuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# Load .env early (pydantic-settings also loads, but this helps other libs)
load_dotenv()
setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    try:
        init_readonly_pool(DB_PATH)
        logger.info("SQLite readonly pool initialized size=%s path=%s", READONLY_POOL.size, DB_PATH)
    except Exception as e:
        logger.warning("Failed to init readonly pool: %s", e)
    yield
    # shutdown
    try:
        READONLY_POOL.close()
    except Exception:
        pass


app = FastAPI(title=settings.service_name, version=settings.version, lifespan=lifespan)

# Exception handlers (unified error shape)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
app.add_middleware(RateLimitMiddleware, rpm=settings.rate_limit_rpm)

# Auth (design doc §5.2: Bearer Token as second layer behind Tailscale)
auth_enabled = os.environ.get("AUTH_ENABLED", "true").lower() not in ("false", "0", "no")
app.add_middleware(AuthMiddleware, enabled=auth_enabled)


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": settings.service_name}


# Routers
app.include_router(agents_router)
app.include_router(analysis_router)
app.include_router(auth_router)
app.include_router(control_router)
app.include_router(pm_router)
app.include_router(settings_router)
app.include_router(strategy_router)
app.include_router(portfolio_router)
app.include_router(stream_router)
app.include_router(system_router)
app.include_router(inventory_router)
app.include_router(capital_router)
app.include_router(chat_router)
