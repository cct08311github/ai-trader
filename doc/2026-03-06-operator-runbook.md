# AI Trader Operator Runbook

## Scope

This runbook covers the new operational hardening jobs:

- periodic ops summary capture
- daily broker reconciliation
- daily incident hygiene
- PM2 wiring and expected operator actions

All paths below assume the repository root:

`/Users/openclaw/.openclaw/shared/projects/ai-trader`

## Services

### Long-running services

- `ai-trader-api`
- `ai-trader-web`
- `ai-trader-watcher`
- `ai-trader-agents`

### Scheduled one-shot services

- `ai-trader-ops-summary`
  - PM2 cron: every 15 minutes
  - command: `bin/run_ops_summary.sh`
  - output: `data/ops/ops_summary/latest.json`

- `ai-trader-reconciliation`
  - PM2 cron: every weekday at 16:45 Asia/Taipei host time
  - command: `bin/run_reconciliation.sh`
  - output: `data/ops/reconciliation/latest.json`
  - exit code:
    - `0`: no mismatch
    - `1`: mismatch found or broker snapshot failure

- `ai-trader-incident-hygiene`
  - PM2 cron: every weekday at 16:55 Asia/Taipei host time
  - command: `bin/run_incident_hygiene.sh`
  - output: `data/ops/incident_hygiene/latest.json`

## First-time Setup

1. Reload PM2 config:

```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
pm2 start ecosystem.config.js --only ai-trader-ops-summary,ai-trader-reconciliation
pm2 start ecosystem.config.js --only ai-trader-incident-hygiene
```

2. Verify PM2 registration:

```bash
pm2 status
```

Expected:

- both jobs appear in PM2
- state may be `stopped` between cron runs because they are one-shot jobs

3. Dry-run each job manually:

```bash
bin/run_ops_summary.sh
bin/run_reconciliation.sh
bin/run_incident_hygiene.sh
```

4. Confirm snapshot files exist:

```bash
ls -la data/ops/ops_summary
ls -la data/ops/reconciliation
ls -la data/ops/incident_hygiene
```

## Normal Operations

### Ops summary

Primary checks:

```bash
cat data/ops/ops_summary/latest.json
curl -sk https://127.0.0.1:8080/api/system/ops-summary \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
```

Watch for:

- `overall = critical`
- `failed_executions > 0`
- `open_incidents > 0`
- `reconciliation_mismatches_24h > 0`
- `auto_lock.active = true`
- abnormal `pre_trade_rejects_24h`

Current verified state after hygiene rollout on `2026-03-06`:

- unresolved incidents were reduced from `431` to `3`
- remaining open set:
  - `1` reconciliation mismatch cluster
  - `2` distinct network allowlist denial payload variants

### Reconciliation

Primary checks:

```bash
cat data/ops/reconciliation/latest.json
curl -sk https://127.0.0.1:8080/api/system/reconciliation/latest \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
```

Interpretation:

- `mismatch_count = 0`: local DB and broker snapshot agree
- `missing_local_position`: broker has inventory not reflected locally
- `missing_broker_position`: local DB shows inventory broker does not have
- `quantity_mismatch`: same symbol exists in both places but quantities differ
- `missing_broker_order`: local order is open but broker snapshot does not contain it
- `auto_lock_applied = true`: reconciliation has disabled `trading_enabled` in `config/system_state.json`

## Incident Response

### Reconciliation mismatch

1. Read latest report:

```bash
cat data/ops/reconciliation/latest.json
```

2. Inspect incidents:

```bash
sqlite3 data/sqlite/trades.db \
  "SELECT ts,severity,source,code,detail_json FROM incidents WHERE source='broker_reconciliation' ORDER BY ts DESC LIMIT 10;"
```

3. Compare positions directly:

```bash
sqlite3 data/sqlite/trades.db \
  "SELECT symbol,quantity,avg_price,current_price,state FROM positions WHERE quantity>0 ORDER BY symbol;"
```

