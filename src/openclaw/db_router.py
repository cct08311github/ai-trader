"""
db_router.py

P1-7 / v4 Gap #7: Database routing and connection management.
Encapsulates SQLite connection creation, ensuring WAL mode and busy_timeout
are enforced for concurrent access. Routes different data domains to separate DB files.
"""
import sqlite3
import os
from pathlib import Path

# Base directory for databases
DB_DIR = Path(os.getenv("OPENCLAW_HOME", os.path.expanduser("~/.openclaw"))) / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)

# Default timeout for locked databases
DEFAULT_TIMEOUT = 30.0

def get_db_path(domain: str) -> Path:
    """
    Routes the given domain to a specific database file.
    Domains:
      - 'main': System metadata, agents, llm_traces (main.db)
      - 'trades': Execution orders and positions (trades.db)
      - 'ticks': High frequency market data (ticks.db)
      - 'memory': Cognitive memory store (memory.db)
    """
    if domain in ("ticks", "market_data"):
        return DB_DIR / "ticks.db"
    elif domain in ("trades", "execution"):
        return DB_DIR / "trades.db"
    elif domain == "memory":
        return DB_DIR / "memory.db"
    else:
        return DB_DIR / "main.db"

def get_connection(domain: str = "main", timeout: float = DEFAULT_TIMEOUT) -> sqlite3.Connection:
    """
    Creates and returns a thread-safe SQLite connection for the specified domain.
    Enforces WAL mode and busy_timeout to prevent 'database is locked' errors.
    """
    db_path = get_db_path(domain)
    
    # isolation_level=None enables autocommit mode, which is generally safer
    # for concurrent environments when combined with explicit BEGIN/COMMIT blocks.
    conn = sqlite3.connect(
        str(db_path),
        timeout=timeout,
        check_same_thread=False,
        isolation_level=None  
    )
    
    # Return dictionary-like rows
    conn.row_factory = sqlite3.Row
    
    # Enforce WAL mode and other performance/concurrency PRAGMAs
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")  # 30 seconds
    conn.execute("PRAGMA foreign_keys=ON;")
    
    return conn

def init_execution_tables():
    """
    Initializes necessary tables in the trades database.
    (This addresses the execution table requirement for the trades router).
    """
    with get_connection("trades") as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS position_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                system_state_json TEXT NOT NULL,
                positions_json TEXT NOT NULL,
                available_cash REAL,
                reason TEXT
            )
        ''')
        # Ensure executions (trades) table exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                pnl REAL,
                fee REAL,
                tax REAL,
                status TEXT
            )
        ''')
