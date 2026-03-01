#!/usr/bin/env python3
"""Tests for institution_ingest module."""
import sys
sys.path.insert(0, 'src')

import sqlite3
import pytest
from openclaw.institution_ingest import (
    InstitutionFlowRow,
    ensure_schema,
    upsert_institution_flows,
    get_institution_flows,
    get_market_summary,
    get_symbol_trend,
    calculate_alignment_score,
    generate_text_chart,
    get_chip_health_for_decision,
    evaluate_chip_health,
)

def test_basic_flow():
    conn = sqlite3.connect(':memory:')
    ensure_schema(conn)
    # Insert mock data
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
        ),
        InstitutionFlowRow(
            trade_date='2025-02-27',
            symbol='2317',
            foreign_net=-500.0,
            investment_trust_net=100.0,
            dealer_net=50.0,
            total_net=-350.0,
            health_score=0.4,
            source_url='test'
        ),
    ]
    upsert_institution_flows(conn, rows)
    # Query all
    all_rows = get_institution_flows(conn)
    assert len(all_rows) == 2
    # Query by date
    date_rows = get_institution_flows(conn, trade_date='2025-02-27')
    assert len(date_rows) == 2
    # Query by symbol
    sym_rows = get_institution_flows(conn, symbol='2330')
    assert len(sym_rows) == 1
    assert sym_rows[0].symbol == '2330'
    # Market summary
    summary = get_market_summary(conn, '2025-02-27')
    assert summary['total_symbols'] == 2
    assert summary['total_foreign'] == 500.0  # 1000 + (-500)
    assert summary['total_net'] == 550.0  # 900 + (-350)
    # Symbol trend
    trend = get_symbol_trend(conn, '2330', days=5)
    assert len(trend) == 1
    # Alignment score
    align = calculate_alignment_score(1000.0, 200.0, -300.0)
    assert 0 <= align <= 1
    # Text chart
    chart = generate_text_chart(rows[:1], metric='total_net', width=20)
    assert '2330' in chart
    # Chip health for decision
    chip = get_chip_health_for_decision(conn, '2330', '2025-02-27')
    assert chip['available'] == True
    assert chip['health_score'] == 0.7
    # Evaluate chip health
    eval_result = evaluate_chip_health(conn, '2330', '2025-02-27', threshold=0.5)
    assert eval_result['allowed'] == True  # health 0.7 > 0.5
    eval_result2 = evaluate_chip_health(conn, '2317', '2025-02-27', threshold=0.5)
    assert eval_result2['allowed'] == False  # health 0.4 < 0.5
    conn.close()

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
