"""repositories — Data access layer for the AI Trader core engine.

Each repository encapsulates SQL operations for a specific domain,
replacing scattered raw SQL across 10+ modules.
"""
from openclaw.repositories.order_repository import OrderRepository
from openclaw.repositories.position_repository import PositionRepository
from openclaw.repositories.trace_repository import TraceRepository
from openclaw.repositories.decision_repository import DecisionRepository
from openclaw.repositories.signal_repository import SignalRepository
from openclaw.repositories.pnl_repository import PnLRepository
from openclaw.repositories.proposal_repository import ProposalRepository

__all__ = [
    "OrderRepository",
    "PositionRepository",
    "TraceRepository",
    "DecisionRepository",
    "SignalRepository",
    "PnLRepository",
    "ProposalRepository",
]
