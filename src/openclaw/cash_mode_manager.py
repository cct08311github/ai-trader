"""Cash Mode Manager - Integrates cash_mode decisions into the trading system.

This module provides:
1. Persistent storage of cash mode state
2. Integration with market regime analysis
3. Configuration management
4. Status reporting and monitoring
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, Any

from openclaw.cash_mode import (
    CashModeDecision,
    CashModePolicy,
    evaluate_cash_mode,
    apply_cash_mode_to_system_state,
)
from openclaw.market_regime import MarketRegimeResult
from openclaw.risk_engine import SystemState

logger = logging.getLogger(__name__)


@dataclass
class CashModeState:
    """Current cash mode state with metadata."""
    
    is_active: bool
    rating: float
    reason_code: str
    detail: Dict[str, Any]
    timestamp_ms: int
    market_regime: str
    confidence: float


class CashModeManager:
    """Manages cash mode state and integrates with the trading system."""
    
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._init_db()
        self.current_state: Optional[CashModeState] = None
        self.policy = CashModePolicy.default()
    
    def _init_db(self) -> None:
        """Initialize database tables for cash mode state tracking."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cash_mode_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_ms INTEGER NOT NULL,
                    is_active INTEGER NOT NULL,
                    rating REAL NOT NULL,
                    reason_code TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    confidence REAL NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cash_mode_config (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
            """)
            
            # Store default policy
            default_policy = {
                "enter_below_rating": 35.0,
                "exit_above_rating": 55.0,
                "enter_on_bear_regime": True,
                "bear_min_confidence": 0.45,
                "emergency_volatility_threshold": 0.07
            }
            
            conn.execute(
                "INSERT OR REPLACE INTO cash_mode_config (key, value_json) VALUES (?, ?)",
                ("policy", json.dumps(default_policy))
            )
    
    def load_policy(self) -> CashModePolicy:
        """Load cash mode policy from database."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value_json FROM cash_mode_config WHERE key = ?",
                ("policy",)
            ).fetchone()
            
            if row:
                policy_data = json.loads(row[0])
                return CashModePolicy(**policy_data)
            
            return CashModePolicy.default()
    
    def save_policy(self, policy: CashModePolicy) -> None:
        """Save cash mode policy to database."""
        policy_data = {
            "enter_below_rating": policy.enter_below_rating,
            "exit_above_rating": policy.exit_above_rating,
            "enter_on_bear_regime": policy.enter_on_bear_regime,
            "bear_min_confidence": policy.bear_min_confidence,
            "emergency_volatility_threshold": policy.emergency_volatility_threshold
        }
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cash_mode_config (key, value_json) VALUES (?, ?)",
                ("policy", json.dumps(policy_data))
            )
    
    def evaluate(
        self,
        market_regime_result: MarketRegimeResult,
        current_system_state: SystemState
    ) -> Tuple[CashModeDecision, SystemState]:
        """Evaluate cash mode based on market regime and update system state."""
        
        # Get current cash mode state
        current_cash_mode = current_system_state.reduce_only_mode
        
        # Evaluate cash mode decision
        decision = evaluate_cash_mode(
            market_regime_result,
            current_cash_mode=current_cash_mode,
            policy=self.policy
        )
        
        # Apply decision to system state
        new_system_state = apply_cash_mode_to_system_state(
            current_system_state,
            decision
        )
        
        # Store state for reporting
        self.current_state = CashModeState(
            is_active=decision.cash_mode,
            rating=decision.rating,
            reason_code=decision.reason_code,
            detail=decision.detail,
            timestamp_ms=int(time.time() * 1000),
            market_regime=market_regime_result.regime.value,
            confidence=float(market_regime_result.confidence)
        )
        
        # Log to database
        self._log_decision(decision, market_regime_result)
        
        # Log state change if applicable
        if decision.cash_mode != current_cash_mode:
            logger.info(
                "Cash mode changed: %s -> %s (reason: %s, rating: %.1f)",
                current_cash_mode,
                decision.cash_mode,
                decision.reason_code,
                decision.rating
            )
        
        return decision, new_system_state
    
    def _log_decision(self, decision: CashModeDecision, market_regime_result: MarketRegimeResult) -> None:
        """Log cash mode decision to database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cash_mode_history (
                    timestamp_ms, is_active, rating, reason_code,
                    detail_json, market_regime, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(time.time() * 1000),
                    1 if decision.cash_mode else 0,
                    decision.rating,
                    decision.reason_code,
                    json.dumps(decision.detail),
                    market_regime_result.regime.value,
                    float(market_regime_result.confidence)
                )
            )
    
    def get_status_report(self) -> Dict[str, Any]:
        """Get current cash mode status report."""
        if not self.current_state:
            return {
                "cash_mode_active": False,
                "status": "UNINITIALIZED",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        return {
            "cash_mode_active": self.current_state.is_active,
            "rating": self.current_state.rating,
            "reason_code": self.current_state.reason_code,
            "market_regime": self.current_state.market_regime,
            "confidence": self.current_state.confidence,
            "policy": {
                "enter_below_rating": self.policy.enter_below_rating,
                "exit_above_rating": self.policy.exit_above_rating,
                "enter_on_bear_regime": self.policy.enter_on_bear_regime,
                "bear_min_confidence": self.policy.bear_min_confidence,
                "emergency_volatility_threshold": self.policy.emergency_volatility_threshold
            },
            "timestamp": datetime.fromtimestamp(
                self.current_state.timestamp_ms / 1000, timezone.utc
            ).isoformat(),
            "detail": self.current_state.detail
        }
    
    def get_history(self, limit: int = 100) -> list[Dict[str, Any]]:
        """Get cash mode history."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT timestamp_ms, is_active, rating, reason_code,
                       detail_json, market_regime, confidence
                FROM cash_mode_history
                ORDER BY timestamp_ms DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            history = []
            for row in rows:
                history.append({
                    "timestamp": datetime.fromtimestamp(row[0] / 1000, timezone.utc).isoformat(),
                    "is_active": bool(row[1]),
                    "rating": row[2],
                    "reason_code": row[3],
                    "detail": json.loads(row[4]),
                    "market_regime": row[5],
                    "confidence": row[6]
                })
            
            return history


# Global instance for easy access
_cash_mode_manager: Optional[CashModeManager] = None


def get_cash_mode_manager(db_path: str = ":memory:") -> CashModeManager:
    """Get or create global cash mode manager instance."""
    global _cash_mode_manager
    if _cash_mode_manager is None:
        _cash_mode_manager = CashModeManager(db_path)
    return _cash_mode_manager


def integrate_with_decision_pipeline(
    market_regime_result: MarketRegimeResult,
    system_state: SystemState,
    db_conn: sqlite3.Connection
) -> Tuple[SystemState, Dict[str, Any]]:
    """
    Integrate cash mode evaluation into decision pipeline.
    
    This function should be called from the main decision pipeline
    before evaluating individual trade decisions.
    """
    
    # Get cash mode manager (use existing database connection)
    manager = CashModeManager(db_path=":memory:")  # Use same connection
    
    # Evaluate cash mode
    decision, new_system_state = manager.evaluate(
        market_regime_result,
        system_state
    )
    
    # Log to main database if needed
    cursor = db_conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO cash_mode_state (
            id, is_active, rating, reason_code, detail_json,
            market_regime, confidence, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            1 if decision.cash_mode else 0,
            decision.rating,
            decision.reason_code,
            json.dumps(decision.detail),
            market_regime_result.regime.value,
            float(market_regime_result.confidence)
        )
    )
    
    status_report = manager.get_status_report()
    
    return new_system_state, status_report
