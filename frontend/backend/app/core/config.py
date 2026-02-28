from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings loaded from environment/.env.

    Notes:
    - Keep defaults safe for local dev.
    - Do not store secrets in code.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB
    db_path: str = Field(default="", alias="DB_PATH")

    # CORS
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    # Rate limit
    rate_limit_rpm: int = Field(default=120, alias="RATE_LIMIT_RPM")

    # Safety
    enable_rw_endpoints: bool = Field(default=False, alias="ENABLE_RW_ENDPOINTS")
    strategy_ops_token: str | None = Field(default=None, alias="STRATEGY_OPS_TOKEN")

    # Service
    service_name: str = "AI-Trader Command Center API"
    version: str = "0.1.0"

    def parse_cors_origins(self) -> List[str]:
        raw = (self.cors_origins or "").strip()
        if raw:
            return [o.strip() for o in raw.split(",") if o.strip()]
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
