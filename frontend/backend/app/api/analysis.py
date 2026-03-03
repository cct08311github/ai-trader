from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

import app.db as db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def conn_dep():
    try:
        with db.get_conn() as conn:
            yield conn
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for key in ("market_summary", "technical", "strategy"):
        if isinstance(d.get(key), str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


@router.get("/latest")
def get_latest(conn: sqlite3.Connection = Depends(conn_dep)):
    row = conn.execute(
        "SELECT * FROM eod_analysis_reports ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No analysis report found")
    return _row_to_dict(row)


@router.get("/dates")
def get_dates(conn: sqlite3.Connection = Depends(conn_dep)):
    rows = conn.execute(
        "SELECT trade_date FROM eod_analysis_reports ORDER BY trade_date DESC LIMIT 30"
    ).fetchall()
    return [r["trade_date"] for r in rows]


@router.get("/{trade_date}")
def get_by_date(trade_date: str, conn: sqlite3.Connection = Depends(conn_dep)):
    row = conn.execute(
        "SELECT * FROM eod_analysis_reports WHERE trade_date=?", (trade_date,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"No report for {trade_date}")
    return _row_to_dict(row)