4. If mismatch is real:

- auto-trading is now disabled automatically when reconciliation reports `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
- verify Shioaji account position manually
- repair DB only after broker truth is confirmed
- rerun reconciliation after repair
- only re-enable auto-trading after broker truth and local positions are reconciled:

```bash
curl -sk -X POST https://127.0.0.1:8080/api/control/enable \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
```

### Ops summary critical

1. Read `latest.json`.
   If `auto_lock.active = true`, treat reconciliation as the primary incident until proven otherwise.
2. Check PM2 logs:

```bash
pm2 logs ai-trader-api --lines 100
pm2 logs ai-trader-watcher --lines 100
pm2 logs ai-trader-ops-summary --lines 100
pm2 logs ai-trader-reconciliation --lines 100
```

3. If `failed_executions > 0`, inspect:

```bash
sqlite3 data/sqlite/trades.db \
  "SELECT proposal_id,status,supporting_evidence,decided_at FROM strategy_proposals WHERE status='failed' ORDER BY decided_at DESC LIMIT 20;"
sqlite3 data/sqlite/trades.db \
  "SELECT execution_key,proposal_id,state,attempt_count,last_error,last_order_id,updated_at FROM proposal_execution_journal ORDER BY updated_at DESC LIMIT 20;"
```

4. If `open_incidents > 0`, inspect:

```bash
sqlite3 data/sqlite/trades.db \
  "SELECT ts,severity,source,code,detail_json FROM incidents WHERE resolved=0 ORDER BY ts DESC;"
```

5. If incidents are dominated by repeated identical payloads, run hygiene:

```bash
bin/run_incident_hygiene.sh
cat data/ops/incident_hygiene/latest.json
```

## Manual Commands

### Force a fresh ops snapshot

```bash
bin/run_ops_summary.sh
```

### Force a reconciliation run

Production broker snapshot:

```bash
RECON_BROKER_SOURCE=shioaji bin/run_reconciliation.sh
```

Mock broker snapshot:

```bash
RECON_BROKER_SOURCE=mock bin/run_reconciliation.sh
```

Explicit simulation override:

```bash
RECON_SIMULATION=true bin/run_reconciliation.sh
RECON_SIMULATION=false bin/run_reconciliation.sh
```

### Force incident de-duplication

```bash
bin/run_incident_hygiene.sh
```

## PM2 Operations

### Reload scheduled jobs after config changes

```bash
pm2 reload ecosystem.config.js --only ai-trader-ops-summary,ai-trader-reconciliation,ai-trader-incident-hygiene
```

### Trigger immediate run via PM2

```bash
pm2 restart ai-trader-ops-summary
pm2 restart ai-trader-reconciliation
pm2 restart ai-trader-incident-hygiene
```

### Inspect job logs

```bash
pm2 logs ai-trader-ops-summary --lines 100
pm2 logs ai-trader-reconciliation --lines 100
pm2 logs ai-trader-incident-hygiene --lines 100
```

## Snapshot Locations

- ops summary latest:
  - `data/ops/ops_summary/latest.json`
- ops summary history:
  - `data/ops/ops_summary/YYYYMMDDTHHMMSSZ.json`
- reconciliation latest:
  - `data/ops/reconciliation/latest.json`
- reconciliation history:
  - `data/ops/reconciliation/YYYYMMDDTHHMMSSZ.json`
- incident hygiene latest:
  - `data/ops/incident_hygiene/latest.json`
- incident hygiene history:
  - `data/ops/incident_hygiene/YYYYMMDDTHHMMSSZ.json`

## Notes

- PM2 one-shot cron apps are expected to sit idle between runs.
- Reconciliation currently uses broker positions via Shioaji service and local open orders from SQLite.
- If the broker API is unavailable, reconciliation exits non-zero and the failure is visible in PM2 logs.
