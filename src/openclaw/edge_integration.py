"""Edge Integration Module (v4 #16).

This module integrates edge metrics calculation into the trading decision pipeline.
It provides functions to:
1. Calculate edge metrics from historical trades
2. Integrate edge metrics into decision making
3. Update strategy versions with edge metrics
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from openclaw.edge_metrics import compute_edge_metrics, EdgeMetrics, persist_edge_metrics_to_strategy_version


@dataclass
class EdgeAnalysisResult:
    """Result of edge analysis for a strategy."""
    strategy_id: str
    metrics: EdgeMetrics
    edge_score: float
    is_edge_ok: bool
    recommendation: str
    analysis_period_days: int
    trade_count: int


def get_trades_for_strategy(
    db_path: str,
    strategy_id: str,
    days_back: int = 30
) -> List[Dict[str, Any]]:
    """Get trades for a specific strategy from the database.
    
    Args:
        db_path: Path to SQLite database
        strategy_id: Strategy identifier
        days_back: Number of days to look back
        
    Returns:
        List of trade records with pnl information
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cutoff_date = (datetime.now() - timedelta(days=days_back)).isoformat()
    
    cursor.execute("""
        SELECT 
            id, symbol, action, quantity, price, fee, tax, pnl,
            timestamp, agent_id, decision_id
        FROM trades 
        WHERE agent_id = ? AND timestamp >= ?
        ORDER BY timestamp
    """, (strategy_id, cutoff_date))
    
    columns = [desc[0] for desc in cursor.description]
    trades = []
    
    for row in cursor.fetchall():
        trade = dict(zip(columns, row))
        # Convert pnl to float if it's not None
        if trade.get('pnl') is not None:
            trade['pnl'] = float(trade['pnl'])
        trades.append(trade)
    
    conn.close()
    return trades


def analyze_strategy_edge(
    db_path: str,
    strategy_id: str,
    days_back: int = 30,
    min_trades: int = 10
) -> EdgeAnalysisResult:
    """Analyze edge metrics for a strategy.
    
    Args:
        db_path: Path to SQLite database
        strategy_id: Strategy identifier
        days_back: Number of days to look back
        min_trades: Minimum number of trades required for analysis
        
    Returns:
        EdgeAnalysisResult with metrics and recommendations
    """
    trades = get_trades_for_strategy(db_path, strategy_id, days_back)
    
    if not trades:
        # Create empty metrics for no trades
        empty_metrics = compute_edge_metrics([])
        return EdgeAnalysisResult(
            strategy_id=strategy_id,
            metrics=empty_metrics,
            edge_score=0.0,
            is_edge_ok=False,
            recommendation="No trades found for analysis",
            analysis_period_days=days_back,
            trade_count=0
        )
    
    # Extract pnl values for edge metrics calculation
    pnl_values = [trade.get('pnl', 0.0) for trade in trades if trade.get('pnl') is not None]
    
    if len(pnl_values) < min_trades:
        metrics = compute_edge_metrics(pnl_values)
        return EdgeAnalysisResult(
            strategy_id=strategy_id,
            metrics=metrics,
            edge_score=0.0,
            is_edge_ok=False,
            recommendation=f"Insufficient trades for analysis: {len(pnl_values)} < {min_trades}",
            analysis_period_days=days_back,
            trade_count=len(pnl_values)
        )
    
    # Calculate edge metrics
    metrics = compute_edge_metrics(pnl_values)
    score = compute_edge_score(metrics)
    
    # Determine if edge is OK based on criteria
    is_edge_ok = evaluate_edge_quality(metrics)
    
    # Generate recommendation
    recommendation = generate_edge_recommendation(metrics, is_edge_ok)
    
    return EdgeAnalysisResult(
        strategy_id=strategy_id,
        metrics=metrics,
        edge_score=score,
        is_edge_ok=is_edge_ok,
        recommendation=recommendation,
        analysis_period_days=days_back,
        trade_count=len(pnl_values)
    )


