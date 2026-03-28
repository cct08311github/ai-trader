"""Tests for openclaw.log_utils."""
from __future__ import annotations

import logging

from openclaw.log_utils import StructuredAdapter, get_structured_logger


class TestStructuredAdapter:
    def test_appends_extra_as_json(self, caplog):
        logger = get_structured_logger("test_logger", component="watcher")
        with caplog.at_level(logging.INFO, logger="test_logger"):
            logger.info("scan done", extra={"symbols": 5})
        assert "scan done |" in caplog.text
        assert '"component": "watcher"' in caplog.text
        assert '"symbols": 5' in caplog.text

    def test_no_extra_no_suffix(self, caplog):
        base = logging.getLogger("test_plain")
        adapter = StructuredAdapter(base, {})
        with caplog.at_level(logging.INFO, logger="test_plain"):
            adapter.info("simple message")
        assert "simple message" in caplog.text
        assert "|" not in caplog.text

    def test_default_component(self, caplog):
        logger = get_structured_logger("test_comp", component="risk")
        with caplog.at_level(logging.INFO, logger="test_comp"):
            logger.info("check")
        assert '"component": "risk"' in caplog.text
