import sqlite3, pytest, json, time

@pytest.fixture
def eng_db(tmp_path):
    """建立含所有必要表的測試 DB"""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
            current_price REAL, unrealized_pnl REAL, high_water_mark REAL,
            state TEXT DEFAULT 'HOLDING', entry_trading_day TEXT
        );
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL,
            PRIMARY KEY (trade_date, symbol)
        );
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY, generated_by TEXT, target_rule TEXT,
            rule_category TEXT, current_value TEXT, proposed_value TEXT,
            supporting_evidence TEXT, confidence REAL, requires_human_approval INTEGER,
            status TEXT, expires_at INTEGER, proposal_json TEXT,
            created_at INTEGER, decided_at INTEGER
        );
        CREATE TABLE position_events (
            event_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
            from_state TEXT, to_state TEXT NOT NULL, reason TEXT,
            trading_day TEXT, ts INTEGER NOT NULL
        );
        CREATE TABLE position_candidates (
            symbol TEXT PRIMARY KEY, trading_day TEXT NOT NULL,
            reason TEXT, created_at INTEGER NOT NULL
        );
    """)
    conn.commit()
    return conn


def _insert_position(conn, symbol, qty, avg_price, current_price, state="HOLDING", entry_day="2026-01-01"):
    conn.execute(
        "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?)",
        (symbol, qty, avg_price, current_price, 0.0, current_price, state, entry_day)
    )
    conn.commit()


def _insert_eod_prices(conn, symbol, from_date_str, days, start_price=100.0):
    """插入 N 天的模擬 eod_prices（日期從 from_date_str 起連續）"""
    from datetime import date, timedelta
    d = date.fromisoformat(from_date_str)
    price = start_price
    for i in range(days):
        conn.execute("INSERT OR IGNORE INTO eod_prices VALUES (?,?,?,?,?,?,?)",
                     (d.isoformat(), symbol, price, price*1.01, price*0.99, price, 1e6))
        d += timedelta(days=1)
        price *= 1.001
    conn.commit()


class TestTimeStop:
    def test_no_action_when_hold_days_below_threshold(self, eng_db):
        """持倉天數未達門檻時不觸發時間止損"""
        _insert_position(eng_db, "2330", 1000, 100.0, 98.0,  # 虧損
                         entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 5)  # 只有 5 天

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        proposals = eng_db.execute("SELECT COUNT(*) FROM strategy_proposals").fetchone()[0]
        assert proposals == 0

    def test_time_stop_losing_at_10_days(self, eng_db):
        """虧損持倉持有 10 個交易日應觸發時間止損 proposal（auto approved）"""
        _insert_position(eng_db, "2330", 1000, 100.0, 97.0,
                         entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 10)  # 10 天

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        p = eng_db.execute("SELECT status, proposal_json FROM strategy_proposals").fetchone()
        assert p is not None
        assert p["status"] == "approved"
        pj = json.loads(p["proposal_json"])
        assert pj["type"] == "time_stop"
        assert pj["symbol"] == "2330"

    def test_time_stop_profit_at_30_days(self, eng_db):
        """獲利持倉持有 30 個交易日應觸發時間止損 proposal（pending，需人工審核）"""
        _insert_position(eng_db, "2330", 1000, 100.0, 115.0,  # 獲利
                         entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 30)

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        p = eng_db.execute("SELECT status FROM strategy_proposals").fetchone()
        assert p is not None
        assert p["status"] == "pending"  # 獲利持倉需人工審核

    def test_state_updated_to_exiting_after_time_stop(self, eng_db):
        """時間止損觸發後持倉 state 改為 EXITING"""
        _insert_position(eng_db, "2330", 1000, 100.0, 97.0,
                         entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 10)

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        state = eng_db.execute(
            "SELECT state FROM positions WHERE symbol='2330'"
        ).fetchone()["state"]
        assert state == "EXITING"

    def test_position_event_recorded(self, eng_db):
        """狀態轉換應記錄到 position_events"""
        _insert_position(eng_db, "2330", 1000, 100.0, 97.0,
                         entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 10)

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        event = eng_db.execute("SELECT * FROM position_events").fetchone()
        assert event is not None
        assert event["to_state"] == "EXITING"
        assert "time_stop" in event["reason"]

    def test_candidate_purge(self, eng_db):
        """過期 CANDIDATE 在 tick 時自動清除"""
        eng_db.execute(
            "INSERT INTO position_candidates VALUES ('OLD',?,?,?)",
            ("2025-12-01", "stale", int(time.time()) - 86400 * 5)
        )
        eng_db.commit()
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 1)

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        remaining = eng_db.execute("SELECT COUNT(*) FROM position_candidates").fetchone()[0]
        assert remaining == 0

    def test_exiting_position_not_retriggered(self, eng_db):
        """已在 EXITING 狀態的持倉不應重複觸發"""
        _insert_position(eng_db, "2330", 1000, 100.0, 97.0,
                         state="EXITING", entry_day="2026-01-01")
        _insert_eod_prices(eng_db, "2330", "2026-01-02", 10)

        from openclaw.trading_engine import tick
        tick(eng_db, "2330")

        proposals = eng_db.execute("SELECT COUNT(*) FROM strategy_proposals").fetchone()[0]
        assert proposals == 0  # 不重複觸發
