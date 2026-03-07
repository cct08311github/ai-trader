# AI Trader Hardening Progress

Last updated: 2026-03-07 Asia/Taipei

## Coordination

- Primary coordination file for parallel AI work.
- Update this file after every meaningful batch.
- Keep entries factual: branch, worktree, scope, tests, commit, next step.

## Worktrees

- `main`
  - path: `/Users/openclaw/.openclaw/shared/projects/ai-trader`
  - focus: sole active mainline after integrating operator remediation, operator drilldown, and System UI work
  - status: active
- `codex/integration-recovery`
  - path: `/Users/openclaw/.openclaw/shared/projects/ai-trader-work-integration-recovery`
  - focus: single mainline for remediation, operator API, and System UI after integration recovery
  - status: retired after fast-forward into `main`
- `codex/remediation-api`
  - path: `/Users/openclaw/.openclaw/shared/projects/ai-trader-work-remediation-api`
  - focus: operator remediation, incident handling, quarantine workflow, CLI/API hardening
  - status: retired after integration into `codex/integration-recovery`
- `codex/system-ops-ui`
  - path: `/Users/openclaw/.openclaw/shared/projects/ai-trader-work-system-ops-ui`
  - focus: System page operator UI for quarantine/incidents/remediation history
  - status: retired after integration into `codex/integration-recovery`
- `codex/operator-drilldown`
  - path: `/Users/openclaw/.openclaw/shared/projects/ai-trader-work-operator-drilldown`
  - focus: backend filtering/query ergonomics for operator APIs
  - status: retired after integration into `codex/integration-recovery`

## Completed Batches

1. `a253377` `feat: harden operator incident workflows`
   - added reconciliation diagnostics and incident hygiene improvements
2. `c7822a3` `feat: auto-lock trading on reconciliation drift`
   - reconciliation can auto-disable `trading_enabled`
3. `8e98f32` `feat: add reconciliation quarantine workflow`
   - added quarantine planning/apply framework
4. `cba9fc5` `feat: add reversible quarantine controls`
   - clear/rebuild quarantine flow
5. `cad1a10` `feat: add quarantine remediation api`
   - added `/api/system/quarantine-plan`
   - added `/api/system/quarantine/apply`
   - added `/api/system/quarantine/clear`
6. `1337b7e` `feat: add remediation audit trail`
   - added remediation journal
   - added `/api/system/remediation-history`
7. `1741e2f` `feat: add incident resolution api`
   - added `/api/system/incidents/open`
   - added `/api/system/incidents/resolve`
8. `25ae475` `feat: add incident resolution cli`
   - added `tools/run_incident_resolution.py`
   - added `bin/run_incident_resolution.sh`
9. `1a31836` `docs: add shared progress ledger`
   - shared coordination ledger for split worktrees
10. `2026-03-07 integration verification`
   - all remediation, operator-drilldown, and system-ops-ui commits cherry-picked into `codex/integration-recovery`
   - backend operator tests passed on the integrated branch
   - `System.test.jsx` passed on the integrated branch
   - `frontend/web` production build passed on the integrated branch
11. `2026-03-07 mainline consolidation`
   - retired split worktrees after successful integration
   - `codex/integration-recovery` is now the only active operator hardening line
12. `2026-03-07 main promotion`
   - `main` fast-forwarded from `cba9fc5` to `f4ef55b`
   - previous dirty `main` changes were preserved in `stash@{0}` with message `main-wip-before-integration-2026-03-07`
   - integrated backend tests, `System.test.jsx`, and production build all passed on `main`
13. `2026-03-07 stash recovery batch 1`
   - restored `pre_trade_guard` and `llm_governance` from the saved `main` stash
   - wired pre-trade hard guard into `main.py`, `ticker_watcher.py`, and manual close in `portfolio.py`
   - restored proposal execution journal hardening and related tests
   - restored LLM governance metadata persistence and related tests
14. `2026-03-07 stash recovery batch 2`
   - restored `/api/reports/context` into the FastAPI mainline
   - added backend route tests for structured report context and optional-source fallback
   - fixed report technical-indicator generation for short price histories
15. `2026-03-07 stash recovery batch 3`
   - restored `AGENTS.md` for future Codex sessions
   - restored the automated trading hardening plan under `doc/plans/`
   - left runtime JSON state snapshots in stash instead of committing environment drift

