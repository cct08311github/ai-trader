# AI Trader Hardening Progress

Last updated: 2026-03-07 22:15 Asia/Taipei

## Coordination

- Primary coordination file for parallel AI work.
- Update this file after every meaningful batch.
- Keep entries factual: branch, worktree, scope, tests, commit, next step.
- **Checklist format**: `[x]` = done, `[ ]` = pending. Sub-tasks indented under parent.

## Active Branch

- `main` — sole active mainline
- path: `/Users/openclaw/.openclaw/shared/projects/ai-trader`
- all retired worktrees (`codex/integration-recovery`, `codex/remediation-api`, `codex/system-ops-ui`, `codex/operator-drilldown`) have been merged and deleted
- runtime config stash has been dropped (all obsolete)

## Completed Checklist

### Batch 1–15: Operator Hardening & Stash Recovery

- [x] `a253377` harden operator incident workflows
- [x] `c7822a3` auto-lock trading on reconciliation drift
- [x] `8e98f32` reconciliation quarantine workflow
- [x] `cba9fc5` reversible quarantine controls
- [x] `cad1a10` quarantine remediation API (`/api/system/quarantine-plan`, `apply`, `clear`)
- [x] `1337b7e` remediation audit trail (`/api/system/remediation-history`)
- [x] `1741e2f` incident resolution API (`/api/system/incidents/open`, `resolve`)
- [x] `25ae475` incident resolution CLI (`tools/run_incident_resolution.py`)
- [x] `1a31836` shared progress ledger
- [x] integration verification (cherry-pick + tests green)
- [x] mainline consolidation (retired split worktrees)
- [x] main promotion (fast-forward to `f4ef55b`)
- [x] stash recovery batch 1: pre_trade_guard, llm_governance, proposal execution journal
- [x] stash recovery batch 2: `/api/reports/context` + tests
- [x] stash recovery batch 3: AGENTS.md, doc/plans

### Batch 16: P0 + P1 Hardening (2026-03-07)

