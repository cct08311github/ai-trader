from __future__ import annotations

import logging
import os
from typing import Iterable


class SensitiveFilter(logging.Filter):
    """Best-effort filter to avoid leaking secrets into logs."""

    def __init__(self, patterns: Iterable[str] = ("token", "authorization", "password")) -> None:
        super().__init__()
        self._patterns = tuple(p.lower() for p in patterns)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            lowered = msg.lower()
            for p in self._patterns:
                if p in lowered:
                    # Redact whole message (simple/safe)
                    record.msg = "[REDACTED]"
                    record.args = ()
                    break
        except Exception:
            # Never break logging
            pass
        return True


def setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    root = logging.getLogger()
    root.addFilter(SensitiveFilter())
