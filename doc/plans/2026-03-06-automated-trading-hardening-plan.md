# 2026-03-06 Automated Trading Hardening Plan

## Goal

Bring AI Trader closer to automated trading industry standards by prioritizing hard controls, reconciliation, model governance, and production observability without forcing a full architecture rewrite up front.

## Current State Summary

The system already has useful safety primitives:

- global trading switch via `config/system_state.json`
- `.EMERGENCY_STOP` fail-safe
- `risk_engine.py` strategy-layer risk evaluation
- `proposal_executor.py` intent-based sell execution
- audit tables for `decisions`, `risk_checks`, `orders`, `fills`, `llm_traces`
- simulation/live separation through broker configuration

Main gaps against industry practice:

- no non-bypassable pre-trade hard gate shared by every order path
- no formal post-trade reconciliation loop against broker truth
- limited model governance for Gemini/LLM decisions
- limited event idempotency and replay guarantees
- monitoring is log-centric, not SLI/SLO + alert centric

## Guiding Principles

1. Put hard controls closest to broker submission.
2. Prefer additive changes that preserve current strategy code paths.
3. Every new guard must emit machine-readable reason codes.
4. Every phase must include tests and rollback notes.
5. Avoid coupling phase 1 safety controls to a frontend/settings rewrite.

## Phased Roadmap

### Phase 1: Pre-Trade Hard Guard

Objective: create a broker-adjacent, reusable gate that blocks obviously unsafe orders even if strategy logic or API code is wrong.

Scope:

- add shared `pre_trade_guard` module
- enforce at least on:
  - `src/openclaw/ticker_watcher.py`
  - `src/openclaw/main.py`
  - `frontend/backend/app/api/portfolio.py` manual close path
- initial hard checks:
  - invalid qty/price
  - max order notional
  - max order quantity
  - per-symbol recent order rate cap
  - duplicate order cooldown
  - sell quantity cannot exceed known position
  - projected symbol notional cap for buys
- rejected orders must carry explicit reject codes for audit

Deliverables:

- new shared guard module
- unit tests for guard logic
- integration coverage for watcher/main submission paths

Acceptance:

- unsafe orders are rejected before `broker.submit_order()`
- existing happy-path tests remain green
- every guard rejection has a stable reason code

Rollback:

- remove guard calls or set permissive env overrides

### Phase 2: Order Lifecycle Integrity

Objective: make proposal/intention/execution transitions durable and idempotent.

Scope:

- formalize proposal state machine
- add idempotency key / execution key for intents
- add retry metadata and failure counters
- add dead-letter or failed-intents persistence
- persist execution attempts separately from final order rows

Deliverables:

- schema migration for execution journal
- proposal executor refactor
- duplicate execution prevention tests

Acceptance:

- same intent cannot create duplicate broker submissions across retries/restarts
- failed executions are inspectable and resumable

### Phase 3: Broker Reconciliation

Objective: detect and repair drift between local DB state and broker truth.

Scope:

- daily reconciliation job
- compare broker positions, orders, fills, cash, settlement with local DB
- generate incidents on mismatch
- provide dry-run and repair modes

Deliverables:

- reconciliation service/script
- incident emission rules
- operator report format

Acceptance:

- system can identify orphan orders, drifted positions, and fill mismatches automatically

### Phase 4: LLM Model Governance

Objective: treat Gemini decisions as governed models rather than opaque runtime behavior.

Scope:

- model version pinning
- prompt template versioning
- input snapshot capture
- structured decision rationale
- shadow mode for candidate strategies/prompts
- offline vs live drift metrics

Deliverables:

- trace schema extension
- prompt/model registry
- shadow evaluation pipeline

Acceptance:

- every production LLM decision is attributable to exact model/prompt/input versions

### Phase 5: Monitoring and Operational Controls

Objective: move from logs to proactive operations.

Scope:

- SLIs for quote freshness, decision latency, order reject rate, fill latency, DB lock contention, LLM failure rate
- alert thresholds
- service health summary page or API
- strategy-level kill switch and broker-send-only kill switch

Deliverables:

- metrics emitters
- dashboard wiring
- runbook updates

Acceptance:

- operators can detect degraded trading conditions before trading loss manifests

## Execution Order

1. Phase 1 pre-trade hard guard
2. Phase 2 order lifecycle integrity
3. Phase 3 broker reconciliation
4. Phase 4 LLM governance
5. Phase 5 monitoring and operational controls

## Phase 1 Implementation Notes

Recommended default hard limits for initial rollout:

- `max_order_qty = 2000`
- `max_order_notional = 500000 TWD`
- `max_symbol_position_notional = 1200000 TWD`
- `max_orders_per_symbol_window = 2`
- `recent_order_window_sec = 600`
- `duplicate_order_window_sec = 30`

These are intentionally conservative and should be overridable by env or call-site config during rollout.

## Test Strategy

- unit tests for pure guard evaluation
- watcher execution tests to prove broker is never called on blocked orders
- main execution tests to prove hard guard rejects before network/broker flow
- manual close API tests for blocked sell quantity or malformed order parameters

## Risks

- thresholds may be too strict for current watchlist turnover
- duplicate detection can block legitimate rapid re-entry if cooldown is too wide
- manual close path needs special handling so emergency exits are not accidentally blocked by buy-side limits

## Immediate Next Step

Implement Phase 1 with a shared `pre_trade_guard` and wire it into all order submission paths.
