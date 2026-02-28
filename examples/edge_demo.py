#!/usr/bin/env python3
"""
Edge Metrics 演示腳本 (v4 #16)

這個腳本展示如何：
1. 計算 edge metrics
2. 集成到決策流程
3. 更新策略版本
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# 添加項目路徑
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from openclaw.edge_metrics import compute_edge_metrics, edge_score, persist_edge_metrics_to_strategy_version
from openclaw.edge_integration import (
    analyze_strategy_edge,
    integrate_edge_into_decision,
    update_strategy_version_with_edge,
    batch_update_all_strategy_versions
)
from openclaw.strategy_registry import StrategyRegistry


def setup_test_database(db_path: str):
    """設置測試數據庫和數據"""
    
    # 確保目錄存在
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    
    # 創建 trades 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
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
    
    # 創建 strategy_versions 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_versions (
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
    
    # 創建 version_audit_log 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS version_audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
    """)
    
    # 清除現有數據
    conn.execute("DELETE FROM trades")
    conn.execute("DELETE FROM strategy_versions")
    conn.execute("DELETE FROM version_audit_log")
    
    # 插入測試交易數據 - 策略1 (良好的edge)
    strategy1_trades = []
    base_time = datetime.now() - timedelta(days=30)
    
    for i in range(50):
        # 70% 勝率，平均賺 $15，平均賠 $10
        if i % 10 < 7:  # 70% 勝率
            pnl = 15.0 + (i % 5)  # $15-$20
        else:
            pnl = -10.0 - (i % 3)  # -$10 to -$13
        
        trade_time = (base_time + timedelta(days=i/2.0)).isoformat()
        
        strategy1_trades.append((
            f"trade_strat1_{i}",
            "AAPL",
            "buy" if i % 2 == 0 else "sell",
            100,
            150.0 + (i % 10),
            1.0,
            0.5,
            pnl,
            trade_time,
            "momentum_strategy_v2",
            f"dec_{i}"
        ))
    
    # 插入測試交易數據 - 策略2 (較差的edge)
    strategy2_trades = []
    for i in range(30):
        # 40% 勝率，平均賺 $8，平均賠 $12
        if i % 10 < 4:  # 40% 勝率
            pnl = 8.0 + (i % 3)  # $8-$11
        else:
            pnl = -12.0 - (i % 4)  # -$12 to -$16
        
        trade_time = (base_time + timedelta(days=i/1.5)).isoformat()
        
        strategy2_trades.append((
            f"trade_strat2_{i}",
            "GOOGL",
            "buy" if i % 2 == 0 else "sell",
            50,
            2800.0 + (i % 50),
            2.0,
            1.0,
            pnl,
            trade_time,
            "mean_reversion_v1",
            f"dec_{i+100}"
        ))
    
    # 插入所有交易
    all_trades = strategy1_trades + strategy2_trades
    conn.executemany(
        "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        all_trades
    )
    
    # 創建策略版本
    registry = StrategyRegistry(db_path)
    
    # 策略1版本
    version1 = registry.create_version(
        strategy_config={
            "strategy_id": "momentum_strategy_v2",
            "name": "Momentum Strategy v2",
            "parameters": {
                "lookback_period": 20,
                "threshold": 0.02
            }
        },
        created_by="demo_user",
        version_tag="V2.1",
        notes="Initial version with edge metrics"
    )
    
    # 策略2版本
    version2 = registry.create_version(
        strategy_config={
            "strategy_id": "mean_reversion_v1",
            "name": "Mean Reversion v1",
            "parameters": {
                "z_score_threshold": 2.0,
                "holding_period": 5
            }
        },
        created_by="demo_user",
        version_tag="V1.0",
        notes="Mean reversion strategy"
    )
    
    conn.commit()
    conn.close()
    
    print(f"✓ 設置測試數據庫: {db_path}")
    print(f"  - 插入 {len(all_trades)} 筆交易")
    print(f"  - 創建 2 個策略版本")
    
    return {
        "strategy1_id": "momentum_strategy_v2",
        "strategy2_id": "mean_reversion_v1",
        "version1_id": version1["version_id"],
        "version2_id": version2["version_id"]
    }


