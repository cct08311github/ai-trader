"""signal_pipeline.py — Unified signal pipeline facade for the AI Trader system.

Consolidates signal generation, caching, and retrieval into a single entry point.
This is a FACADE: delegates to signal_generator and lm_signal_cache — no logic replication.

Usage:
    from openclaw.signal_pipeline import SignalPipeline, PipelineSignalResult

    pipeline = SignalPipeline()
    result = pipeline.compute_signals(conn, symbol="2330", position_avg_price=None,
                                      high_water_mark=None)
    # result.direction: "buy" | "sell" | "flat"
    # result.signals: {"technical": "buy", "llm_score": 0.7, "llm_direction": "bull"}
    # result.source: "technical" | "llm" | "combined"
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineSignalResult:
    """Result from SignalPipeline computation.

    Attributes:
        symbol:    Stock symbol (e.g. "2330")
        direction: Consolidated direction — "buy", "sell", or "flat"
        strength:  Confidence proxy in [0.0, 1.0]:
                     buy  → 1.0, flat → 0.5, sell → 0.0
        signals:   Raw sub-signal values for transparency/logging
        source:    Which sub-system produced the final answer:
                     "technical" | "llm" | "combined"
    """
    symbol: str
    direction: str          # "buy" | "sell" | "flat"
    strength: float         # 0.0 to 1.0
    signals: Dict[str, Any]
    source: str             # "technical" | "llm" | "combined"

    # Convenience map used internally
    _DIRECTION_TO_STRENGTH: Dict[str, float] = field(
        default_factory=lambda: {"buy": 1.0, "flat": 0.5, "sell": 0.0},
        init=False, repr=False, compare=False,
    )

    @classmethod
    def from_technical(
        cls,
        symbol: str,
        technical_signal: str,
        llm_cache: Optional[Dict[str, Any]] = None,
    ) -> "PipelineSignalResult":
        """Build a result from a technical signal string."""
        _map = {"buy": 1.0, "flat": 0.5, "sell": 0.0}
        signals: Dict[str, Any] = {"technical": technical_signal}
        if llm_cache:
            signals["llm_score"] = llm_cache.get("score")
            signals["llm_direction"] = llm_cache.get("direction")
            signals["llm_source"] = llm_cache.get("source")
            source = "combined"
        else:
            source = "technical"
        return cls(
            symbol=symbol,
            direction=technical_signal,
            strength=_map.get(technical_signal, 0.5),
            signals=signals,
            source=source,
        )


class SignalPipeline:
    """Unified entry point for signal generation.

    Acts as a FACADE over:
    - openclaw.signal_generator  (technical signals: MA cross / RSI / trailing stop)
    - openclaw.lm_signal_cache   (LLM sentiment signals written by strategy_committee)

    The pipeline does NOT duplicate calculation logic; all computation is
    delegated to the existing modules.

    Dependency injection is supported for testing:
        pipeline = SignalPipeline(signal_generator=mock_gen, cache=mock_cache)
    """

    def __init__(
        self,
        signal_generator=None,
        cache=None,
    ):
        """Initialize with optional injected dependencies.

        Args:
            signal_generator: Module or object with ``compute_signal(conn, symbol,
                              position_avg_price, high_water_mark)`` and
                              ``fetch_candles(conn, symbol, days)`` callables.
                              Defaults to the real openclaw.signal_generator module.
            cache:            Module or object with ``read_cache_with_fallback(conn,
                              symbol)`` callable.
                              Defaults to the real openclaw.lm_signal_cache module.
        """
        if signal_generator is None:
            from openclaw import signal_generator as _sg
            signal_generator = _sg
        if cache is None:
            from openclaw import lm_signal_cache as _lc
            cache = _lc

        self._generator = signal_generator
        self._cache = cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_signals(
        self,
        conn: sqlite3.Connection,
        symbol: str,
        position_avg_price: Optional[float],
        high_water_mark: Optional[float],
        trailing_pct: Optional[float] = None,
    ) -> PipelineSignalResult:
        """Compute technical signals and annotate with LLM cache if available.

        This method:
        1. Delegates to signal_generator.compute_signal() for the technical signal.
        2. Looks up lm_signal_cache for supplementary LLM context.
        3. Returns a PipelineSignalResult (technical signal is authoritative for direction).

        Args:
            conn:                 SQLite connection (read-only is sufficient).
            symbol:               Stock symbol, e.g. "2330".
            position_avg_price:   Average cost of current position, or None if flat.
            high_water_mark:      Highest price since entry, or None.
            trailing_pct:         Override default trailing-stop percentage.

        Returns:
            PipelineSignalResult with direction, strength, and sub-signal details.
        """
        # Delegate to the real signal_generator
        kwargs: Dict[str, Any] = {}
        if trailing_pct is not None:
            kwargs["trailing_pct"] = trailing_pct

        technical_signal: str = self._generator.compute_signal(
            conn,
            symbol,
            position_avg_price,
            high_water_mark,
            **kwargs,
        )

        # Enrich with LLM cache (non-blocking — failures → no enrichment)
        llm_cache: Optional[Dict[str, Any]] = None
        try:
            llm_cache = self._cache.read_cache_with_fallback(conn, symbol)
        except Exception as exc:
            logger.warning(
                "SignalPipeline: lm_signal_cache lookup failed for %s: %s",
                symbol, exc,
            )

        result = PipelineSignalResult.from_technical(symbol, technical_signal, llm_cache)
        logger.debug(
            "SignalPipeline.compute_signals: symbol=%s direction=%s source=%s signals=%s",
            symbol, result.direction, result.source, result.signals,
        )
        return result

    def get_cached_or_compute(
        self,
        conn: sqlite3.Connection,
        symbol: str,
        candles: Optional[List[Dict[str, Any]]] = None,
        position_avg_price: Optional[float] = None,
        high_water_mark: Optional[float] = None,
    ) -> PipelineSignalResult:
        """Return from LLM cache if available, otherwise compute technical signals.

        The LLM cache (written by strategy_committee) reflects a longer-horizon
        market view. When present, this method surfaces it directly; when absent
        (cache miss), it falls back to compute_signals().

        Args:
            conn:               SQLite connection.
            symbol:             Stock symbol.
            candles:            Unused; kept for API symmetry. Candles are
                                fetched from DB by signal_generator.
            position_avg_price: Average cost of current position, or None.
            high_water_mark:    Highest price since entry, or None.

        Returns:
            PipelineSignalResult — source will be "llm" on cache hit, or the
            value from compute_signals() on cache miss.
        """
        # Try LLM cache first
        llm_cache: Optional[Dict[str, Any]] = None
        try:
            llm_cache = self._cache.read_cache_with_fallback(conn, symbol)
        except Exception as exc:
            logger.warning(
                "SignalPipeline: lm_signal_cache lookup failed for %s: %s",
                symbol, exc,
            )

        if llm_cache is not None:
            _dir_map = {"bull": "buy", "neutral": "flat", "bear": "sell"}
            direction = _dir_map.get(llm_cache.get("direction", "neutral"), "flat")
            _strength_map = {"buy": 1.0, "flat": 0.5, "sell": 0.0}
            signals: Dict[str, Any] = {
                "llm_score": llm_cache.get("score"),
                "llm_direction": llm_cache.get("direction"),
                "llm_source": llm_cache.get("source"),
            }
            logger.debug(
                "SignalPipeline.get_cached_or_compute: cache hit symbol=%s direction=%s",
                symbol, direction,
            )
            return PipelineSignalResult(
                symbol=symbol,
                direction=direction,
                strength=_strength_map.get(direction, 0.5),
                signals=signals,
                source="llm",
            )

        # Cache miss — fall through to technical computation
        logger.debug(
            "SignalPipeline.get_cached_or_compute: cache miss for %s, computing technical",
            symbol,
        )
        return self.compute_signals(conn, symbol, position_avg_price, high_water_mark)
