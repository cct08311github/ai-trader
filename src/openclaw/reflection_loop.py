from __future__ import annotations

import json
from datetime import datetime
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


@dataclass
class ReflectionOutput:
    stage1_diagnosis: Dict[str, Any]
    stage2_abstraction: Dict[str, Any]
    stage3_refinement: Dict[str, Any]


def validate_reflection_output(payload: Dict[str, Any]) -> ReflectionOutput:
    for key in ("stage1_diagnosis", "stage2_abstraction", "stage3_refinement"):
        if key not in payload or not isinstance(payload[key], dict):
            raise ValueError(f"missing or invalid {key}")

    s1 = payload["stage1_diagnosis"]
    s2 = payload["stage2_abstraction"]
    s3 = payload["stage3_refinement"]

    if "root_cause_code" not in s1:
        raise ValueError("stage1_diagnosis.root_cause_code required")
    if "rule_text" not in s2 or "confidence" not in s2:
        raise ValueError("stage2_abstraction.rule_text/confidence required")
    if "decision" not in s3:
        raise ValueError("stage3_refinement.decision required")

    return ReflectionOutput(s1, s2, s3)


def insert_reflection_run(conn: sqlite3.Connection, trade_date: str, result: ReflectionOutput) -> str:
    run_id = str(uuid.uuid4())
    sem_size = conn.execute("SELECT COUNT(*) FROM semantic_memory WHERE status='active'").fetchone()[0]
    candidate_count = 1 if result.stage3_refinement.get("decision") == "proposal" else 0
    conn.execute(
        """
        INSERT INTO reflection_runs(
          run_id, trade_date, stage1_diagnosis_json, stage2_abstraction_json, stage3_refinement_json,
          candidate_semantic_rules, semantic_memory_size, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            run_id,
            trade_date,
            json.dumps(result.stage1_diagnosis, ensure_ascii=True),
            json.dumps(result.stage2_abstraction, ensure_ascii=True),
            json.dumps(result.stage3_refinement, ensure_ascii=True),
            int(candidate_count),
            int(sem_size),
        ),
    )
    return run_id


# ===== v4 #25 三段式反思機制擴充 =====

def check_reflection_threshold(stage2_abstraction: Dict[str, Any]) -> bool:
    """檢查反思結果是否達到生成提案的門檻。"""
    confidence = stage2_abstraction.get('confidence', 0.0)
    # 默認門檻: 0.7
    return confidence >= 0.7


def create_proposal_from_reflection(
    conn: sqlite3.Connection,
    reflection_result: ReflectionOutput,
    trade_date: str,
    generated_by: str = 'reflection_loop'
) -> Optional[str]:
    """從反思結果創建策略提案。"""
    try:
        # 嘗試導入 proposal_engine
        from openclaw.proposal_engine import create_proposal as create_proposal_func
    except ImportError:
        print('Warning: proposal_engine not available')
        return None

    # strategy_proposals table is optional in some unit tests
    if not _table_exists(conn, 'strategy_proposals'):
        return None
    
    # 提取提案數據
    stage2 = reflection_result.stage2_abstraction
    stage3 = reflection_result.stage3_refinement
    
    # 從 stage2 提取規則類別和信心度
    rule_category = stage2.get('rule_category', 'unknown')
    rule_text = stage2.get('rule_text', '')
    confidence = stage2.get('confidence', 0.5)
    
    # 從 stage3 提取提案內容
    decision = stage3.get('decision', {})
    if not isinstance(decision, dict):
        decision = {'raw': str(decision)}
    
    current_value = decision.get('current_value', '')
    proposed_value = decision.get('proposed_value', '')
    supporting_evidence = decision.get('supporting_evidence', '')
    
    # 創建提案
    proposal = create_proposal_func(
        conn=conn,
        generated_by=generated_by,
        target_rule=rule_text[:100],  # 截斷防止過長
        rule_category=rule_category,
        current_value=str(current_value)[:500],
        proposed_value=str(proposed_value)[:500],
        supporting_evidence=str(supporting_evidence)[:1000],
        confidence=confidence,
        auto_approve=False  # 反思生成的提案需要人工審核
    )
    
    return proposal.proposal_id if hasattr(proposal, 'proposal_id') else None


def record_day_episode(conn: sqlite3.Connection, trade_date: str, reflection_id: str) -> str:
    """記錄 day episode 到記憶系統。"""
    episode_id = f'day_{trade_date}_{reflection_id[:8]}'
    
    # 檢查 episodic_memory 表是否存在
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='episodic_memory'" 
    )
    if cursor.fetchone() is None:
        # 表不存在，跳過記錄
        return episode_id
    
    # 插入 day episode
    conn.execute(
        """
        INSERT INTO episodic_memory (episode_id, episode_type, trade_date, reflection_id, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (episode_id, 'day', trade_date, reflection_id, datetime.utcnow().isoformat())
    )
    
    return episode_id


def run_daily_reflection(conn: sqlite3.Connection, trade_date: str) -> Dict[str, Any]:
    """執行每日三段式反思（主函數）。"""
    # 這裡應該執行實際的反思邏輯，目前是框架
    # 實際實現應該從數據庫讀取當日交易數據，進行分析
    
    # 模擬反思結果
    reflection_result = ReflectionOutput(
        stage1_diagnosis={
            'root_cause_code': 'sample_diagnosis',
            'issues_found': ['sample_issue'],
            'patterns': []
        },
        stage2_abstraction={
            'rule_text': 'buy_threshold adjustment',
            'rule_category': 'entry_parameters',
            'confidence': 0.85,
            'generalization': 'sample generalization'
        },
        stage3_refinement={
            'decision': {
                'action': 'propose',
                'current_value': '0.02',
                'proposed_value': '0.025',
                'supporting_evidence': 'Backtest shows improvement'
            }
        }
    )
    
    # 驗證輸出
    validated_result = validate_reflection_output({
        'stage1_diagnosis': reflection_result.stage1_diagnosis,
        'stage2_abstraction': reflection_result.stage2_abstraction,
        'stage3_refinement': reflection_result.stage3_refinement
    })
    
    # 插入反思運行記錄
    run_id = insert_reflection_run(conn, trade_date, validated_result)
    
    # 檢查門檻
    if check_reflection_threshold(validated_result.stage2_abstraction):
        # 創建提案
        proposal_id = create_proposal_from_reflection(
            conn, validated_result, trade_date, 'daily_reflection'
        )
        print(f'Proposal created: {proposal_id}')
    else:
        proposal_id = None
        print('Reflection below threshold, no proposal created')
    
    # 記錄 day episode
    episode_id = record_day_episode(conn, trade_date, run_id)
    
    return {
        'run_id': run_id,
        'episode_id': episode_id,
        'proposal_id': proposal_id,
        'threshold_passed': check_reflection_threshold(validated_result.stage2_abstraction)
    }


# ===== 測試輔助函數 =====
def test_reflection_flow() -> None:
    """測試反思流程（用於開發）。"""
    import tempfile
    import os
    
    # 創建臨時數據庫
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        conn = sqlite3.connect(db_path)
        
        # 創建所需表（簡化版）
        conn.execute("""
            CREATE TABLE reflection_runs (
                run_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                stage1_diagnosis_json TEXT NOT NULL,
                stage2_abstraction_json TEXT NOT NULL,
                stage3_refinement_json TEXT NOT NULL,
                candidate_semantic_rules INTEGER,
                semantic_memory_size INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE episodic_memory (
                episode_id TEXT PRIMARY KEY,
                episode_type TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                reflection_id TEXT,
                recorded_at TEXT NOT NULL
            )
        """)
        
        conn.commit()
        
        # 運行測試反思
        result = run_daily_reflection(conn, '2026-02-28')
        print(f'Test result: {result}')
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == '__main__':
    test_reflection_flow()
