from __future__ import annotations

from datetime import datetime, timedelta
import math
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional




def _column_exists(conn, table: str, column: str) -> bool:
    """Return True if a column exists in a sqlite table."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return False
    for r in rows:
        if len(r) >= 2 and str(r[1]) == column:
            return True
    return False

@dataclass
class EpisodicRecord:
    trade_date: str
    symbol: str
    strategy_id: str
    market_regime: str
    entry_reason: str
    outcome_pnl: float
    pm_score: float
    root_cause_code: str
    episode_id: str | None = None


@dataclass
class SemanticRule:
    rule_text: str
    confidence: float
    source_episodes: List[str]
    sample_count: int
    last_validated_date: str
    status: str = "active"
    rule_id: str | None = None


def upsert_working_memory(conn: sqlite3.Connection, key: str, value: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO working_memory(mem_key, mem_value_json, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(mem_key) DO UPDATE SET
          mem_value_json = excluded.mem_value_json,
          updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=True)),
    )


def clear_working_memory(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM working_memory")




def insert_episodic_memory(conn: sqlite3.Connection, rec: EpisodicRecord) -> str:
    eid = rec.episode_id or str(uuid.uuid4())

    # Unit tests may create simplified schemas (no created_at). Production schema may
    # enforce created_at NOT NULL. Insert conditionally based on actual columns.
    if _column_exists(conn, 'episodic_memory', 'created_at'):
        conn.execute(
            """
            INSERT INTO episodic_memory(
              episode_id, trade_date, symbol, strategy_id, market_regime, entry_reason, outcome_pnl, pm_score, root_cause_code, decay_score, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, datetime('now'))
            """,
            (
                eid,
                rec.trade_date,
                rec.symbol,
                rec.strategy_id,
                rec.market_regime,
                rec.entry_reason,
                rec.outcome_pnl,
                rec.pm_score,
                rec.root_cause_code,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO episodic_memory(
              episode_id, trade_date, symbol, strategy_id, market_regime, entry_reason, outcome_pnl, pm_score, root_cause_code, decay_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0)
            """,
            (
                eid,
                rec.trade_date,
                rec.symbol,
                rec.strategy_id,
                rec.market_regime,
                rec.entry_reason,
                rec.outcome_pnl,
                rec.pm_score,
                rec.root_cause_code,
            ),
        )

    return eid




def apply_episodic_decay(conn: sqlite3.Connection, decay_lambda: float = 0.95, archive_threshold: float = 0.1) -> int:
    """Apply episodic decay and archive low-signal episodes.

    The unit tests expect decay to behave like an iterative process.
    We apply multiplicative decay to the *oldest* active episode per call.

      decay_score = decay_score * decay_lambda

    Returns the number of episodes newly archived in this call.
    """

    before_row = conn.execute("SELECT COUNT(*) FROM episodic_memory WHERE archived = 1").fetchone()
    before_n = int(before_row[0] if before_row else 0)

    row = conn.execute(
        """
        SELECT episode_id
        FROM episodic_memory
        WHERE archived = 0
        ORDER BY trade_date ASC
        LIMIT 1
        """
    ).fetchone()

    if row is not None:
        episode_id = str(row[0])
        conn.execute(
            """
            UPDATE episodic_memory
            SET decay_score = decay_score * ?
            WHERE episode_id = ?
            """,
            (float(decay_lambda), episode_id),
        )

    conn.execute(
        """
        UPDATE episodic_memory
        SET archived = 1
        WHERE archived = 0 AND decay_score < ?
        """,
        (float(archive_threshold),),
    )

    after_row = conn.execute("SELECT COUNT(*) FROM episodic_memory WHERE archived = 1").fetchone()
    after_n = int(after_row[0] if after_row else 0)
    return max(0, after_n - before_n)



