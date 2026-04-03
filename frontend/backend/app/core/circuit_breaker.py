from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"      # Normal — calls pass through.
    OPEN = "open"          # Degraded — calls fail fast.
    HALF_OPEN = "half_open"  # Probe — one trial call allowed.


class CircuitBreakerError(Exception):
    """Raised when the circuit is OPEN and the call is rejected."""


class CircuitBreaker:
    """Simple failure-counting circuit breaker.

    States:
    - CLOSED  → calls execute normally; failures are counted.
    - OPEN    → calls are rejected immediately after *failure_threshold* consecutive
                failures; the circuit opens for *reset_timeout* seconds.
    - HALF_OPEN → after *reset_timeout* elapses, one trial call is allowed.
                  Success → CLOSED (counter reset).
                  Failure → OPEN again (timer restarted).

    Args:
        failure_threshold: Consecutive failures before tripping (default 5).
        reset_timeout: Seconds to wait before attempting a probe call (default 300).
        name: Optional label used in log messages.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 300,
        name: str = "circuit_breaker",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.name = name

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_timeout()
            return self._state

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute *func* through the circuit breaker.

        Raises:
            CircuitBreakerError: When the circuit is OPEN.
            Exception: Any exception raised by *func* itself (also recorded as failure).
        """
        with self._lock:
            self._evaluate_timeout()
            current_state = self._state

        if current_state == CircuitState.OPEN:
            with self._lock:
                secs = self._seconds_until_probe()
            raise CircuitBreakerError(
                f"[{self.name}] Circuit is OPEN — call rejected. "
                f"Retry after {secs:.0f}s."
            )

        if current_state == CircuitState.HALF_OPEN:
            return self._probe(func, *args, **kwargs)

        # CLOSED — normal execution.
        return self._execute(func, *args, **kwargs)

    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
        logger.info("[%s] Circuit manually reset to CLOSED.", self.name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_timeout(self) -> None:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.reset_timeout:
                logger.info(
                    "[%s] Reset timeout elapsed (%.0fs); entering HALF_OPEN.",
                    self.name,
                    elapsed,
                )
                self._state = CircuitState.HALF_OPEN

    def _execute(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            raise

    def _probe(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Single trial call in HALF_OPEN state."""
        try:
            result = func(*args, **kwargs)
            logger.info("[%s] Probe succeeded; circuit CLOSED.", self.name)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            return result
        except Exception as exc:
            logger.warning("[%s] Probe failed; circuit re-OPENED. Error: %s", self.name, exc)
            self._trip()
            raise

    def _on_success(self) -> None:
        with self._lock:
            if self._failure_count:
                logger.debug("[%s] Success; failure counter reset.", self.name)
            self._failure_count = 0

    def _on_failure(self, exc: Exception) -> None:
        with self._lock:
            self._failure_count += 1
            count = self._failure_count
            threshold = self.failure_threshold
        logger.warning(
            "[%s] Failure %d/%d: %s",
            self.name,
            count,
            threshold,
        )
        if count >= threshold:
            self._trip()

    def _trip(self) -> None:
        with self._lock:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            count = self._failure_count
        logger.error(
            "[%s] Circuit OPEN after %d consecutive failures. Will probe in %ds.",
            self.name,
            count,
            self.reset_timeout,
        )

    def _seconds_until_probe(self) -> float:
        if self._opened_at is None:
            return 0.0
        remaining = self.reset_timeout - (time.monotonic() - self._opened_at)
        return max(0.0, remaining)
