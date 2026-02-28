from __future__ import annotations

import os
from typing import List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.portfolio import router as portfolio_router
from app.api.control import router as control_router
from app.api.settings import router as settings_router
from app.api.strategy import router as strategy_router

def _parse_cors_origins() -> List[str]:

    """Parse CORS origins from env.

    - CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
    - Default: common local dev origins
    """

    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]

    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


app = FastAPI(title="AI-Trader Command Center API", version="0.1.0")

# CORS: allow frontend to call API
cors_origins = _parse_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": "Command Center API"}


# Routers
app.include_router(control_router)
app.include_router(settings_router)

app.include_router(strategy_router)
app.include_router(portfolio_router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
