"""Test Edge Integration Module (v4 #16)."""

import os
import tempfile
import sqlite3
import json
from datetime import datetime, timedelta


def test_edge_integration_basic():
    """Test basic edge integration functionality."""
    from openclaw.edge_integration import (
        analyze_strategy_edge,
        evaluate_edge_quality,
        generate_edge_recommendation
    )
    
    # Create a temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        # Create trades table and insert some test data
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                action TEXT,
                quantity INTEGER,
                price REAL,
                fee REAL,
                tax REAL,
                pnl REAL,
                timestamp TEXT,
                agent_id TEXT,
                decision_id TEXT
            )
        """)
        
        # Insert some test trades with positive edge
        test_trades = [
            ("1", "AAPL", "buy", 100, 150.0, 1.0, 0.5, 10.0, 
             (datetime.now() - timedelta(days=1)).isoformat(), "strategy_1", "dec_1"),
            ("2", "AAPL", "sell", 100, 155.0, 1.0, 0.5, 8.0, 
             (datetime.now() - timedelta(days=2)).isoformat(), "strategy_1", "dec_2"),
            ("3", "GOOGL", "buy", 50, 2800.0, 2.0, 1.0, -5.0, 
             (datetime.now() - timedelta(days=3)).isoformat(), "strategy_1", "dec_3"),
            ("4", "GOOGL", "sell", 50, 2790.0, 2.0, 1.0, -3.0, 
             (datetime.now() - timedelta(days=4)).isoformat(), "strategy_1", "dec_4"),
            ("5", "MSFT", "buy", 200, 300.0, 1.5, 0.8, 15.0, 
             (datetime.now() - timedelta(days=5)).isoformat(), "strategy_1", "dec_5"),
        ]
        
        for trade in test_trades:
            conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                trade
            )
        
        conn.commit()
        conn.close()
        
        # Test edge analysis
        result = analyze_strategy_edge(db_path, "strategy_1", days_back=30)
        
        assert result.strategy_id == "strategy_1"
        assert result.trade_count == 5
        assert result.metrics.n_trades == 5
        
        # Test edge quality evaluation
        is_ok = evaluate_edge_quality(result.metrics)
        # With 3 wins and 2 losses, profit factor should be > 1.1
        assert result.metrics.profit_factor > 1.0
        
        # Test recommendation generation
        recommendation = generate_edge_recommendation(result.metrics, is_ok)
        assert isinstance(recommendation, str)
        assert len(recommendation) > 0
        
        print("✓ Basic edge integration tests passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_edge_integration_decision():
    """Test edge integration into decision making."""
    from openclaw.edge_integration import integrate_edge_into_decision
    
    # Create a temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        # Create trades table and insert some test data
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                action TEXT,
                quantity INTEGER,
                price REAL,
                fee REAL,
                tax REAL,
                pnl REAL,
                timestamp TEXT,
                agent_id TEXT,
                decision_id TEXT
            )
        """)
        
        # Insert test trades with good edge
        for i in range(15):
            pnl = 10.0 if i % 3 != 0 else -5.0  # Mostly positive PnL
            conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"test_{i}", "AAPL", "buy", 100, 150.0, 1.0, 0.5, pnl,
                    (datetime.now() - timedelta(days=i)).isoformat(), 
                    "good_strategy", f"dec_{i}"
                )
            )
        
        conn.commit()
        conn.close()
        
        # Test decision integration with good edge
        decision_data = {
            "symbol": "AAPL",
            "action": "buy",
            "quantity": 100,
            "position_sizing": {"size": 1.0}
        }
        
        updated_decision, recommendation = integrate_edge_into_decision(
            db_path=db_path,
            strategy_id="good_strategy",
            decision_data=decision_data,
            edge_threshold=50.0
        )
        
        assert "edge_analysis" in updated_decision
        assert "edge_decision" in updated_decision
        assert updated_decision["edge_analysis"]["strategy_id"] == "good_strategy"
        
        # With good edge, position size should not be reduced
        assert updated_decision["position_sizing"]["size"] == 1.0
        
        print("✓ Edge decision integration tests passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_edge_integration_strategy_version():
    """Test edge integration with strategy versions."""
    from openclaw.edge_integration import update_strategy_version_with_edge
    from openclaw.strategy_registry import StrategyRegistry
    
    # Create a temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    
    try:
        # Create all necessary tables
        conn = sqlite3.connect(db_path)
        
        # Create trades table
        conn.execute("""
            CREATE TABLE trades (
                id TEXT PRIMARY KEY,
                symbol TEXT,
                action TEXT,
                quantity INTEGER,
                price REAL,
                fee REAL,
                tax REAL,
                pnl REAL,
                timestamp TEXT,
                agent_id TEXT,
                decision_id TEXT
            )
        """)
        
        # Create strategy_versions table
        conn.execute("""
            CREATE TABLE strategy_versions (
                version_id TEXT PRIMARY KEY,
                version_tag TEXT,
                status TEXT,
                strategy_config_json TEXT,
                created_by TEXT,
                source_proposal_id TEXT,
                notes TEXT,
                created_at TEXT,
                effective_from TEXT
            )
        """)
        
        # Create version_audit_log table
        conn.execute("""
            CREATE TABLE version_audit_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT,
                action TEXT,
                performed_by TEXT,
                details TEXT,
                performed_at TEXT
            )
        """)
        
        # Insert test trades
        for i in range(10):
            pnl = 8.0 if i % 4 != 0 else -4.0  # Mostly positive PnL
            conn.execute(
                "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"trade_{i}", "TSLA", "buy", 50, 200.0, 1.0, 0.5, pnl,
                    (datetime.now() - timedelta(days=i)).isoformat(), 
                    "version_strategy", f"dec_{i}"
                )
            )
        
        # Create a strategy version
        version_id = "test_version_123"
        config = {
            "strategy_id": "version_strategy",
            "name": "Test Strategy",
            "parameters": {"param1": "value1"}
        }
        
        conn.execute(
            "INSERT INTO strategy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                "V1.0",
                "active",
                json.dumps(config),
                "test_user",
                None,
                "Test version",
                datetime.now().isoformat(),
                datetime.now().isoformat()
            )
        )
        
        conn.commit()
        conn.close()
        
        # Test updating strategy version with edge metrics
        success = update_strategy_version_with_edge(
            db_path=db_path,
            version_id=version_id,
            strategy_id="version_strategy",
            days_back=30
        )
        
        assert success is True
        
        # Verify the update
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_config_json FROM strategy_versions WHERE version_id = ?",
            (version_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        config_updated = json.loads(row[0])
        assert "edge_metrics" in config_updated
        assert "edge_score" in config_updated
        assert config_updated["edge_metrics"]["n_trades"] == 10
        
        print("✓ Strategy version edge integration tests passed")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":
    test_edge_integration_basic()
    test_edge_integration_decision()
    test_edge_integration_strategy_version()
    print("\n✅ All edge integration tests passed!")