def compute_edge_score(metrics: EdgeMetrics) -> float:
    """Compute a normalized edge score (0-100) from metrics.
    
    This is a simplified version that combines multiple factors.
    """
    from openclaw.edge_metrics import edge_score
    return edge_score(metrics)


def evaluate_edge_quality(metrics: EdgeMetrics) -> bool:
    """Evaluate if edge quality is acceptable.
    
    Criteria:
    1. Minimum 10 trades
    2. Profit factor > 1.1
    3. Expectancy > 0
    4. Win rate between 40% and 70% (optional)
    """
    if metrics.n_trades < 10:
        return False
    
    if metrics.profit_factor <= 1.1:
        return False
    
    if metrics.expectancy <= 0:
        return False
    
    # Optional: check win rate range
    if metrics.win_rate < 0.3 or metrics.win_rate > 0.8:
        # Still might be OK, but flag for review
        return metrics.profit_factor > 1.2 and metrics.expectancy > 0.5
    
    return True


def generate_edge_recommendation(metrics: EdgeMetrics, is_edge_ok: bool) -> str:
    """Generate a human-readable recommendation based on edge metrics."""
    if metrics.n_trades == 0:
        return "No trades available for analysis"
    
    if metrics.n_trades < 10:
        return f"Insufficient sample size ({metrics.n_trades} trades). Need at least 10 trades."
    
    recommendations = []
    
    if not is_edge_ok:
        recommendations.append("Edge quality below acceptable threshold.")
    
    if metrics.profit_factor < 1.1:
        recommendations.append(f"Profit factor ({metrics.profit_factor:.2f}) is too low. Target > 1.1.")
    
    if metrics.expectancy <= 0:
        recommendations.append(f"Expectancy ({metrics.expectancy:.2f}) should be positive.")
    
    if metrics.win_rate < 0.4:
        recommendations.append(f"Win rate ({metrics.win_rate:.2%}) is low. Consider improving entry signals.")
    
    if metrics.win_rate > 0.7:
        recommendations.append(f"Win rate ({metrics.win_rate:.2%}) is unusually high. Verify calculation.")
    
    if metrics.payoff_ratio < 1.0:
        recommendations.append(f"Payoff ratio ({metrics.payoff_ratio:.2f}) is less than 1. Average loss exceeds average win.")
    
    if is_edge_ok:
        if len(recommendations) == 0:
            return f"Edge quality is good. Profit factor: {metrics.profit_factor:.2f}, Expectancy: {metrics.expectancy:.2f}"
        else:
            return f"Edge is acceptable but could be improved. " + " ".join(recommendations)
    else:
        return "Edge quality needs improvement. " + " ".join(recommendations)


def integrate_edge_into_decision(
    db_path: str,
    strategy_id: str,
    decision_data: Dict[str, Any],
    edge_threshold: float = 50.0
) -> Tuple[Dict[str, Any], str]:
    """Integrate edge analysis into trading decision.
    
    Args:
        db_path: Path to SQLite database
        strategy_id: Strategy identifier
        decision_data: Current decision data
        edge_threshold: Minimum edge score to allow trading
        
    Returns:
        Tuple of (updated_decision_data, recommendation)
    """
    # Analyze edge for the strategy
    edge_result = analyze_strategy_edge(db_path, strategy_id)
    
    # Add edge metrics to decision data
    decision_data['edge_analysis'] = {
        'strategy_id': edge_result.strategy_id,
        'edge_score': edge_result.edge_score,
        'is_edge_ok': edge_result.is_edge_ok,
        'metrics': edge_result.metrics.as_dict(),
        'recommendation': edge_result.recommendation,
        'trade_count': edge_result.trade_count,
        'analysis_period_days': edge_result.analysis_period_days
    }
    
    # Determine if we should proceed with the trade based on edge
    should_proceed = True
    recommendation = edge_result.recommendation
    
    if not edge_result.is_edge_ok:
        should_proceed = False
        recommendation = f"Edge quality insufficient: {edge_result.recommendation}"
    
    if edge_result.edge_score < edge_threshold:
        should_proceed = False
        recommendation = f"Edge score ({edge_result.edge_score:.1f}) below threshold ({edge_threshold})"
    
    decision_data['edge_decision'] = {
        'should_proceed': should_proceed,
        'edge_threshold': edge_threshold,
        'actual_score': edge_result.edge_score
    }
    
    # If edge is not OK, reduce position size or block trade
    if not should_proceed:
        if 'position_sizing' in decision_data:
            # Reduce position size by 50% if edge is poor
            original_size = decision_data['position_sizing'].get('size', 1.0)
            decision_data['position_sizing']['size'] = original_size * 0.5
            decision_data['position_sizing']['edge_adjustment'] = 0.5
            recommendation += " Position size reduced by 50% due to poor edge."
        else:
            # Block the trade entirely
            decision_data['trade_blocked'] = True
            decision_data['block_reason'] = 'insufficient_edge_quality'
            recommendation += " Trade blocked due to insufficient edge quality."
    
    return decision_data, recommendation


