"""watcher_lifecycle.py — Watcher lifecycle management.

Provides the ``WatcherApp`` class that wraps the ticker_watcher's main loop
with proper lifecycle management: signal handling via ``threading.Event``
(replacing the global ``_shutdown_requested`` flag), and configurable
components via dependency injection.

This module is the future entry point for the watcher process.
Currently, ``ticker_watcher.run_watcher()`` delegates startup to this class.
"""
from __future__ import annotations

import logging
import signal
import threading
from typing import Optional

from openclaw.config_manager import ConfigManager, get_config
from openclaw.db_utils import open_watcher_conn
from openclaw.market_data_service import MarketDataService

log = logging.getLogger(__name__)


class WatcherApp:
    """Orchestrates the watcher lifecycle with thread-safe shutdown.

    Parameters
    ----------
    config : ConfigManager, optional
        Configuration manager.  Defaults to the global singleton.
    db_path : str, optional
        Override the database path.
    """

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        db_path: Optional[str] = None,
    ) -> None:
        self.config = config or get_config()
        self._db_path = db_path
        self.shutdown_event = threading.Event()
        self.market_data: Optional[MarketDataService] = None

    def request_shutdown(self) -> None:
        """Signal the watcher to stop after the current scan cycle."""
        self.shutdown_event.set()
        log.info("Shutdown requested — will exit after current scan cycle.")

    @property
    def shutdown_requested(self) -> bool:
        return self.shutdown_event.is_set()

    def install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT handlers that trigger graceful shutdown."""
        def _handler(signum: int, frame: object) -> None:
            self.request_shutdown()

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    def interruptible_sleep(self, seconds: int) -> bool:
        """Sleep for *seconds*, returning True immediately if shutdown is requested."""
        return self.shutdown_event.wait(timeout=seconds)

    def open_connection(self):
        """Open a watcher-optimised DB connection."""
        return open_watcher_conn(self._db_path)