def demo_edge_metrics_calculation(db_path: str, strategy_id: str):
    """演示 edge metrics 計算"""
    
    print(f"\n{'='*60}")
    print(f"演示: Edge Metrics 計算 - 策略: {strategy_id}")
    print(f"{'='*60}")
    
    # 分析策略 edge
    result = analyze_strategy_edge(db_path, strategy_id, days_back=60)
    
    print(f"\n分析結果:")
    print(f"  - 策略 ID: {result.strategy_id}")
    print(f"  - 分析期間: {result.analysis_period_days} 天")
    print(f"  - 交易數量: {result.trade_count}")
    print(f"  - Edge Score: {result.edge_score:.1f}/100")
    print(f"  - Edge 質量: {'✓ OK' if result.is_edge_ok else '✗ 需要改進'}")
    print(f"  - 建議: {result.recommendation}")
    
    print(f"\n詳細指標:")
    metrics = result.metrics
    print(f"  - 勝率: {metrics.win_rate:.2%}")
    print(f"  - 平均賺: ${metrics.avg_win:.2f}")
    print(f"  - 平均賠: ${metrics.avg_loss:.2f}")
    print(f"  - 期望值: ${metrics.expectancy:.2f}")
    print(f"  - 獲利因子: {metrics.profit_factor:.2f}")
    print(f"  - 盈虧比: {metrics.payoff_ratio:.2f}")
    print(f"  - 總損益: ${metrics.total_pnl:.2f}")
    print(f"  - 平均損益: ${metrics.avg_pnl:.2f}")
    
    return result


def demo_decision_integration(db_path: str, strategy_id: str):
    """演示決策流程集成"""
    
    print(f"\n{'='*60}")
    print(f"演示: 決策流程集成 - 策略: {strategy_id}")
    print(f"{'='*60}")
    
    # 模擬一個交易決策
    decision_data = {
        "symbol": "AAPL",
        "action": "buy",
        "quantity": 100,
        "price": 152.50,
        "position_sizing": {
            "size": 1.0,
            "max_position": 0.1,
            "current_exposure": 0.05
        },
        "risk_parameters": {
            "stop_loss": 145.0,
            "take_profit": 165.0
        }
    }
    
    print(f"\n原始決策數據:")
    print(json.dumps(decision_data, indent=2, ensure_ascii=False))
    
    # 集成 edge 分析
    updated_decision, recommendation = integrate_edge_into_decision(
        db_path=db_path,
        strategy_id=strategy_id,
        decision_data=decision_data,
        edge_threshold=50.0
    )
    
    print(f"\nEdge 分析建議: {recommendation}")
    
    print(f"\n更新後的決策數據:")
    edge_analysis = updated_decision.get('edge_analysis', {})
    edge_decision = updated_decision.get('edge_decision', {})
    
    print(f"  - Edge Score: {edge_analysis.get('edge_score', 0):.1f}")
    print(f"  - Edge 質量: {'OK' if edge_analysis.get('is_edge_ok') else '需要改進'}")
    print(f"  - 是否執行交易: {'是' if edge_decision.get('should_proceed') else '否'}")
    
    if 'position_sizing' in updated_decision:
        original_size = decision_data['position_sizing']['size']
        new_size = updated_decision['position_sizing']['size']
        if new_size != original_size:
            adjustment = updated_decision['position_sizing'].get('edge_adjustment', 1.0)
            print(f"  - 部位規模調整: {original_size} → {new_size} (調整係數: {adjustment})")
    
    if updated_decision.get('trade_blocked'):
        print(f"  - 交易被阻擋: {updated_decision.get('block_reason')}")
    
    return updated_decision


def demo_strategy_version_update(db_path: str, version_id: str, strategy_id: str):
    """演示策略版本更新"""
    
    print(f"\n{'='*60}")
    print(f"演示: 策略版本更新 - 版本: {version_id}")
    print(f"{'='*60}")
    
    # 更新策略版本
    success = update_strategy_version_with_edge(
        db_path=db_path,
        version_id=version_id,
        strategy_id=strategy_id,
        days_back=60
    )
    
    print(f"\n更新結果: {'成功' if success else '失敗'}")
    
    if success:
        # 讀取更新後的配置
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT strategy_config_json FROM strategy_versions WHERE version_id = ?",
            (version_id,)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            config = json.loads(row[0])
            edge_metrics = config.get('edge_metrics', {})
            edge_score_val = config.get('edge_score', 0)
            
            print(f"\n更新後的策略配置:")
            print(f"  - Edge Score: {edge_score_val:.1f}")
            print(f"  - 交易數量: {edge_metrics.get('n_trades', 0)}")
            print(f"  - 勝率: {edge_metrics.get('win_rate', 0):.2%}")
            print(f"  - 獲利因子: {edge_metrics.get('profit_factor', 0):.2f}")
            print(f"  - 期望值: ${edge_metrics.get('expectancy', 0):.2f}")
    
    return success


