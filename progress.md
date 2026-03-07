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

### QA Refresh After Batch 17

- [x] docs and runbook synced with current mainline behavior
- [x] reports/system/main FastAPI suites rerun green
- [x] reconciliation/operator_jobs suites rerun green
- [x] `bin/run_ops_summary.sh` produced fresh snapshot with `open_incidents=0` and `auto_lock_active=0`
- [x] `bin/run_reconciliation.sh` produced fresh audit snapshot with:
  - [x] `resolved_simulation=true`
  - [x] `mismatch_count=9`
  - [x] no new auto-lock applied
  - [x] no open-incident regression
- [ ] reconcile `reconciliation_mismatches_24h=27` warning metric with simulation-aware semantics in ops summary

### QA Refresh After Batch 18

- [x] `src/tests/test_operator_jobs.py`
- [x] `src/tests/test_broker_reconciliation.py`
- [x] `frontend/backend/tests/test_system_api.py`
- [x] fresh `bin/run_ops_summary.sh` snapshot:
  - [x] `reconciliation_mismatches_24h=0`
  - [x] `overall=ok`
  - [x] `open_incidents=0`

### QA Refresh After Batch 19

- [x] `PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q src/tests/test_ticker_watcher.py src/tests/test_proposal_executor.py src/tests/test_report_context_client.py`
- [x] `PYTHONPATH=src bin/venv/bin/python tools/fetch_report_context.py --help`

### QA Refresh After Batch 20

- [x] `PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q src/tests/test_daily_pm_review.py src/tests/test_risk_engine.py frontend/backend/tests/test_settings_api.py frontend/backend/tests/test_system_api.py frontend/backend/tests/test_chat_context.py`
- [x] verified committed runtime baselines:
  - [x] `config/daily_pm_state.json` is fail-closed
  - [x] `config/capital.json` keeps conservative single-position cap

---

## Pending Checklist

### Workstream A: Runtime Config Governance

- [ ] create isolated worktree `codex/runtime-config-governance`
- [ ] classify tracked config files by role:
  - [ ] deploy baseline
  - [ ] runtime state
  - [ ] operator override
- [ ] decide whether [config/daily_pm_state.json](/Users/openclaw/.openclaw/shared/projects/ai-trader/config/daily_pm_state.json) should remain tracked or move to generated/runtime-only handling
- [ ] decide whether [config/capital.json](/Users/openclaw/.openclaw/shared/projects/ai-trader/config/capital.json) needs explicit approval workflow for production limit changes
- [ ] document “tracked deploy baseline vs runtime operator override” in:
  - [ ] [AGENTS.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/AGENTS.md)
  - [ ] [CLAUDE.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/CLAUDE.md)
  - [ ] [2026-03-06-operator-runbook.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/doc/2026-03-06-operator-runbook.md)
- [ ] if runtime-only is chosen, add safe bootstrap/default handling in code and tests
- [ ] QA:
  - [ ] `PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q src/tests/test_daily_pm_review.py src/tests/test_risk_engine.py frontend/backend/tests/test_settings_api.py frontend/backend/tests/test_system_api.py frontend/backend/tests/test_chat_context.py`
- [ ] acceptance: runtime config changes are intentional, reviewable, and production-safe

### Workstream B: Reports API Consumer Rollout

- [ ] create isolated worktree `codex/reports-consumer-rollout`
- [ ] decide production stance for `PORTFOLIO_JSON_PATH`:
  - [ ] set in production `.env`
  - [ ] or explicitly document empty/missing as acceptable
- [ ] identify external consumers of `/api/reports/context`:
  - [ ] finance/researcher agents
  - [ ] operator scripts
  - [ ] external OpenClaw integrations
- [ ] confirm canonical integration path:
  - [ ] direct HTTP calls
  - [ ] `src/openclaw/report_context_client.py`
  - [ ] `tools/fetch_report_context.py`
- [ ] add at least one real consumer integration or document why helper-only is sufficient
- [ ] sync docs so future AI sessions can find the endpoint without code search
- [ ] QA:
  - [ ] `PYTHONPATH=src bin/venv/bin/python -m pytest -q src/tests/test_report_context_client.py`
  - [ ] `bin/venv/bin/python -m pytest -q frontend/backend/tests/test_reports_api.py frontend/backend/tests/test_main.py`
  - [ ] `PYTHONPATH=src bin/venv/bin/python tools/fetch_report_context.py --help`
