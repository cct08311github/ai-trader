"""log_utils.py — Logging utilities for the AI Trader core engine.

Provides a lightweight structured logging adapter and establishes
the naming convention for future modules.

Convention
----------
New modules should use::

    import logging
    logger = logging.getLogger(__name__)

Existing modules using ``log`` or ``_log`` are accepted but should
migrate to ``logger`` over time.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional


class StructuredAdapter(logging.LoggerAdapter):
    """Logger adapter that appends structured key-value pairs.

    Usage::

        from openclaw.log_utils import get_structured_logger
        logger = get_structured_logger(__name__, component="watcher")
        logger.info("scan complete", extra={"symbols": 15, "duration_ms": 320})
        # Output: scan complete | {"component": "watcher", "symbols": 15, "duration_ms": 320}
    """

    def process(
        self,
        msg: str,
        kwargs: Dict[str, Any],
    ) -> tuple[str, Dict[str, Any]]:
        extra = {**self.extra, **kwargs.pop("extra", {})}
        if extra:
            suffix = json.dumps(extra, default=str, ensure_ascii=False)
            return f"{msg} | {suffix}", kwargs
        return msg, kwargs


def get_structured_logger(
    name: str,
    *,
    component: Optional[str] = None,
    **extra: Any,
) -> StructuredAdapter:
    """Create a structured logger with default extra fields.

    Parameters
    ----------
    name : str
        Logger name (typically ``__name__``).
    component : str, optional
        Component identifier added to every message.
    **extra
        Additional key-value pairs for every message.
    """
    base = logging.getLogger(name)
    defaults: Dict[str, Any] = {}
    if component:
        defaults["component"] = component
    defaults.update(extra)
    return StructuredAdapter(base, defaults)