def demo_batch_update(db_path: str):
    """演示批次更新"""
    
    print(f"\n{'='*60}")
    print(f"演示: 批次更新所有策略版本")
    print(f"{'='*60}")
    
    stats = batch_update_all_strategy_versions(db_path, days_back=60)
    
    print(f"\n批次更新統計:")
    print(f"  - 總版本數: {stats['total_versions']}")
    print(f"  - 成功更新: {stats['updated']}")
    print(f"  - 更新失敗: {stats['failed']}")
    
    if stats['details']:
        print(f"\n詳細結果:")
        for detail in stats['details']:
            status_icon = "✓" if detail['status'] == 'updated' else "✗"
            print(f"  {status_icon} {detail['version_id']} - {detail['strategy_id']} ({detail['status']})")
    
    return stats


def main():
    """主演示函數"""
    
    print("="*60)
    print("Edge Metrics 系統演示 (v4 #16)")
    print("="*60)
    
    # 設置測試數據庫
    db_path = "data/sqlite/trades_demo.db"
    ids = setup_test_database(db_path)
    
    # 演示1: 策略1 (良好的edge)
    result1 = demo_edge_metrics_calculation(db_path, ids["strategy1_id"])
    
    # 演示2: 策略2 (較差的edge)
    result2 = demo_edge_metrics_calculation(db_path, ids["strategy2_id"])
    
    # 演示3: 決策集成 - 策略1
    decision1 = demo_decision_integration(db_path, ids["strategy1_id"])
    
    # 演示4: 決策集成 - 策略2
    decision2 = demo_decision_integration(db_path, ids["strategy2_id"])
    
    # 演示5: 策略版本更新
    success1 = demo_strategy_version_update(db_path, ids["version1_id"], ids["strategy1_id"])
    success2 = demo_strategy_version_update(db_path, ids["version2_id"], ids["strategy2_id"])
    
    # 演示6: 批次更新
    stats = demo_batch_update(db_path)
    
    print(f"\n{'='*60}")
    print("演示總結")
    print(f"{'='*60}")
    
    print(f"\n策略比較:")
    print(f"1. {ids['strategy1_id']}:")
    print(f"   - Edge Score: {result1.edge_score:.1f}/100")
    print(f"   - 交易數量: {result1.trade_count}")
    print(f"   - 質量: {'✓ OK' if result1.is_edge_ok else '✗ 需要改進'}")
    print(f"   - 決策: {'允許交易' if decision1.get('edge_decision', {}).get('should_proceed') else '限制交易'}")
    
    print(f"\n2. {ids['strategy2_id']}:")
    print(f"   - Edge Score: {result2.edge_score:.1f}/100")
    print(f"   - 交易數量: {result2.trade_count}")
    print(f"   - 質量: {'✓ OK' if result2.is_edge_ok else '✗ 需要改進'}")
    print(f"   - 決策: {'允許交易' if decision2.get('edge_decision', {}).get('should_proceed') else '限制交易'}")
    
    print(f"\n策略版本更新:")
    print(f"  - 版本1: {'成功' if success1 else '失敗'}")
    print(f"  - 版本2: {'成功' if success2 else '失敗'}")
    
    print(f"\n批次更新:")
    print(f"  - 總共處理: {stats['total_versions']} 個版本")
    print(f"  - 成功率: {stats['updated']/(stats['updated']+stats['failed'])*100:.1f}%")
    
    print(f"\n{'='*60}")
    print("✅ Edge Metrics 系統演示完成!")
    print(f"{'='*60}")
    
    # 清理演示數據庫
    try:
        os.remove(db_path)
        print(f"\n已清理演示數據庫: {db_path}")
    except:
        pass


if __name__ == "__main__":
    main()
