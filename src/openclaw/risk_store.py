from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class LimitQuery:
    symbol: Optional[str] = None
    strategy_id: Optional[str] = None


def load_limits(conn: sqlite3.Connection, query: LimitQuery) -> Dict[str, float]:
    """
    Load enabled limits with precedence:
    global < symbol < strategy.
    """
    conn.row_factory = sqlite3.Row

    base: Dict[str, float] = {}
    for row in conn.execute(
        """
        SELECT rule_name, rule_value
        FROM risk_limits
        WHERE enabled = 1
          AND scope = 'global'
        """
    ):
        base[row["rule_name"]] = float(row["rule_value"])

    if query.symbol:
        for row in conn.execute(
            """
            SELECT rule_name, rule_value
            FROM risk_limits
            WHERE enabled = 1
              AND scope = 'symbol'
              AND symbol = ?
            """,
            (query.symbol,),
        ):
            base[row["rule_name"]] = float(row["rule_value"])

    if query.strategy_id:
        for row in conn.execute(
            """
            SELECT rule_name, rule_value
            FROM risk_limits
            WHERE enabled = 1
              AND scope = 'strategy'
              AND strategy_id = ?
            """,
            (query.strategy_id,),
        ):
            base[row["rule_name"]] = float(row["rule_value"])

    return base


def seed_sql(conn: sqlite3.Connection, sql_text: str) -> None:
    conn.executescript(sql_text)
    conn.commit()
