"""Test token budget monitoring (v4 #2) - Fixed version."""

import pytest
import tempfile
import json
import os
import sqlite3
import time
from pathlib import Path

from openclaw.token_budget import (
    BudgetPolicy,
    BudgetTier,
    load_budget_policy,
    evaluate_budget,
    record_token_usage,
    get_monthly_cost,
    emit_budget_event,
    _month_key
)


def test_load_budget_policy():
    """Test loading budget policy from JSON file."""
    policy_data = {
        "system_name": "Test Budget",
        "version": "1.0",
        "currency": "TWD",
        "base_monthly_budget": 1000.0,
        "tiers": {
            "warning": {
                "threshold_pct": 70,
                "action": "notify",
                "message": "Warning at 70%"
            },
            "throttling": {
                "threshold_pct": 85,
                "action": "throttle"
            },
            "critical_halt": {
                "threshold_pct": 100,
                "action": "halt"
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(policy_data, f)
        temp_path = f.name
    
    try:
        policy = load_budget_policy(Path(temp_path))
        
        assert policy.system_name == "Test Budget"
        assert policy.version == "1.0"
        assert policy.currency == "TWD"
        assert policy.base_monthly_budget == 1000.0
        
        # Check tiers
        assert "warning" in policy.tiers
        assert "throttling" in policy.tiers
        assert "critical_halt" in policy.tiers
        
        warning_tier = policy.tiers["warning"]
        assert warning_tier.threshold_pct == 70.0
        assert warning_tier.action == "notify"
        assert warning_tier.message == "Warning at 70%"
        
    finally:
        os.unlink(temp_path)


def test_evaluate_budget():
    """Test budget evaluation logic."""
    # Create a simple policy
    policy = BudgetPolicy(
        system_name="Test",
        version="1.0",
        currency="TWD",
        base_monthly_budget=1000.0,
        tiers={
            "warning": BudgetTier("warning", 70.0, "notify", "Warning"),
            "throttling": BudgetTier("throttling", 85.0, "throttle", "Throttling"),
            "critical_halt": BudgetTier("critical_halt", 100.0, "halt", "Halt")
        }
    )
    
    # Create an in-memory database
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE token_usage_monthly (
            month TEXT PRIMARY KEY,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            est_cost_twd REAL,
            updated_at TIMESTAMP
        )
    """)
    
    # Test with no usage
    status, used_pct, tier = evaluate_budget(conn, policy, month="2026-01")
    assert status == "ok"
    assert used_pct == 0.0
    assert tier is None
    
    # Add some usage (500 TWD out of 1000 = 50%)
    conn.execute("""
        INSERT INTO token_usage_monthly(month, model, prompt_tokens, completion_tokens, est_cost_twd, updated_at)
        VALUES ('2026-01', 'gemini-flash', 1000, 2000, 500.0, datetime('now'))
    """)
    
    status, used_pct, tier = evaluate_budget(conn, policy, month="2026-01")
    assert status == "ok"
    assert abs(used_pct - 50.0) < 0.01
    assert tier is None
    
    # Add more usage to reach 75% (warning tier)
    conn.execute("""
        UPDATE token_usage_monthly 
        SET est_cost_twd = 750.0 
        WHERE month = '2026-01'
    """)
    
    status, used_pct, tier = evaluate_budget(conn, policy, month="2026-01")
    assert status == "warn"
    assert abs(used_pct - 75.0) < 0.01
    assert tier is not None
    assert tier.name == "warning"
    
    # Test with zero budget (should always be ok)
    zero_policy = BudgetPolicy(
        system_name="Test",
        version="1.0",
        currency="TWD",
        base_monthly_budget=0.0,
        tiers={}
    )
    status, used_pct, tier = evaluate_budget(conn, zero_policy, month="2026-01")
    assert status == "ok"
    assert used_pct == 0.0
    assert tier is None
    
    conn.close()


def test_record_token_usage():
    """Test recording token usage."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE token_usage_monthly (
            month TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            est_cost_twd REAL,
            updated_at TIMESTAMP,
            PRIMARY KEY (month, model)
        )
    """)
    
    # Record first usage
    record_token_usage(
        conn,
        model="gemini-flash",
        prompt_tokens=1000,
        completion_tokens=2000,
        est_cost_twd=50.0,
        ts_ms=int(time.time() * 1000)
    )
    
    # Verify record
    row = conn.execute(
        "SELECT month, model, prompt_tokens, completion_tokens, est_cost_twd FROM token_usage_monthly"
    ).fetchone()
    
    assert row is not None
    current_month = _month_key()
    assert row[0] == current_month
    assert row[1] == "gemini-flash"
    assert row[2] == 1000
    assert row[3] == 2000
    assert row[4] == 50.0
    
    conn.close()


def test_get_monthly_cost():
    """Test getting monthly cost with explicit month parameter."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE token_usage_monthly (
            month TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            est_cost_twd REAL,
            updated_at TIMESTAMP,
            PRIMARY KEY (month, model)
        )
    """)
    
    # Add data for different months
    conn.executemany(
        """
        INSERT INTO token_usage_monthly(month, model, est_cost_twd, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        """,
        [
            ("2026-01", "gemini-flash", 300.0),
            ("2026-01", "gemini-pro", 200.0),
            ("2026-02", "gemini-flash", 150.0),
            ("2026-02", "gemini-pro", 100.0),
        ]
    )
    
    # Test specific month
    cost = get_monthly_cost(conn, month="2026-01")
    assert cost == 500.0  # 300 + 200
    
    cost = get_monthly_cost(conn, month="2026-02")
    assert cost == 250.0  # 150 + 100
    
    # Test non-existent month
    cost = get_monthly_cost(conn, month="2026-03")
    assert cost == 0.0
    
    conn.close()


def test_emit_budget_event():
    """Test emitting budget events."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE token_budget_events (
            event_id TEXT PRIMARY KEY,
            ts TIMESTAMP,
            month TEXT,
            tier TEXT,
            used_pct REAL,
            action TEXT,
            message TEXT,
            extra_json TEXT
        )
    """)
    
    tier = BudgetTier(
        name="warning",
        threshold_pct=70.0,
        action="notify",
        message="Budget warning"
    )
    
    # Emit event
    emit_budget_event(
        conn,
        tier=tier,
        used_pct=75.0,
        month="2026-02",
        extra={"trigger": "test"}
    )
    
    # Verify event was recorded
    row = conn.execute(
        "SELECT tier, used_pct, action, message FROM token_budget_events"
    ).fetchone()
    
    assert row is not None
    assert row[0] == "warning"
    assert row[1] == 75.0
    assert row[2] == "notify"
    assert row[3] == "Budget warning"
    
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
