from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


# NOTE:
# OpenClaw v4 stability rule: runtime LLM model ids MUST be pinned.
# This registry enforces a small allowlist and provides alias -> pinned resolution.
#
# Keys: user-facing / legacy ids that may appear in configs/tests.
# Values: pinned provider model ids that are safe to call.
ALLOWED_MODELS: Dict[str, str] = {
    # MiniMax (primary strategy LLM)
    "minimax/MiniMax-M2.5": "MiniMax-M2.5",
    "MiniMax-M2.5": "MiniMax-M2.5",

    # Google Gemini (kept for backward compat / fallback)
    "google/gemini-1.5-pro-002": "google/gemini-1.5-pro-002",
    "google/gemini-1.5-flash-002": "google/gemini-1.5-flash-002",
    "google/gemini-3.1-pro-001": "google/gemini-3.1-pro-001",
    "google/gemini-3.0-flash-001": "google/gemini-3.0-flash-001",

    # Legacy aliases (kept to avoid breaking existing pipelines/tests)
    "gemini-3.1-pro": "google/gemini-3.1-pro-001",
    "gemini-3.0-flash": "google/gemini-3.0-flash-001",
}


@dataclass
class UnauthorizedModelError(ValueError):
    code: str
    model_id: str
    allowed_models: tuple[str, ...]

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"{self.code}: model_id={self.model_id!r} is not in allowlist; "
            f"allowed={list(self.allowed_models)}"
        )


def is_model_allowed(model_id: str) -> bool:
    if not isinstance(model_id, str):
        return False
    mid = model_id.strip()
    if not mid:
        return False
    return mid in ALLOWED_MODELS


def resolve_pinned_model_id(model_id: str) -> str:
    """Return a pinned model id for an allowed model.

    Raises:
        UnauthorizedModelError: when model_id is not in the allowlist.
    """

    mid = (model_id or "").strip()
    if not is_model_allowed(mid):
        raise UnauthorizedModelError(
            code="LLM_MODEL_NOT_ALLOWED",
            model_id=mid,
            allowed_models=tuple(sorted(ALLOWED_MODELS.keys())),
        )
    return ALLOWED_MODELS[mid]