- [x] **P0: Reconciliation mismatch root cause** — `d298ebf`
  - [x] root cause identified: simulation mode = broker always empty → structural false positive
  - [x] `operator_jobs.py`: skip auto-lock when `resolved_simulation=True`
  - [x] `broker_reconciliation.py`: skip incident when simulation + `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
  - [x] reconciliation report still written for audit
  - [x] resolved 1 false positive incident in DB
  - [x] added live-mode auto-lock positive test
  - [x] tests: 12/12 reconciliation + 37/37 operator/system
- [x] **P0: Network allowlist incident root cause** — `d298ebf`
  - [x] root cause: 430 incidents are test artifacts (fake IPs `8.8.8.8`, `203.0.113.10`)
  - [x] `OPENCLAW_IP_ALLOWLIST` not set → no-op in production
  - [x] resolved 2 open incidents → 0 open incidents remain
- [x] **P1: PM2 and operator runbook validation** — `92aaf7f`
  - [x] PM2 process list matches ecosystem.config.js (7 services + 1 external `agent-monitor-web`)
  - [x] 3 cron jobs produce output in `data/ops/` as documented
  - [x] no stale worktree/branch references in docs
- [x] **P1: Runtime config snapshot review** — `92aaf7f`
  - [x] inspected `stash@{0}`: all 3 configs obsolete
  - [x] dropped stash
- [x] **P1: Eliminate owned-code deprecation warnings** — `f22c3d3`
  - [x] replaced 5 owned `utcnow()` → `datetime.now(UTC)`
  - [x] fixed 2 test files
  - [x] strict `-W error::DeprecationWarning` passes 101/101
- [x] **P1: Expand regression coverage** — `c45d9f2`
  - [x] reports API: invalid type, missing auth, DB error, missing chips/analysis tables
  - [x] pre-trade guard: 3 env override tests
  - [x] execution journal stale recovery (completed in Batch 19)

### Batch 17: Documentation Sync + QA Refresh (2026-03-07)

- [x] **P2: Reports API documentation and consumer-facing docs**
  - [x] document `/api/reports/context` in AGENTS.md § FastAPI 後端 → API 路由
  - [x] document auth: requires `Authorization: Bearer <token>` header
  - [x] document response shape: `{status, report_type, real_holdings, simulated_positions, technical_indicators, institution_chips, recent_trades, eod_analysis, system_state}`
  - [x] document query params: `type=morning|evening|weekly` (default: morning)
  - [x] document `PORTFOLIO_JSON_PATH` missing-file fallback behavior
- [x] **P2: Operator/hardening doc sync**
  - [x] CLAUDE.md § 測試規範 updated with simulation-aware reconciliation rule
  - [x] AGENTS.md § 測試規範 updated with simulation-aware reconciliation rule
  - [x] AGENTS.md § 變更歷史 added `v4.14.0`
  - [x] operator runbook added simulation-aware reconciliation behavior note
  - [x] operator runbook added incident cleanup procedures used in batch 16
- [x] **QA refresh for completed work**
  - [x] `frontend/backend/tests/test_reports_api.py`
  - [x] `frontend/backend/tests/test_system_api.py`
  - [x] `frontend/backend/tests/test_main.py`
  - [x] `src/tests/test_broker_reconciliation.py`
  - [x] `src/tests/test_operator_jobs.py`
  - [x] `bin/run_ops_summary.sh`
  - [x] `bin/run_reconciliation.sh` (expected exit `1` with audit mismatch report under simulation)

### Batch 18: Ops Summary Metric Alignment (2026-03-07)

- [x] **P1: reconcile `reconciliation_mismatches_24h` warning metric with simulation-aware semantics**
  - [x] `ops_health.py` now prioritizes unresolved `broker_reconciliation` incidents over raw historical reports
  - [x] simulation-only or already-resolved historical reports no longer push `ops-summary` into warning
  - [x] added operator job test for simulation-only reconciliation metric suppression
  - [x] added system API test for `/api/system/ops-summary` metric suppression
  - [x] fresh `bin/run_ops_summary.sh` snapshot now shows `reconciliation_mismatches_24h=0`
  - [x] fresh `bin/run_ops_summary.sh` snapshot now shows `overall=ok`

### Batch 19: Parallel Recovery Follow-up (2026-03-07)

- [x] **P1 Deferred: Execution journal stale recovery test**
  - [x] created isolated worktree `codex/execution-journal-e2e`
  - [x] added watcher-path integration regression for stale journal recovery → successful completion — `1ac4284`, cherry-picked as `59cc09b`
  - [x] added watcher-path integration regression for broker failure → no infinite retry — `1ac4284`, cherry-picked as `59cc09b`
  - [x] QA: `src/tests/test_ticker_watcher.py` + `src/tests/test_proposal_executor.py`
- [x] **P2 Reports API consumer integration**
  - [x] created isolated worktree `codex/reports-consumer-followup`
  - [x] added `src/openclaw/report_context_client.py` as the canonical in-repo consumer helper — `fcfe5c0`, cherry-picked as `1eacca0`
  - [x] added `tools/fetch_report_context.py` CLI for operator/agent usage — `fcfe5c0`, cherry-picked as `1eacca0`
  - [x] added `src/tests/test_report_context_client.py`
  - [x] QA: consumer helper tests + CLI `--help`

### Batch 20: Runtime Config Baseline Review (2026-03-07)

- [x] **Production-bound runtime config review**
  - [x] analyzed `config/daily_pm_state.json` as deploy-time trading gate state
  - [x] rejected committing date-bound `manual_override approved=true` state into `main`
  - [x] replaced `daily_pm_state.json` with fail-closed deploy baseline (`approved=false`, `source=pending`, `date=null`)
  - [x] analyzed `config/capital.json` change from `0.333...` to `0.5`
  - [x] rejected unreviewed single-position limit loosening for production deployment
  - [x] restored conservative `max_single_position_pct=0.33299999999999996`
  - [x] QA: `daily_pm_review`, `risk_engine`, `settings_api`, `system_api`, `chat_context`

### Batch 21: CI Path Audit + Test Fix (2026-03-07) — `25d9da2`

- [x] **Workstream E: CI Guardrail Hardcoded Path Audit**
  - [x] scanned source for `/Users/` and `~/.openclaw` references across `src/`, `frontend/`, `tools/`, `config/`, `bin/`, `ecosystem.config.js`
  - [x] classified each hit:
    - [x] `tools/trigger_pm_review.py` — **production code bug** → fixed: `Path.home() / ".openclaw" / ".env"` with `OPENCLAW_ROOT_ENV` env override
    - [x] `ecosystem.config.js` — **deployment config** → fixed: `path.join(__dirname, ...)` for all paths
    - [x] `frontend/backend/run.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `bin/run_watcher.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `bin/run_agents.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `bin/run_ops_summary.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `bin/run_reconciliation.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `bin/run_incident_hygiene.sh` — **deployment script** → fixed: `SCRIPT_DIR` based path derivation
    - [x] `src/openclaw/db_router.py` — uses `expanduser("~/.openclaw")` — already portable ✓
    - [x] `frontend/web/README.md` — doc/example only ✓
    - [x] `frontend/backend/.env` — deployment config ✓
  - [x] verified zero `/Users/openclaw` references remain in production code after changes
  - [x] QA: all impacted test suites pass
    - [x] `rg -n '/Users/openclaw' src/ tools/ bin/ frontend/backend/ ecosystem.config.js --glob '!bin/venv/**' --glob '!frontend/backend/.env'` → 0 hits
    - [x] `PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q src/tests/test_broker_reconciliation.py src/tests/test_operator_jobs.py src/tests/test_proposal_executor.py src/tests/test_ticker_watcher.py` → pass
    - [x] `bin/venv/bin/python -m pytest -q frontend/backend/tests/` → all pass (including 4 previously failing)
  - [x] acceptance: no unsafe hardcoded path remains in production code