- [ ] acceptance: reports context has a documented production consumer path

### Workstream C: Operator UI Chunking And UX

- [ ] create isolated worktree `codex/operator-ui-chunking`
- [ ] reproduce and measure current build warning in [frontend/web](/Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web)
- [ ] reduce large bundle risk:
  - [ ] evaluate `React.lazy()` for System operator panels
  - [ ] evaluate `React.lazy()` for Analysis page heavy views
  - [ ] evaluate dynamic import for `recharts`
- [ ] tighten operator panel empty states so “no data” is explicit and actionable
- [ ] verify mobile responsiveness for System operator panels
- [ ] update tests for new lazy-loading/empty-state behavior
- [ ] QA:
  - [ ] `cd frontend/web && npm test -- --run src/pages/System.test.jsx`
  - [ ] `cd frontend/web && npm run build`
- [ ] acceptance: chunk warning is reduced or explicitly documented as accepted debt

### Workstream D: Ops Summary Semantics

- [ ] create isolated worktree `codex/ops-summary-semantics`
- [ ] decide whether resolved reconciliation incidents need a separate historical metric
- [ ] if yes, add a non-alerting metric instead of overloading `reconciliation_mismatches_24h`
- [ ] update ops summary API/tests/docs to reflect final semantics
- [ ] QA:
  - [ ] `PYTHONPATH=src:frontend/backend bin/venv/bin/python -m pytest -q src/tests/test_operator_jobs.py src/tests/test_broker_reconciliation.py frontend/backend/tests/test_system_api.py`
  - [ ] `bin/run_ops_summary.sh`
- [ ] acceptance: alerting metrics and historical audit metrics are clearly separated

### Workstream E: CI Guardrail Hardcoded Path Audit

- [ ] create isolated worktree `codex/ci-path-audit`
- [ ] scan source for remaining `~/.openclaw` or `/Users/` references
- [ ] classify each hit:
  - [ ] legitimate doc/example only
  - [ ] test fixture only
  - [ ] production code bug
- [ ] migrate production-code hits to env vars or safe defaults
- [ ] add/adjust regression coverage for any migrated path behavior
- [ ] QA:
  - [ ] `rg -n \"~/.openclaw|/Users/\" src frontend tools config`
  - [ ] run impacted pytest/vitest suites
- [ ] acceptance: no unsafe hardcoded path remains in production code

### Workstream F: Documentation Consistency Sweep

- [ ] create isolated worktree `codex/doc-consistency-sweep`
- [ ] sync operator/hardening docs:
  - [ ] [CLAUDE.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/CLAUDE.md)
  - [ ] [AGENTS.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/AGENTS.md)
  - [ ] [2026-03-06-operator-runbook.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/doc/2026-03-06-operator-runbook.md)
  - [ ] [README.md](/Users/openclaw/.openclaw/shared/projects/ai-trader/README.md)
- [ ] verify docs reflect:
  - [ ] sole active line is `main`
  - [ ] runtime config baseline policy
  - [ ] reports context consumer path
  - [ ] current operator PM2/cron flow
- [ ] QA:
  - [ ] cross-read docs for contradictions
- [ ] acceptance: docs agree on active workflow, endpoints, and operational rules

### Parked / Future Work

- [ ] **Reconciliation improvement: simulation-mode position tracking**
  - [ ] consider separate reconciliation mode for simulation that compares local DB against expected paper positions
  - [ ] alternative: skip reconciliation entirely in simulation and only enable when `simulation_mode=false`
  - [ ] acceptance: reconciliation provides value in both simulation and live modes

- [ ] **Frontend React warnings cleanup**
  - [ ] wrap state updates in `act()` for: AnalysisPage, InventoryPage, PortfolioPage, PositionDetailDrawer
  - [ ] upgrade React Router to v7 or add `v7_startTransition` future flag
  - [ ] acceptance: zero React warnings in test output

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
- last parallel batches:
  - `Batch 20` runtime baseline review completed on `main`
  - `59cc09b` watcher execution journal regression coverage
  - `1eacca0` report context consumer helper + CLI
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
