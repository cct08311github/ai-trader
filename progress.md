# AI Trader Hardening Progress

Last updated: 2026-03-07 Asia/Taipei

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
  - [ ] execution journal stale recovery (deferred — requires end-to-end broker mock)

### QA Snapshot (2026-03-07)

| Test Suite | Count | Result |
|------------|-------|--------|
| Core Engine | 76 | pass |
| Operator | 54 | pass |
| FastAPI | 67+ | pass |
| Frontend vitest | 124 | pass |
| Frontend build | — | pass |
| Reports API (new) | 6 | pass |
| Pre-trade guard (new) | 8 | pass |
| Reconciliation + operator_jobs (new) | 12 | pass |

0 open incidents in DB. 0 owned-code deprecation warnings.

---

## Pending Checklist

### P1 Deferred

- [ ] **Execution journal stale recovery test**
  - [ ] build end-to-end broker mock for watcher → intent → execute → journal flow
  - [ ] test stale journal entry recovery across watcher restart
  - [ ] test `mark_intent_failed` prevents infinite retry
  - acceptance: execution journal has both success and failure-path coverage in integration context

### P2 Product and API Follow-up

- [ ] **Reports API documentation and consumer integration**
  - [ ] document `/api/reports/context` in CLAUDE.md § FastAPI 後端 → API 路由
  - [ ] document in AGENTS.md § FastAPI 後端 → API 路由
  - [ ] document auth: requires `Authorization: Bearer <token>` header
  - [ ] document response shape: `{status, report_type, real_holdings, simulated_positions, technical_indicators, institution_chips, recent_trades, eod_analysis, system_state}`
  - [ ] document query params: `type=morning|evening|weekly` (default: morning)
  - [ ] identify actual consumers (OpenClaw finance/researcher agents) and confirm integration
  - acceptance: future AI sessions find the endpoint in docs without reading code

- [ ] **Operator UI polish and chunking**
  - [ ] review `frontend/web` build warning: `index.js` 790KB > 500KB threshold
  - [ ] evaluate code-splitting options:
    - [ ] `React.lazy()` for System page operator panels (quarantine/incidents/remediation)
    - [ ] `React.lazy()` for Analysis page (heavy charts)
    - [ ] dynamic import for recharts
  - [ ] tighten operator panel empty-state behavior (no data → clear message)
  - [ ] verify mobile responsiveness of operator panels
  - acceptance: chunk warning reduced or consciously documented as accepted debt

### P2 Documentation Maintenance

- [ ] **Sync all operator/hardening docs**
  - [ ] CLAUDE.md updates:
    - [ ] add `/api/reports/context` to API 路由 table
    - [ ] add `reports` router to router list
    - [ ] update § 變更歷史 with batch 16 summary
    - [ ] update § 測試規範 with new test patterns (simulation-aware reconciliation)
  - [ ] AGENTS.md updates:
    - [ ] add `reports` router to § FastAPI 後端 → API 路由
    - [ ] add batch 16 to § 變更歷史
  - [ ] operator runbook (`doc/2026-03-06-operator-runbook.md`):
    - [ ] add simulation-aware reconciliation behavior note
    - [ ] add incident cleanup procedures used in batch 16
  - [ ] verify no cross-doc contradictions about active workflow
  - acceptance: all docs agree on endpoints, services, and workflow

### P3 Future Enhancements (not urgent)

- [ ] **Reconciliation improvement: simulation-mode position tracking**
  - [ ] consider separate reconciliation mode for simulation that compares local DB against expected paper positions
  - [ ] alternative: skip reconciliation entirely in simulation and only enable when `simulation_mode=false`
  - acceptance: reconciliation provides value in both simulation and live modes

- [ ] **Frontend React warnings cleanup**
  - [ ] wrap state updates in `act()` for: AnalysisPage, InventoryPage, PortfolioPage, PositionDetailDrawer
  - [ ] upgrade React Router to v7 or add `v7_startTransition` future flag
  - acceptance: zero React warnings in test output

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

## Handoff Notes

- branch: `main` — sole active line
- 0 open incidents in DB
- runtime config stash dropped (all obsolete)
- next task: pick from **Pending Checklist** (P1 deferred or P2)
- P2 items are independent — safe for parallel AI sessions
- do not re-open retired codex worktrees

## Rules For Other AI Sessions

- do not modify runtime files (`config/system_state.json`) unless the task explicitly requires it
- do not revert unrelated user changes in the main worktree
- prefer isolated worktrees for independent streams
- update this file after each batch:
  - move `[ ]` → `[x]` for completed items
  - add commit hash
  - add test results
  - note any remaining risk