- [x] **Pre-existing test fix: 4 broken tests in test_coverage_gaps.py**
  - [x] root cause: `MockOrderCandidate.__init__` didn't store attributes; `pre_trade_guard.evaluate_pre_trade_guard()` accesses `candidate.qty` → AttributeError
  - [x] fix: all 4 `MockOrderCandidate` classes now store `symbol`, `side`, `qty`, `price`, `order_type`, `opens_new_position`
  - [x] 4 tests now pass: `TestPortfolioClosePositionBrokerFlow` (3) + `TestPortfolioClosePositionWithCurrentPrice` (1)

### Batch 22: Strategy Committee De-dup And UX Visibility (2026-03-07)

- [x] **Suppress near-duplicate `STRATEGY_DIRECTION` proposals** — `880a9ee`
  - [x] `src/openclaw/agents/strategy_committee.py` compares new strategy direction proposals against the last 12 hours of committee-generated proposals
  - [x] high-similarity proposals are suppressed instead of writing another pending proposal
  - [x] duplicate suppression still writes a dedicated `llm_traces` record so operators can verify analysis actually ran
  - [x] `result.raw["duplicate_alerts"]` is populated for downstream consumers
  - [x] QA:
    - [x] `python3 -m pytest /Users/openclaw/.openclaw/shared/projects/ai-trader/src/tests/test_agents.py -q`
    - [x] `python3 -m pytest /Users/openclaw/.openclaw/shared/projects/ai-trader/src/tests/test_proposal_engine.py -q`
- [x] **Surface duplicate alerts in operator UX** — `6b48c52`
  - [x] `frontend/web/src/pages/Strategy.jsx` shows duplicate suppression feed from strategy logs
  - [x] proposal modal renders `duplicate_alerts` when present in `proposal_json`
  - [x] `src/openclaw/tg_approver.py` includes duplicate warning text in Telegram review messages when payload contains `duplicate_alerts`
  - [x] added regression coverage in `src/tests/test_tg_approver.py`
  - [x] QA:
    - [x] `python3 -m pytest /Users/openclaw/.openclaw/shared/projects/ai-trader/src/tests/test_tg_approver.py -q`
    - [x] `npm --prefix /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web run build`

### QA Snapshot (2026-03-07 17:35)

| Test Suite | Count | Result |
|------------|-------|--------|
| Core Engine | 153+ | ✅ pass |
| Operator | 55+ | ✅ pass |
| Reconciliation | 13+ | ✅ pass |
| FastAPI (all suites) | 67+ | ✅ pass |
| FastAPI test_coverage_gaps | 31 (was 27p/4f) | ✅ pass (4 fixed) |
| Config suites (pm_review/risk/settings/chat) | 127+ | ✅ pass |
| Report context client | 2 | ✅ pass |
| Strategy committee dedup | 32+ | ✅ pass |
| Telegram approver | 17 | ✅ pass |
| Frontend vitest | 124 | ✅ pass |
| Frontend build | — | ✅ pass (chunk warning mitigated) |

