# tests/test_strategy_optimizer.py
import sqlite3, time, pytest

@pytest.fixture
def opt_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
            qty INTEGER, price REAL, status TEXT, ts_submit TEXT,
            decision_id TEXT, broker_order_id TEXT, order_type TEXT,
            tif TEXT, strategy_version TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY, order_id TEXT,
            ts_fill TEXT, qty INTEGER, price REAL, fee REAL, tax REAL
        );
        CREATE TABLE optimization_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,
            trigger_type TEXT NOT NULL, param_key TEXT NOT NULL,
            old_value REAL, new_value REAL, is_auto INTEGER DEFAULT 0,
            sample_n INTEGER, confidence REAL, rationale TEXT
        );
        CREATE TABLE param_bounds (
            param_key TEXT PRIMARY KEY, min_val REAL NOT NULL,
            max_val REAL NOT NULL, weekly_max_delta REAL NOT NULL,
            last_auto_change_ts INTEGER, frozen_until_ts INTEGER
        );
        CREATE TABLE risk_limits (
            name TEXT PRIMARY KEY, value REAL NOT NULL,
            updated_at INTEGER
        );
    """)
    conn.commit()
    return conn


def _insert_matched_trade(conn, symbol, buy_price, sell_price, qty=1000, days_ago=5):
    """插入一筆完整的買賣配對（模擬已平倉交易）"""
    import uuid
    from datetime import datetime, timedelta
    ts_buy  = (datetime.now() - timedelta(days=days_ago+1)).isoformat()
    ts_sell = (datetime.now() - timedelta(days=days_ago)).isoformat()

    buy_id  = str(uuid.uuid4())
    sell_id = str(uuid.uuid4())
    fill_buy_id  = str(uuid.uuid4())
    fill_sell_id = str(uuid.uuid4())

    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (buy_id, symbol, "buy", qty, buy_price, "filled", ts_buy,
         "d1", "b1", "market", "ROD", "v1"))
    conn.execute("INSERT INTO fills VALUES (?,?,?,?,?,?,?)",
        (fill_buy_id, buy_id, ts_buy, qty, buy_price, buy_price*qty*0.001425, 0))

    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sell_id, symbol, "sell", qty, sell_price, "filled", ts_sell,
         "d2", "b2", "market", "ROD", "v1"))
    fee  = sell_price * qty * 0.001425
    tax  = sell_price * qty * 0.003
    conn.execute("INSERT INTO fills VALUES (?,?,?,?,?,?,?)",
        (fill_sell_id, sell_id, ts_sell, qty, sell_price, fee, tax))
    conn.commit()


class TestStrategyMetricsEngine:
    def test_insufficient_sample_returns_low_confidence(self, opt_db):
        """樣本不足時 confidence < 0.6，不應觸發調整"""
        _insert_matched_trade(opt_db, "2330", 100, 105)  # 只有 1 筆
        from openclaw.strategy_optimizer import StrategyMetricsEngine
        report = StrategyMetricsEngine(opt_db).compute(window_days=28)
        assert report.confidence < 0.6
        assert report.sample_n == 1

    def test_30_trades_gives_full_confidence(self, opt_db):
        """30 筆以上 confidence = 1.0"""
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100+i, 103+i)
        from openclaw.strategy_optimizer import StrategyMetricsEngine
        report = StrategyMetricsEngine(opt_db).compute(window_days=28)
        assert report.confidence >= 1.0
        assert report.sample_n >= 30

    def test_win_rate_calculation(self, opt_db):
        """勝率正確計算：3 盈 2 虧 = 60%"""
        for price in [100, 105, 110]:  # 3 盈
            _insert_matched_trade(opt_db, "2330", price, price + 5)
        for price in [100, 105]:  # 2 虧
            _insert_matched_trade(opt_db, "2330", price, price - 3)
        from openclaw.strategy_optimizer import StrategyMetricsEngine
        report = StrategyMetricsEngine(opt_db).compute(window_days=28)
        assert abs(report.win_rate - 0.6) < 0.01


class TestOptimizationGateway:
    def test_low_confidence_does_not_auto_adjust(self, opt_db):
        """confidence < 0.6 不觸發任何自動調整"""
        _insert_matched_trade(opt_db, "2330", 100, 95)  # 1 筆虧損
        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        gw = OptimizationGateway(opt_db)
        adjustments = gw.on_eod(metrics)
        assert adjustments == []

    def test_param_bounds_respected(self, opt_db):
        """調整不超出 param_bounds 定義的 weekly_max_delta"""
        # 插入 param_bounds
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, None)
        )
        opt_db.execute("INSERT INTO risk_limits VALUES ('trailing_pct', 0.05, ?)", (int(time.time()),))
        opt_db.commit()

        # 30 筆全是虧損 → 應嘗試調整 trailing_pct
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 95)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        gw = OptimizationGateway(opt_db)
        adjustments = gw.on_eod(metrics)

        for adj in adjustments:
            if adj["param_key"] == "trailing_pct":
                delta = abs(adj["new_value"] - adj["old_value"])
                assert delta <= 0.005  # weekly_max_delta

    def test_adjustment_written_to_optimization_log(self, opt_db):
        """自動調整應寫入 optimization_log"""
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, None)
        )
        opt_db.execute("INSERT INTO risk_limits VALUES ('trailing_pct', 0.05, ?)", (int(time.time()),))
        opt_db.commit()
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 95)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        OptimizationGateway(opt_db).on_eod(metrics)

        log_count = opt_db.execute("SELECT COUNT(*) FROM optimization_log").fetchone()[0]
        assert log_count > 0

    def test_frozen_param_not_adjusted(self, opt_db):
        """frozen_until_ts 未到期的參數不被調整"""
        future = int(time.time()) + 86400 * 7
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, future)  # frozen
        )
        opt_db.execute("INSERT INTO risk_limits VALUES ('trailing_pct', 0.05, ?)", (int(time.time()),))
        opt_db.commit()
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 95)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        adjustments = OptimizationGateway(opt_db).on_eod(metrics)

        trailing_adjs = [a for a in adjustments if a["param_key"] == "trailing_pct"]
        assert trailing_adjs == []  # 凍結期間不調整

    def test_weekly_max_delta_cumulative_blocks_second_adjustment(self, opt_db):
        """本週累積調整已達 weekly_max_delta 時，第二次調整被跳過"""
        now = int(time.time())
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, None)
        )
        opt_db.execute("INSERT INTO risk_limits VALUES ('trailing_pct', 0.05, ?)", (now,))
        # 插入一筆本週已發生的自動調整，delta=0.005（達到 weekly_max_delta）
        opt_db.execute(
            """INSERT INTO optimization_log
               (ts, trigger_type, param_key, old_value, new_value, is_auto, sample_n, confidence, rationale)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (now - 3600, "eod_stats", "trailing_pct", 0.050, 0.055, 1, 30, 1.0, "prior_auto"),
        )
        opt_db.commit()
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 95)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        adjustments = OptimizationGateway(opt_db).on_eod(metrics)

        trailing_adjs = [a for a in adjustments if a["param_key"] == "trailing_pct"]
        assert trailing_adjs == []  # 本週預算耗盡，不應再調整

    def test_last_auto_change_ts_updated_after_adjustment(self, opt_db):
        """自動調整成功後 param_bounds.last_auto_change_ts 應被更新"""
        now = int(time.time())
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, None)
        )
        opt_db.execute("INSERT INTO risk_limits VALUES ('trailing_pct', 0.05, ?)", (now,))
        opt_db.commit()
        for i in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 95)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        OptimizationGateway(opt_db).on_eod(metrics)

        row = opt_db.execute(
            "SELECT last_auto_change_ts FROM param_bounds WHERE param_key='trailing_pct'"
        ).fetchone()
        assert row is not None and row["last_auto_change_ts"] is not None
        assert row["last_auto_change_ts"] >= now


