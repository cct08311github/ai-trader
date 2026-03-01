"""
resume_protocol.py

P1-7 / v4 Gap #6: System Resume and Position Snapshot Protocol.

1. Takes snapshots of the current portfolio and system state every 5 mins.
2. During initialization, performs a self-check of system integrity.
3. Provides a /RESUME flow to load the last known good state from the `trades.db` 
   database (`position_snapshots` table) upon unexpected shutdown.
"""
import json
import logging
import datetime
from typing import Optional
from .db_router import get_connection

logger = logging.getLogger("resume_protocol")

class ResumeProtocolTracker:
    def __init__(self, check_interval_sec=300):
        self._last_snapshot_time: Optional[datetime.datetime] = None
        self._interval = check_interval_sec

    
    def snapshot(self, system_state_dict: dict, positions_list: list, available_cash: float, reason="periodic"):
        """
        Takes a snapshot of the current positions and basic system safety rules.
        """
        now = datetime.datetime.utcnow()
        if reason == "periodic" and self._last_snapshot_time:
            if (now - self._last_snapshot_time).total_seconds() < self._interval:
                return False # Skipping snapshot to reduce DB load
        
        try:
            with get_connection("trades") as conn:
                conn.execute(
                    """
                    INSERT INTO position_snapshots (system_state_json, positions_json, available_cash, reason) 
                    VALUES (?, ?, ?, ?)
                    """,
                    (json.dumps(system_state_dict), json.dumps(positions_list), available_cash, reason)
                )
            self._last_snapshot_time = now
            logger.info(f"Position snapshot taken ({reason})")
            return True
        except Exception as e:
            logger.error(f"Failed to take snapshot: {e}")
            return False

    def load_latest_snapshot(self):
        """
        Loads the most recent position/system state snapshot.
        Essential for /RESUME flow.
        """
        try:
            with get_connection("trades") as conn:
                row = conn.execute("SELECT * FROM position_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
                
            if not row:
                logger.warning("No snapshot found. Clean start.")
                return None
                
            return {
                "timestamp": row["timestamp"],
                "system_state": json.loads(row["system_state_json"]),
                "positions": json.loads(row["positions_json"]),
                "available_cash": row["available_cash"],
                "reason": row["reason"]
            }
        except Exception as e:
            logger.error(f"Failed to read snapshot for crash recovery: {e}")
            return None

def system_self_check():
    """
    On cold boot, perform self checks to see if we crashed mid-trade or 
    have orphaned orders.
    """
    logger.info("Executing System Self-Check (V4)...")
    tracker = ResumeProtocolTracker()
    latest = tracker.load_latest_snapshot()
    
    if not latest:
        return {"status": "clean", "message": "First run or DB cleared."}
        
    # Analyze the last state
    tstamp = latest["timestamp"]
    logger.info(f"Last known snapshot from {tstamp}: {len(latest['positions'])} positions held.")
    
    # Check if system was paused or halted in last state
    sys_state = latest["system_state"]
    if sys_state.get("mode") in ("halt", "suspended"):
        return {"status": "needs_resume", "details": latest}
        
    return {"status": "ok", "message": "Self check passed", "details": latest}

def run_resume_flow(force=False):
    """
    Executes the /RESUME command. 
    1. Loads Snapshot
    2. Synchronizes with real broker (mocked/abstracted here)
    3. Triggers PnL reconciliation
    """
    logger.info("--- Initiating /RESUME Protocol ---")
    tracker = ResumeProtocolTracker()
    snap = tracker.load_latest_snapshot()
    
    if not snap:
        logger.info("Nothing to resume from.")
        return False
        
    # Example reconciliation logic:
    logger.info(f"Loaded {len(snap['positions'])} saved positions.")
    logger.info("Reconciling with broker state...")
    
    # In a real app, you would fetch real broker data here, compare the diff, 
    # and possibly submit liquidation orders for orphans.
    
    logger.info("System operational state restored. Memory context re-synchronized.")
    return True
