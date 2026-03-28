"""guards — Pluggable guard chain for the decision pipeline.

Each guard implements the ``Guard`` protocol and can independently
approve or reject a trade decision.  Guards are evaluated in sequence;
the first rejection short-circuits the pipeline.

Usage::

    from openclaw.guards import GuardChain, GuardContext
    from openclaw.guards.system_switch_guard import SystemSwitchGuard
    from openclaw.guards.sentinel_guard import SentinelGuard

    chain = GuardChain([SystemSwitchGuard(), SentinelGuard()])
    result = chain.evaluate(ctx)
"""
from openclaw.guards.base import Guard, GuardChain, GuardContext, GuardResult

__all__ = ["Guard", "GuardChain", "GuardContext", "GuardResult"]