0 open incidents in DB. 0 owned-code deprecation warnings.

### Batch 23: Parallel Workstreams A, B, C, D, F (2026-03-07)

- [x] **Workstream A: Runtime Config Governance** — `1a07691`
  - [x] `.gitignore` updated to drop `system_state.json` and `daily_pm_state.json`
  - [x] added fail-closed fallback for missing `system_state.json`
  - [x] kept `capital.json` tracked as a deploy baseline
  - [x] QA: `pytest -q src/tests/test_daily_pm_review.py src/tests/test_risk_engine.py ...` (pass)
- [x] **Workstream B: Reports API Consumer Rollout** — `fa4e837`
  - [x] `eod_analysis.py` decoupled from direct `positions` table query
  - [x] context fetched via `openclaw.report_context_client` to respect real workspace holdings
  - [x] QA: `pytest -q src/tests/agents/test_eod_analysis.py` (pass)
- [x] **Workstream C: Operator UI Chunking And UX** — `2ef0648`
  - [x] migrated page-level imports in `App.jsx` to `React.lazy`
  - [x] configured `vite.config.js` with `manualChunks` to split `vendor-react`, `vendor-router`, `vendor-charts`
  - [x] QA: `npm test` + `npm run build` (success, chunk size reduced)
- [x] **Workstream D: Ops Summary Semantics** — `6c8ff8a`
  - [x] added `environment` mapping: injected `git rev-parse HEAD`, `sys.version`, and `node -v`
  - [x] surfaced active `position_quarantine` count to metrics
  - [x] QA: `bin/run_ops_summary.sh` output check (pass)
- [x] **Workstream F: Documentation Consistency Sweep** — `430fb0f`
  - [x] synced deploy-baseline vs runtime-state policies across `CLAUDE.md`, `AGENTS.md`, and operator runbook
  - [x] documented `/api/reports/context` consumer paths
  - [x] documented portable path convention
  - [x] QA: structural review (pass)

### Batch 24: Simulation Hardening & Frontend Cleanup (2026-03-07)

- [x] **Workstream G: Simulation-Mode Reconciliation Tracking** — `da72c03`
  - [x] modified `operator_jobs.py` to bypass reconciliation in simulation mode by default
  - [x] added `RECON_FORCE_SIMULATION=1` environment override for manual auditing
  - [x] updated operator runbook with bypass interpretation
  - [x] QA: `pytest src/tests/test_operator_jobs.py` (pass)
- [x] **Workstream H: Frontend React Warning Cleanup** — `54dfdf5`
  - [x] addressed `act()` warnings in `Portfolio.test.jsx`, `Inventory.test.jsx`, `Analysis.test.jsx`
  - [x] configured React Router future flags (`v7_startTransition`, `v7_relativeSplatPath`) to clear console churn
  - [x] QA: `npm test` zero warnings baseline (pass)

### Batch 25: Dashboard Optimization & API Hardening (2026-03-07)

- [x] **Workstream I: SSE Throttle & State Consolidation** — `fc279d5`
  - [x] `LogTerminal.jsx`: implemented rAF-based log buffer flush to handle message bursts
  - [x] `QuotePanel`: rAF-throttled bid/ask updates to prevent UI flickering
  - [x] `Portfolio.jsx`: refactored to `useReducer` for atomic state transitions
- [x] **API Resilience & Accuracy** — `7563488`
  - [x] `frontend/backend/run.sh`: load local backend `.env` so `PORTFOLIO_JSON_PATH` reaches the API process
  - [x] `frontend/backend/.env.example`: documented `PORTFOLIO_JSON_PATH`
  - [x] fixed `reports API` real_holdings always returning empty array when portfolio file exists
  - [x] margin data gap for 2026-03-06 was operationally backfilled via `eod_ingest` (data fix, not query refactor)
  - [x] verification recorded in PR #162: `real_holdings` restored and `institution_chips._trade_date` aligned

---

## Pending Checklist