## Verified Test Commands

```bash
PYTHONPATH=src:frontend/backend /Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python -m pytest -q src/tests/test_position_quarantine.py src/tests/test_operator_remediation.py src/tests/test_incident_resolution.py frontend/backend/tests/test_system_api.py
npm test -- --run src/pages/System.test.jsx
npm run build
PYTHONPATH=src /Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python -m pytest -q src/tests/test_pre_trade_guard.py src/tests/test_proposal_executor.py src/tests/test_ticker_watcher.py src/tests/test_main.py src/tests/test_llm_observability.py
/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python -m pytest -q frontend/backend/tests/test_portfolio_api.py
/Users/openclaw/.openclaw/shared/projects/ai-trader/bin/venv/bin/python -m pytest -q frontend/backend/tests/test_reports_api.py frontend/backend/tests/test_main.py
```

Additional smoke checks completed:

- FastAPI `quarantine_apply -> remediation-history -> quarantine_clear`
- FastAPI `incidents/open -> incidents/resolve -> remediation-history`
- CLI `bin/run_incident_resolution.sh` list + apply
- frontend `npm run build`
- frontend `npm test -- --run src/pages/System.test.jsx`

## Current Production/Operational Context

- real reconciliation mismatch cluster remains the highest priority operational issue
- auto-lock behavior is already implemented for `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
- incident storm has already been reduced from hundreds of raw rows to a small actionable set
- repository mainline is now `main`; split codex integration branches/worktrees have been retired
- only remaining saved-but-not-committed material from the old `main` WIP is `stash@{0}` with runtime config snapshots:
  - `config/daily_pm_state.json`
  - `config/system_state.json`
  - `config/watchlist.json`

## QA Results

### 2026-03-07 Full QA Pass

All completed batches (1–15) verified on `main`:

| Test Suite | Count | Result |
|------------|-------|--------|
| Core Engine (pre_trade_guard, proposal_executor, ticker_watcher, main, llm_observability) | 76 | ✅ pass |
| Operator (quarantine, remediation, incident, system_api) | 54 | ✅ pass |
| FastAPI (reports_api, main, portfolio_api) | 67 | ✅ pass |
| Frontend vitest (10 files) | 124 | ✅ pass |
| Frontend production build | — | ✅ built |

No failures. Only cosmetic warnings (React `act()` wrapping, deprecated `utcnow()`).

## In Progress

### Mainline

- branch/worktree: `main`
- current state:
  - all 15 completed batches QA-verified green
  - remediation API/CLI, operator-drilldown, System operator UI fully integrated
  - stash recovery batches 1–3 integrated; only runtime config snapshots remain in `stash@{0}`
  - split implementation worktrees are retired
- target:
  - use `main` as the sole active line going forward

## Backlog

### P0 Production Incidents

1. Reconciliation mismatch root cause and remediation
   - goal: explain and clear the remaining broker/local position drift instead of only auto-locking trading
   - tasks:
     - inspect latest reconciliation snapshot under `data/ops/reconciliation/latest.json`
     - confirm whether mismatches are caused by wrong account, wrong simulation/live mode, or local phantom positions
     - use quarantine/remediation flow only after source-of-truth is confirmed
     - verify `config/system_state.json` auto-lock fields match the active incident reason
   - acceptance:
     - mismatch cluster is either resolved or reduced to a clearly documented residual set
     - operator runbook contains the exact resolution steps used
   - suggested verification:
     - `bin/run_reconciliation.sh`
     - `curl -sk https://127.0.0.1:8080/api/system/reconciliation/latest ...`
     - `curl -sk https://127.0.0.1:8080/api/system/quarantine-status ...`

2. Network allowlist incident root cause
   - goal: stop repeated `SEC_NETWORK_IP_DENIED` incidents at the infrastructure/config level
   - tasks:
     - compare runtime egress IPs against configured allowlist
     - confirm whether the blocked IPs are expected operator/broker/network paths
     - update allowlist source of truth or deployment path as needed
     - resolve remaining clustered incidents after the root cause is fixed
   - acceptance:
     - new allowlist incidents stop appearing during normal operation
     - historical clusters are resolved with remediation history

### P1 Operational Hardening

