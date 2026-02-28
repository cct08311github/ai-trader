from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.core.config import Settings
from app.repositories.strategy_repository import StrategyRepository


class StrategyService:
    def __init__(self, repo: StrategyRepository | None = None) -> None:
        self.repo = repo or StrategyRepository()

    def list_proposals(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = self.repo.get_proposals(conn, limit=limit, offset=offset, status=status)
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}

    def list_logs(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 50,
        offset: int = 0,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = self.repo.get_logs(conn, limit=limit, offset=offset, trace_id=trace_id)
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}

    def ensure_rw_allowed(self, settings: Settings) -> None:
        if not settings.enable_rw_endpoints:
            raise HTTPException(
                status_code=405,
                detail="RW endpoints are disabled (ENABLE_RW_ENDPOINTS=false). Backend enforces read-only SQLite by default.",
            )