### Workstream I: Dashboard Throughput Optimization
- [ ] **SSE Stream Throttling**
  - [x] audit `LogTerminal` and `QuotePanel` for high-frequency DOM updates
  - [x] implement `requestAnimationFrame` throttling for log and quote rendering
- [ ] **State Update Consolidation**
  - [x] implement `useReducer` in `PortfolioPage` to avoid cascaded re-renders
  - [ ] evaluate `TanStack Query` (React Query) for API polling instead of manual `useEffect`
- [ ] **Stress Testing**
  - [ ] build `tools/stress_test_sse.py` to emit 200+ events/sec
  - [ ] verify browser memory usage remains stable during 10-minute soak test
  - [ ] verify UI lag / interaction responsiveness on low-CPU throttling

### Workstream J: PM Review Persistence & Observability
- [ ] **Database Schema Upgrade**
  - [ ] add `pm_reviews` table: `timestamp`, `date`, `approved`, `reason`, `confidence`, `raw_payload`
  - [ ] add index on `date` for fast historical lookup
- [ ] **Agent Integration**
  - [ ] modify `src/openclaw/agents/daily_pm_review.py` to use `DB.get_conn_rw()`
  - [ ] transition from `daily_pm_state.json` fallback to DB query
- [ ] **Operator Observability**
  - [ ] `GET /api/pm/history`: implement paginated review history endpoint
  - [ ] `System.jsx`: add "Review History" modal or tab with trend visualization (Confidence %)
- [ ] **CLI Hardening**
  - [ ] add `--persist` flag to `tools/trigger_pm_review.py`
  - [ ] add retry logic (exp-backoff) for network-induced review failures

### Workstream K: Sentinel & Health Monitoring V2
- [ ] **Process Liveness Checks**
  - [ ] integrate PM2 status check into `ops-summary` (detect if `watcher` is errored/stopped)
- [ ] **Alert Thresholds**
  - [ ] implement configurable slack/telegram alerts for persistent high CPU/Disk usage


---

## Verified Test Commands

```bash
# Core engine
PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q \
  src/tests/test_pre_trade_guard.py src/tests/test_proposal_executor.py \
  src/tests/test_ticker_watcher.py src/tests/test_main.py \
  src/tests/test_llm_observability.py

# Operator
PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q \
  src/tests/test_position_quarantine.py src/tests/test_operator_remediation.py \
  src/tests/test_incident_resolution.py frontend/backend/tests/test_system_api.py

# Reconciliation
PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q \
  src/tests/test_broker_reconciliation.py src/tests/test_operator_jobs.py

# FastAPI
bin/venv/bin/python -m pytest -q \
  frontend/backend/tests/test_portfolio_api.py \
  frontend/backend/tests/test_reports_api.py \
  frontend/backend/tests/test_main.py

# Frontend
cd frontend/web && npm test -- --run && npm run build
```

## Handoff Notes (Batch 25)

- branch: `main` — sole active line
- 0 open incidents in DB
- **Workstream G completed**: Simulation-mode reconciliation bypassed by default (`da72c03`).
- **Workstream H completed**: Frontend React warnings eliminated (`54dfdf5`).
- **Workstream I partially completed**: rAF throttling and `useReducer` landed (`fc279d5`).
- next task: complete Workstream I verification (`stress_test_sse.py`, soak test, low-CPU validation) or start Workstream J.
- last batch (Batch 25) completed successfully.
- last batch:
  - `fc279d5` — throttle dashboard SSE updates and consolidate portfolio state
  - `7563488` — restore reports API real holdings env wiring
- P2 items are independent — safe for parallel AI sessions
- do not re-open retired codex worktrees
- **Workstream E completed**: all hardcoded `/Users/` paths eliminated from production code
- **4 pre-existing test failures fixed**: `test_coverage_gaps.py` MockOrderCandidate now functional
- **Strategy committee duplicate control is now live**: repeated `STRATEGY_DIRECTION` directions should appear as duplicate suppression traces instead of repeated pending proposals

## Rules For Other AI Sessions

- do not modify runtime files (`config/system_state.json`) unless the task explicitly requires it
- do not revert unrelated user changes in the main worktree
- prefer isolated worktrees for independent streams
- update this file after each batch:
  - move `[ ]` → `[x]` for completed items
  - add commit hash
  - add test results
  - note any remaining risk
