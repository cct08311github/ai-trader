# 2026-03-06 Incident Triage Report

## Scope

Triage based on current production SQLite state and latest reconciliation snapshot.

Data sources:

- `incidents WHERE resolved = 0`
- `data/ops/reconciliation/latest.json`
- `positions`
- `strategy_proposals`

## Executive Summary

Open incidents total before cleanup: `430`

Open incidents after incident hygiene on `2026-03-06`: `3`

Deduplicated incident clusters: `2`

1. `network_security / SEC_NETWORK_IP_DENIED`
   - raw incidents: `429`
   - deduped variants: `2`
   - priority: `P1`
   - reason: critical severity and blocks broker-facing execution paths

2. `broker_reconciliation / RECONCILIATION_MISMATCH`
   - raw incidents: `1`
   - affected symbols: `9`
   - priority: `P0`
   - reason: broker/local position drift is a source-of-truth integrity issue

## Deduplicated Clusters

### Cluster A: Broker/Network Allowlist Denials

Signature:

- `source = network_security`
- `code = SEC_NETWORK_IP_DENIED`
- `severity = critical`

Raw count: `429`

Time range:

- first seen: `2026-03-02T06:37:00.543595+00:00`
- last seen: `2026-03-06T12:40:46.895545+00:00`

Distinct payload groups:

1. `current_ip = 8.8.8.8`, `allowlist = ['192.168.1.0/24']`
   - count: `262`
2. `current_ip = 203.0.113.10`, `allowlist = ['203.0.113.0/28']`
   - count: `167`

Assessment:

- This is almost certainly one logical incident class, not 429 independent incidents.
- It looks like execution code repeatedly attempted a broker-sensitive path while the configured IP allowlist did not match the runtime egress IP.
- Because the same violation repeated for multiple days, this is a persistent configuration defect or stale test config, not a transient outage.

Operational impact:

- likely blocks actual broker submission or sensitive broker API actions
- creates alert noise and hides newer incidents

Priority:

- `P1`

Why not P0:

- current evidence points to blocked execution attempts, but not silent wrong fills or position corruption
- the broker/local reconciliation issue is higher because it concerns source-of-truth divergence

Recommended action:

1. Verify intended production egress IP.
2. Compare it against configured allowlist source used by `network_allowlist`.
3. Replace placeholder/test allowlists if they are still active.
4. Historical duplicates were bulk-resolved by `bin/run_incident_hygiene.sh`; keep using that instead of manual row-by-row cleanup.

### Cluster B: Broker Reconciliation Mismatch

Signature:

- `source = broker_reconciliation`
- `code = RECONCILIATION_MISMATCH`
- `severity = warning`

Raw count: `1`

Latest report:

- `report_id = ebf760a4-b9bf-4bc3-86ae-cbc94d6cfc79`
- `mismatch_count = 9`

Mismatch type breakdown:

- `missing_broker_position = 9`
- `missing_local_position = 0`
- `quantity_mismatch = 0`
- `missing_broker_order = 0`

Affected symbols:

- `1303`
- `2002`
- `2317`
- `2330`
- `2382`
- `2881`
- `2882`
- `2886`
- `3008`

Local position snapshot:

- `1303`: qty `130`, current_price `0.0`
- `2002`: qty `467`, current_price `0.0`
- `2317`: qty `436`, current_price `223.0`
- `2330`: qty `148`, current_price `0.0`
- `2382`: qty `235`, current_price `289.0`
- `2881`: qty `641`, current_price `88.8`
- `2882`: qty `356`, current_price `0.0`
- `2886`: qty `555`, current_price `39.3`
- `3008`: qty `591`, current_price `2380.0`

Assessment:

- This is not duplicate noise.
- All mismatches are one directional: local DB says positions exist, broker snapshot says they do not.
- No open submitted/partially_filled orders were found in local DB at triage time, so this does not look like simple in-flight settlement noise.
- This pattern is consistent with one of these states:
  - local DB inventory is stale or orphaned
  - reconciliation hit a different broker account/mode than the local positions were built from
  - simulation/live mode mismatch during reconciliation

Operational impact:

- portfolio state may be overstated locally
- PM review and concentration logic may use wrong holdings
- risk and proposal decisions may be computed on phantom inventory

Priority:

- `P0`

Recommended action:

1. Confirm whether reconciliation used the intended account and mode.
   - current snapshot used `broker_source = shioaji`
   - `simulation = null` means service default was used
2. Verify `config/system_state.json` current `simulation_mode`.
3. Manually compare broker holdings in Shioaji UI/account against the 9 symbols.
4. If broker really has zero holdings, freeze auto-trading until local `positions` is repaired or regenerated.
5. Rerun reconciliation after repair.

Update after control hardening:

- `bin/run_reconciliation.sh` now auto-disables `trading_enabled` when diagnostics contain `MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
- current `config/system_state.json` is therefore expected to show:
  - `trading_enabled = false`
  - `auto_lock_active = true`
  - `auto_lock_reason_code = MODE_OR_ACCOUNT_MISMATCH_SUSPECTED`
- a dry-run remediation command is available:
  - `python3 tools/run_reconciliation_quarantine.py --db-path data/sqlite/trades.db --snapshot-path data/ops/reconciliation/latest.json`
  - current dry-run output marks all `9` affected symbols as eligible for quarantine because local open orders are `0`

## Priority Queue

### P0

1. Reconciliation mismatch cluster (`9` symbols)
   - reason: source-of-truth divergence between broker and local DB
   - owner: trading system operator
   - next command set:

```bash
sqlite3 data/sqlite/trades.db "SELECT symbol,quantity,avg_price,current_price,state FROM positions WHERE quantity>0 ORDER BY symbol;"
cat data/ops/reconciliation/latest.json
```

### P1

1. Network allowlist denial cluster (`429` raw incidents, `2` deduped payloads)
   - reason: repeated blocking of broker-sensitive paths
   - owner: platform/operator
   - next command set:

```bash
sqlite3 data/sqlite/trades.db "SELECT MIN(ts), MAX(ts), COUNT(*) FROM incidents WHERE resolved=0 AND source='network_security' AND code='SEC_NETWORK_IP_DENIED';"
pm2 logs ai-trader-watcher --lines 100
pm2 logs ai-trader-api --lines 100
```

## De-duplication Result

Raw unresolved incidents before cleanup: `430`

Deduped actionable incidents: `3`

- `1` reconciliation mismatch incident
- `2` network allowlist payload variants

If deduped at the logical-cause level rather than payload level, the count is `2`.

## Proposed Next Actions

1. Investigate whether reconciliation ran against the wrong account or wrong simulation/live mode.
2. If the 9 broker mismatches are confirmed real, stop automatic trading until local `positions` is corrected.
3. Fix `network_allowlist` configuration so the runtime egress IP matches policy.
4. Keep `bin/run_incident_hygiene.sh` in the operator flow so future duplicate incidents are collapsed automatically after reconciliation.
5. Only clear the reconciliation auto lock after broker truth and local `positions` are reconciled.
