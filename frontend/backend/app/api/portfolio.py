from __future__ import annotations

from fastapi import APIRouter

from app.services.shioaji_service import get_positions

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/positions")
def portfolio_positions(source: str = "mock", simulation: bool = True):
    """Return portfolio positions.

    source: mock|shioaji (default mock for speed)
    """
    source = source.lower().strip()
    if source not in {"mock", "shioaji"}:
        source = "mock"

    return {"status": "ok", **get_positions(source=source, simulation=simulation)}
