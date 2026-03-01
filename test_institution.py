#!/usr/bin/env python3
"""
Quick test for institution_ingest module.
"""
import sys
sys.path.insert(0, '/Users/openclaw/.openclaw/shared/projects/ai-trader/src')

import sqlite3
from openclaw.institution_ingest import (
    ensure_schema,
    fetch_institution_flows,
    upsert_institution_flows,
    record_ingest_run,
)

def test_basic():
    conn = sqlite3.connect(':memory:')
    ensure_schema(conn)
    
    # Check table exists
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='institution_flows'")
    assert cur.fetchone() is not None
    print("✓ Table created")
    
    # Try to fetch real data (may fail if network issue)
    try:
        rows = fetch_institution_flows('2025-02-27')  # past date
        print(f"Fetched {len(rows)} rows")
        if rows:
            print(f"Sample row: {rows[0]}")
    except Exception as e:
        print(f"Fetch failed (maybe network): {e}")
        # Create mock rows
        from openclaw.institution_ingest import InstitutionFlowRow
        rows = [
            InstitutionFlowRow(
                trade_date='2025-02-27',
                symbol='2330',
                foreign_net=1000.0,
                investment_trust_net=200.0,
                dealer_net=-300.0,
                total_net=900.0,
                health_score=0.7,
                source_url='test'
            )
        ]
    
    inserted = upsert_institution_flows(conn, rows)
    print(f"Upserted {inserted} rows")
    
    # Query back
    cur = conn.execute("SELECT COUNT(*) FROM institution_flows")
    count = cur.fetchone()[0]
    print(f"Total rows in DB: {count}")
    
    # Test record_ingest_run
    run_id = record_ingest_run(conn, trade_date='2025-02-27', status='success', rows=len(rows), source_url='test')
    print(f"Ingest run recorded: {run_id}")
    
    conn.close()
    print("Test completed")

if __name__ == '__main__':
    test_basic()