3. PM2 and operator runbook validation in live environment
   - goal: ensure docs and jobs still match reality after mainline consolidation
   - tasks:
     - verify PM2 process list matches runbook and README
     - smoke-test `ai-trader-ops-summary`, `ai-trader-reconciliation`, `ai-trader-incident-hygiene`
     - confirm generated artifacts land in `data/ops/...` as documented
   - acceptance:
     - runbook commands work as written on current machine
     - no stale service names or retired worktree references remain

4. Runtime config snapshot review
   - goal: decide whether `stash@{0}` config snapshots are obsolete, operationally needed, or should be documented elsewhere
   - tasks:
     - inspect `stash@{0}` for:
       - `config/daily_pm_state.json`
       - `config/system_state.json`
       - `config/watchlist.json`
     - compare with current runtime state
     - either discard the stash or capture any intentional operational deltas in docs/runbook
   - acceptance:
     - no ambiguous “important but hidden” runtime config remains stranded in stash

### P1 QA and Reliability

5. Eliminate high-noise deprecation warnings in owned code
   - goal: remove project-originated `datetime.utcnow()` deprecation warnings so test output surfaces real regressions
   - tasks:
     - replace owned `utcnow()` / `utcfromtimestamp()` usage with timezone-aware UTC equivalents
     - prioritize:
       - `frontend/backend/app/api/portfolio.py`
       - `src/openclaw/pnl_engine.py`
       - any other owned modules reported by pytest
     - leave third-party warnings documented but untouched unless vendor upgrade is planned
   - acceptance:
     - owned-code deprecation warnings are substantially reduced or eliminated in targeted test suites

6. Expand regression coverage for recovered features
   - goal: make recovered stash work harder to regress accidentally
   - tasks:
     - add negative-path tests for `/api/reports/context`
     - add tests for report context when chips/analysis tables are absent
     - add integration coverage for execution journal stale recovery across watcher flow
     - add tests for pre-trade guard env override behavior
   - acceptance:
     - newly recovered modules have both success and failure-path coverage

### P2 Product and API Follow-up

7. Reports API documentation and consumer integration
   - goal: make `/api/reports/context` discoverable and safe for downstream agents/tools
   - tasks:
     - document the endpoint in README/AGENTS or dedicated API docs
     - confirm auth expectations and expected response shape
     - identify actual consumers and add a thin smoke test if any job/script depends on it
   - acceptance:
     - future AI sessions do not need to rediscover the endpoint by reading code

8. Operator UI polish and chunking follow-up
   - goal: reduce UI technical debt now that operator panels are merged
   - tasks:
     - review `frontend/web` build warning about large chunks
     - consider splitting operator-heavy `System.jsx` areas if bundle growth continues
     - tighten payload formatting and empty-state behavior where useful
   - acceptance:
     - either chunk warning is reduced or consciously documented as accepted debt

### P2 Documentation Maintenance

9. Sync all operator/hardening docs
   - goal: keep docs aligned after multiple recovery batches
   - tasks:
     - ensure `README.md`, `AGENTS.md`, `doc/2026-03-06-operator-runbook.md`, and `progress.md` agree on:
       - sole active branch/workflow
       - operator endpoints and scripts
       - reconciliation/quarantine/remediation flow
     - remove any stale references to retired codex branches/worktrees
   - acceptance:
     - no cross-doc contradictions about the active workflow

## Suggested Execution Order

1. P0 reconciliation mismatch root cause
2. P0 network allowlist root cause
3. runtime config snapshot review
4. PM2/runbook validation
5. owned-code deprecation cleanup
6. regression coverage expansion
7. reports API documentation
8. operator UI polish
9. cross-doc sync pass

## Handoff Notes

- next AI session should start from `main`
- next AI session should start with `Backlog -> P0 Production Incidents -> Reconciliation mismatch root cause and remediation`
- do not re-open or recreate retired codex worktrees unless a new isolated stream is actually needed
- if runtime config snapshots are needed, inspect `stash@{0}` first instead of assuming repo drift
- most recent recovery commits on `main`:
  - `82d04ed` `docs: restore project operating docs`
  - `39e6cc8` `feat: restore report context api`
  - `0af4a2f` `feat: recover pre-trade guard and llm governance`

## Rules For Other AI Sessions

- do not modify runtime files such as `config/system_state.json` unless the task explicitly requires it
- do not revert unrelated user changes in the main worktree
- prefer isolated worktrees for independent streams
- update this file after each batch with:
  - worktree
  - commit
  - tests run
  - remaining risk