class TestReflectionAgent:
    def test_reflect_returns_list(self, opt_db, monkeypatch):
        """reflect_weekly 回傳 list（即使 Gemini 未設定也不崩潰）"""
        # mock llm_gemini
        import sys, types
        fake_gemini = types.ModuleType("openclaw.llm_gemini")
        fake_gemini.call_gemini = lambda *a, **kw: '{"direction":"neutral","rationale":"test","proposals":[]}'
        sys.modules["openclaw.llm_gemini"] = fake_gemini

        from openclaw.strategy_optimizer import ReflectionAgent
        agent = ReflectionAgent(opt_db)
        result = agent.reflect_weekly()
        assert isinstance(result, list)

    def test_reflect_no_crash_on_llm_error(self, opt_db, monkeypatch):
        """Gemini 拋出例外時 reflect_weekly 回傳空 list 不崩潰"""
        import sys, types
        fake_gemini = types.ModuleType("openclaw.llm_gemini")
        def bad_call(*a, **kw): raise RuntimeError("Gemini timeout")
        fake_gemini.call_gemini = bad_call
        sys.modules["openclaw.llm_gemini"] = fake_gemini

        from openclaw.strategy_optimizer import ReflectionAgent
        result = ReflectionAgent(opt_db).reflect_weekly()
        assert result == []