def update_strategy_version_with_edge(
    db_path: str,
    version_id: str,
    strategy_id: str,
    days_back: int = 30
) -> bool:
    """Update a strategy version with current edge metrics.
    
    This function:
    1. Calculates edge metrics for the strategy
    2. Persists them to the strategy version
    3. Returns success status
    
    Args:
        db_path: Path to SQLite database
        version_id: Strategy version ID
        strategy_id: Strategy identifier
        days_back: Number of days to look back for trades
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Get trades and calculate metrics
        trades = get_trades_for_strategy(db_path, strategy_id, days_back)
        pnl_values = [trade.get('pnl', 0.0) for trade in trades if trade.get('pnl') is not None]
        
        if not pnl_values:
            # No trades, create empty metrics
            metrics = compute_edge_metrics([])
        else:
            metrics = compute_edge_metrics(pnl_values)
        
        # Persist metrics to strategy version
        success = persist_edge_metrics_to_strategy_version(
            db_path=db_path,
            version_id=version_id,
            metrics=metrics,
            performed_by="edge_integration",
            notes=f"Auto-updated from {len(pnl_values)} trades over {days_back} days"
        )
        
        return success
        
    except Exception as e:
        print(f"Error updating strategy version with edge metrics: {e}")
        return False


def batch_update_all_strategy_versions(
    db_path: str,
    days_back: int = 30
) -> Dict[str, Any]:
    """Batch update edge metrics for all strategy versions.
    
    Args:
        db_path: Path to SQLite database
        days_back: Number of days to look back for trades
        
    Returns:
        Dictionary with update statistics
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all strategy versions
    cursor.execute("""
        SELECT version_id, strategy_config_json 
        FROM strategy_versions 
        WHERE status = 'active'
    """)
    
    results = cursor.fetchall()
    conn.close()
    
    stats = {
        'total_versions': len(results),
        'updated': 0,
        'failed': 0,
        'details': []
    }
    
    for version_id, config_json in results:
        try:
            config = json.loads(config_json) if config_json else {}
            strategy_id = config.get('strategy_id', 'unknown')
            
            success = update_strategy_version_with_edge(
                db_path=db_path,
                version_id=version_id,
                strategy_id=strategy_id,
                days_back=days_back
            )
            
            if success:
                stats['updated'] += 1
                stats['details'].append({
                    'version_id': version_id,
                    'strategy_id': strategy_id,
                    'status': 'updated'
                })
            else:
                stats['failed'] += 1
                stats['details'].append({
                    'version_id': version_id,
                    'strategy_id': strategy_id,
                    'status': 'failed'
                })
                
        except Exception as e:
            stats['failed'] += 1
            stats['details'].append({
                'version_id': version_id,
                'strategy_id': 'unknown',
                'status': 'error',
                'error': str(e)
            })
    
    return stats