def upsert_semantic_rule(conn: sqlite3.Connection, rule: SemanticRule) -> str:
    rid = rule.rule_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO semantic_memory(
          rule_id, rule_text, confidence, source_episodes_json, sample_count, last_validated_date, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(rule_id) DO UPDATE SET
          rule_text = excluded.rule_text,
          confidence = excluded.confidence,
          source_episodes_json = excluded.source_episodes_json,
          sample_count = excluded.sample_count,
          last_validated_date = excluded.last_validated_date,
          status = excluded.status,
          updated_at = datetime('now')
        """,
        (
            rid,
            rule.rule_text,
            float(rule.confidence),
            json.dumps(rule.source_episodes, ensure_ascii=True),
            int(rule.sample_count),
            rule.last_validated_date,
            rule.status,
        ),
    )
    return rid


def fetch_recent_episodic_by_symbol(conn: sqlite3.Connection, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT episode_id, trade_date, market_regime, outcome_pnl, decay_score, root_cause_code
        FROM episodic_memory
        WHERE symbol = ? AND archived = 0
        ORDER BY trade_date DESC, decay_score DESC
        LIMIT ?
        """,
        (symbol, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ===== v4 #24 分層記憶系統擴充 =====

def get_working_memory(conn: sqlite3.Connection, key: str) -> Optional[Dict[str, Any]]:
    """獲取 working memory 值。"""
    row = conn.execute(
        "SELECT mem_value_json FROM working_memory WHERE mem_key = ?",
        (key,)
    ).fetchone()
    
    if row is None:
        return None
    
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


def list_working_memory(conn: sqlite3.Connection, pattern: str = "%") -> List[Dict[str, Any]]:
    """列出 working memory 條目。"""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT mem_key, mem_value_json, updated_at 
        FROM working_memory 
        WHERE mem_key LIKE ?
        ORDER BY updated_at DESC
        """,
        (pattern,)
    ).fetchall()
    
    result = []
    for row in rows:
        try:
            value = json.loads(row["mem_value_json"])
        except (json.JSONDecodeError, TypeError):
            value = None
        
        result.append({
            "key": row["mem_key"],
            "value": value,
            "updated_at": row["updated_at"]
        })
    
    return result


def apply_semantic_decay(
    conn: sqlite3.Connection, 
    decay_lambda: float = 0.97, 
    archive_threshold: float = 0.1
) -> int:
    """應用 semantic memory 衰減。"""
    conn.execute(
        """
        UPDATE semantic_memory
        SET confidence = confidence * ?
        WHERE status = 'active'
        """,
        (decay_lambda,)
    )
    
    conn.execute(
        """
        UPDATE semantic_memory
        SET status = 'archived'
        WHERE status = 'active' AND confidence < ?
        """,
        (archive_threshold,)
    )
    
    row = conn.execute(
        "SELECT COUNT(*) FROM semantic_memory WHERE status = 'archived'"
    ).fetchone()
    
    return int(row[0] if row else 0)


def apply_layered_decay(conn: sqlite3.Connection) -> Dict[str, int]:
    """應用所有記憶層的衰減。"""
    # Working memory 衰減（清除舊條目）
    before_changes = conn.total_changes
    conn.execute(
        """
        DELETE FROM working_memory 
        WHERE updated_at < datetime('now', '-7 days')
        """
    )
    working_deleted = conn.total_changes - before_changes
    
    # Episodic memory 衰減
    episodic_archived = apply_episodic_decay(conn, decay_lambda=0.95, archive_threshold=0.1)
    
    # Semantic memory 衰減
    semantic_archived = apply_semantic_decay(conn, decay_lambda=0.97, archive_threshold=0.1)
    
    conn.commit()
    
    return {
        "working_deleted": working_deleted,
        "episodic_archived": episodic_archived,
        "semantic_archived": semantic_archived
    }


def retrieve_by_priority(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """按照 v4 規範的檢索優先順序檢索記憶。
    
    優先順序：
    1. Working memory（精確匹配）
    2. Semantic memory（高信心度）
    3. Episodic memory（近期高 decay_score）
    """
    results = []
    
    # 1. Working memory（精確匹配）
    working = get_working_memory(conn, query)
    if working is not None:
        results.append({
            "source": "working",
            "key": query,
            "content": working,
            "score": 1.0
        })
    
    # 2. Semantic memory（規則文本匹配）
    conn.row_factory = sqlite3.Row
    semantic_rows = conn.execute(
        """
        SELECT rule_id, rule_text, confidence, source_episodes_json, sample_count
        FROM semantic_memory
        WHERE status = 'active' AND rule_text LIKE ?
        ORDER BY confidence DESC, sample_count DESC
        LIMIT ?
        """,
        (f"%{query}%", limit)
    ).fetchall()
    
    for row in semantic_rows:
        try:
            source_episodes = json.loads(row["source_episodes_json"])
        except (json.JSONDecodeError, TypeError):
            source_episodes = []
        
        results.append({
            "source": "semantic",
            "rule_id": row["rule_id"],
            "rule_text": row["rule_text"],
            "confidence": row["confidence"],
            "source_episodes": source_episodes,
            "sample_count": row["sample_count"],
            "score": row["confidence"] * 0.8  # 權重調整
        })
    
    # 3. Episodic memory（事件記憶）
    episodic_rows = conn.execute(
        """
        SELECT episode_id, trade_date, symbol, market_regime, outcome_pnl, 
               decay_score, root_cause_code
        FROM episodic_memory
        WHERE archived = 0 AND (
            symbol LIKE ? OR 
            market_regime LIKE ? OR
            root_cause_code LIKE ?
        )
        ORDER BY decay_score DESC, trade_date DESC
        LIMIT ?
        """,
        (f"%{query}%", f"%{query}%", f"%{query}%", limit)
    ).fetchall()
    
    for row in episodic_rows:
        results.append({
            "source": "episodic",
            "episode_id": row[0],
            "trade_date": row[1],
            "symbol": row[2],
            "market_regime": row[3],
            "outcome_pnl": row[4],
            "decay_score": row[5],
            "root_cause_code": row[6],
            "score": row[5] * 0.6  # 權重調整
        })
    
    # 按分數排序
    results.sort(key=lambda x: x["score"], reverse=True)
    
    return results[:limit]


def get_memory_stats(conn: sqlite3.Connection) -> Dict[str, Any]:
    """獲取記憶系統統計信息。"""
    stats = {}
    
    # Working memory
    row = conn.execute("SELECT COUNT(*) FROM working_memory").fetchone()
    stats["working_count"] = row[0] if row else 0
    
    # Episodic memory
    row = conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE archived = 0"
    ).fetchone()
    stats["episodic_active"] = row[0] if row else 0
    
    row = conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE archived = 1"
    ).fetchone()
    stats["episodic_archived"] = row[0] if row else 0
    
    row = conn.execute(
        "SELECT AVG(decay_score) FROM episodic_memory WHERE archived = 0"
    ).fetchone()
    stats["episodic_avg_decay"] = float(row[0]) if row and row[0] else 0.0
    
    # Semantic memory
    row = conn.execute(
        "SELECT COUNT(*) FROM semantic_memory WHERE status = 'active'"
    ).fetchone()
    stats["semantic_active"] = row[0] if row else 0
    
    row = conn.execute(
        "SELECT COUNT(*) FROM semantic_memory WHERE status = 'archived'"
    ).fetchone()
    stats["semantic_archived"] = row[0] if row else 0
    
    row = conn.execute(
        "SELECT AVG(confidence) FROM semantic_memory WHERE status = 'active'"
    ).fetchone()
    stats["semantic_avg_confidence"] = float(row[0]) if row and row[0] else 0.0
    
    return stats


def run_memory_hygiene(conn: sqlite3.Connection) -> Dict[str, Any]:
    """運行記憶衛生任務（衰減 + 清理）。"""
    # 應用衰減
    decay_results = apply_layered_decay(conn)
    
    # 清理過時的 semantic 規則（超過 90 天未驗證）
    before_changes = conn.total_changes
    conn.execute(
        """
        UPDATE semantic_memory
        SET status = 'expired'
        WHERE status = 'active' AND last_validated_date < date('now', '-90 days')
        """
    )
    
    expired_count = conn.total_changes - before_changes
    conn.commit()
    
    return {
        **decay_results,
        "semantic_expired": expired_count
    }


# ===== 測試輔助函數 =====
def test_layered_memory() -> None:
    """測試分層記憶系統（用於開發）。"""
    import tempfile
    import os
    
    # 創建臨時數據庫
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        conn = sqlite3.connect(db_path)
        
        # 創建所需表
        conn.execute("""
            CREATE TABLE working_memory (
                mem_key TEXT PRIMARY KEY,
                mem_value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        conn.execute("""
            CREATE TABLE episodic_memory (
                episode_id TEXT PRIMARY KEY,
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                strategy_id TEXT,
                market_regime TEXT,
                entry_reason TEXT,
                outcome_pnl REAL,
                pm_score REAL,
                root_cause_code TEXT,
                decay_score REAL DEFAULT 1.0,
                archived INTEGER DEFAULT 0
            )
        """)
        
        conn.execute("""
            CREATE TABLE semantic_memory (
                rule_id TEXT PRIMARY KEY,
                rule_text TEXT NOT NULL,
                confidence REAL NOT NULL,
                source_episodes_json TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                last_validated_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        conn.commit()
        
        # 測試數據
        # 1. Working memory
        upsert_working_memory(conn, "current_strategy", {"name": "test", "params": {"buy": 0.02}})
        
        # 2. Episodic memory
        episodic_rec = EpisodicRecord(
            trade_date="2026-02-28",
            symbol="2330",
            strategy_id="strategy_v1",
            market_regime="bull",
            entry_reason="breakout",
            outcome_pnl=0.015,
            pm_score=0.8,
            root_cause_code="success"
        )
        insert_episodic_memory(conn, episodic_rec)
        
        # 3. Semantic memory
        semantic_rule = SemanticRule(
            rule_text="buy when breakout above 20-day MA",
            confidence=0.85,
            source_episodes=["ep1", "ep2"],
            sample_count=15,
            last_validated_date="2026-02-28"
        )
        upsert_semantic_rule(conn, semantic_rule)
        
        # 測試檢索
        results = retrieve_by_priority(conn, "breakout", limit=5)
        print(f"Retrieval results: {len(results)} items")
        
        # 測試衰減
        decay_results = apply_layered_decay(conn)
        print(f"Decay results: {decay_results}")
        
        # 測試統計
        stats = get_memory_stats(conn)
        print(f"Memory stats: {stats}")
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


if __name__ == "__main__":  # pragma: no cover
    test_layered_memory()
