# src/openclaw/lm_signal_cache.py
"""LLM 信號快取層

strategy_committee 辯論結論寫入此快取，signal_aggregator 讀取。
Cache miss 時 caller 應使用 neutral score（0.5）。

快取結構：
  - symbol=None：全市場方向（strategy_committee 辯論大盤）
  - symbol='XXXX'：個股層級（未來擴展）
  read_cache_with_fallback 先查個股，miss 則查全市場。
"""
import sqlite3
import time
import uuid
from typing import Optional


def write_cache(
    conn: sqlite3.Connection,
    symbol: Optional[str],       # None = 全市場方向
    score: float,                # 0.0（極空）~ 1.0（極多）
    source: str,                 # 'strategy_committee' | 'pm_review'
    direction: str,              # 'bull' | 'bear' | 'neutral'
    raw_json: str,
    ttl_seconds: int = 3600,
    autocommit: bool = True,     # False = 呼叫方自行管理 transaction
) -> str:
    """寫入 LLM 快取，回傳 cache_id。"""
    cache_id = str(uuid.uuid4())
    now = int(time.time())
    conn.execute(
        """INSERT INTO lm_signal_cache
           (cache_id, symbol, score, source, direction, raw_json, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cache_id, symbol, score, source, direction, raw_json, now, now + ttl_seconds),
    )
    if autocommit:
        conn.commit()
    return cache_id


def read_cache(conn: sqlite3.Connection, symbol: Optional[str]) -> Optional[dict]:
    """讀取最新未過期的快取。

    symbol=None → 查全市場方向。
    精確匹配：不自動 fallback（請用 read_cache_with_fallback）。
    """
    now = int(time.time())
    row = conn.execute(
        """SELECT score, direction, source FROM lm_signal_cache
           WHERE symbol IS ? AND expires_at > ?
           ORDER BY created_at DESC LIMIT 1""",
        (symbol, now),
    ).fetchone()
    if row is None:
        return None
    return {"score": float(row[0]), "direction": row[1], "source": row[2]}


def read_cache_with_fallback(conn: sqlite3.Connection, symbol: str) -> Optional[dict]:
    """先查個股快取，miss 則 fallback 至全市場快取（symbol=None）。"""
    result = read_cache(conn, symbol)
    if result is not None:
        return result
    return read_cache(conn, None)


def purge_expired(conn: sqlite3.Connection) -> None:
    """清除所有已過期的快取記錄。"""
    conn.execute("DELETE FROM lm_signal_cache WHERE expires_at <= ?", (int(time.time()),))
    conn.commit()
