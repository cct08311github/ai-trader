# AI Trader Operator Runbook

## Scope

This runbook covers the new operational hardening jobs:

- periodic ops summary capture
- daily broker reconciliation
- daily incident hygiene
- PM2 wiring and expected operator actions

All paths below assume the repository root:

`/Users/openclaw/.openclaw/shared/projects/ai-trader` *(Legacy: production deployment uses Portable Paths computed via SCRIPT_DIR/OPENCLAW_ROOT_ENV).*

## Configuration Governance

Configuration files in `config/` are strictly divided into two categories:

1. **Deploy Baselines** (Tracked in Git)
   - Examples: `capital.json`, `drawdown_policy_v1.json`, `locked_symbols.json`.
   - Policy: These dictate production limits (e.g., maximum position size). Any change to these limits requires a PR/Git commit and team review. Do not override these via runtime memory.
2. **Runtime State** (Untracked, `.gitignore`)
   - Examples: `system_state.json`, `daily_pm_state.json`.
   - Policy: These are dynamically generated and updated by the system or operator API actions. They are excluded from version control to prevent Git workspace pollution. Safe defaults are provided in code during bootstrapping.

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

Current verified state after batch 16 on `2026-03-07`:

- unresolved incidents are `0`
- simulation-mode reconciliation no longer raises false-positive auto-lock/incidents when broker positions are structurally empty
- reconciliation reports still write diagnostics for audit, including `resolved_simulation=true`

### Reconciliation

Primary checks:

```bash
cat data/ops/reconciliation/latest.json
curl -sk https://127.0.0.1:8080/api/system/reconciliation/latest \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
curl -sk https://127.0.0.1:8080/api/system/quarantine-status \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
curl -sk "https://127.0.0.1:8080/api/system/remediation-history?limit=10" \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
curl -sk https://127.0.0.1:8080/api/system/incidents/open \
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

5. Build a quarantine plan before changing local positions:

```bash
python3 tools/run_reconciliation_quarantine.py \
  --db-path data/sqlite/trades.db \
  --snapshot-path data/ops/reconciliation/latest.json
```

6. Only after broker truth is confirmed, apply the quarantine plan:

```bash
python3 tools/run_reconciliation_quarantine.py \
  --db-path data/sqlite/trades.db \
  --snapshot-path data/ops/reconciliation/latest.json \
  --apply
```

7. Verify the remediation journal captured the action:

```bash
curl -sk "https://127.0.0.1:8080/api/system/remediation-history?limit=10" \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
```

Simulation-mode note:

- By default, reconciliation is **bypassed** in simulation mode to avoid false-positive drift alerts from ephemeral paper trading environments.
- if `data/ops/reconciliation/latest.json` shows:
  - `report_id = "bypassed-simulation"`
  - `resolved_simulation = true`
- This indicates the run was skipped. auto-lock and critical incidents are NOT triggered.
- **To enable paper reconciliation**: set `RECON_FORCE_SIMULATION=1` in the environment or `.env`. This is useful if you want to audit paper position drift against a dedicated simulation account.
- If enabled and `data/ops/reconciliation/latest.json` shows:
  - `diagnosis_codes` includes `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
  - then treat it as an audit-only simulation mismatch, still not a live broker drift incident.
- switch to live-mode verification only after confirming `simulation_mode=false`.

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
curl -sk https://127.0.0.1:8080/api/system/incidents/open \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"
```

5. If incidents are dominated by repeated identical payloads, run hygiene:

```bash
bin/run_incident_hygiene.sh
cat data/ops/incident_hygiene/latest.json
```

6. After the root cause is fixed, resolve the specific cluster instead of bulk-closing unrelated incidents:

```bash
curl -sk -X POST https://127.0.0.1:8080/api/system/incidents/resolve \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')" \
  -H "Content-Type: application/json" \
  -d '{"source":"network_security","code":"SEC_NETWORK_IP_DENIED","fingerprint":"<cluster fingerprint>","reason":"allowlist updated"}'
```

CLI alternative:

```bash
bin/run_incident_resolution.sh
bin/run_incident_resolution.sh \
  --apply \
  --source network_security \
  --code SEC_NETWORK_IP_DENIED \
  --fingerprint "<cluster fingerprint>" \
  --reason "allowlist updated"
```

Verified cleanup used in batch 16:

- false-positive reconciliation cluster resolved after simulation-aware suppression was added
- two historical `SEC_NETWORK_IP_DENIED` clusters were resolved after confirming they were test artifacts (`8.8.8.8`, `203.0.113.10`) and not active production egress paths

Script-friendly variants:

```bash
bin/run_incident_resolution.sh --summary-only
bin/run_incident_resolution.sh --jsonl
bin/run_incident_resolution.sh \
  --source network_security \
  --code SEC_NETWORK_IP_DENIED \
  --severity critical \
  --action-type incident_resolve \
  --target-ref network_security \
  --summary-only
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

### Build or apply reconciliation quarantine

Dry-run:

```bash
python3 tools/run_reconciliation_quarantine.py \
  --db-path data/sqlite/trades.db \
  --snapshot-path data/ops/reconciliation/latest.json
```

Apply:

```bash
python3 tools/run_reconciliation_quarantine.py \
  --db-path data/sqlite/trades.db \
  --snapshot-path data/ops/reconciliation/latest.json \
  --apply
```

Clear and rebuild from fills:

```bash
python3 tools/run_reconciliation_quarantine.py \
  --db-path data/sqlite/trades.db \
  --clear
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
