# tests/test_strategy_optimizer.py
import sqlite3, time, uuid, pytest


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
            limit_id TEXT PRIMARY KEY, scope TEXT, symbol TEXT,
            strategy_id TEXT, rule_name TEXT, rule_value REAL,
            enabled INTEGER DEFAULT 1, updated_at TEXT
        );
    """)
    conn.commit()
    return conn


def _insert_matched_trade(conn, symbol, buy_price, sell_price, qty=1000, days_ago=5):
    """插入一筆完整的買賣配對（模擬已平倉交易）"""
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


def _insert_trailing_pct(conn, value=0.05):
    """插入 trailing_pct risk_limit（使用正確的 production schema）"""
    conn.execute(
        "INSERT OR IGNORE INTO risk_limits (limit_id, scope, rule_name, rule_value, enabled, updated_at) "
        "VALUES (?, 'global', 'trailing_pct', ?, 1, datetime('now'))",
        (uuid.uuid4().hex[:16], value),
    )
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
        opt_db.execute(
            "INSERT INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.005, None, None)
        )
        _insert_trailing_pct(opt_db, 0.05)

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
        _insert_trailing_pct(opt_db, 0.05)
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
        _insert_trailing_pct(opt_db, 0.05)
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
        _insert_trailing_pct(opt_db, 0.05)
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
        _insert_trailing_pct(opt_db, 0.05)
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


class TestWalkForwardValidator:
    """WalkForwardValidator 單元測試 [Issue #281]"""

    def _insert_trades(self, conn, n_wins, n_losses, days_ago=5):
        """在 days_ago 天前插入 n_wins 筆獲利 + n_losses 筆虧損交易。"""
        from datetime import datetime, timedelta
        for i in range(n_wins):
            _insert_matched_trade(conn, "2330", 100, 110, days_ago=days_ago)
        for i in range(n_losses):
            _insert_matched_trade(conn, "2454", 100, 90, days_ago=days_ago)

    def test_bypass_when_validation_sample_insufficient(self, opt_db):
        """驗證期交易筆數 < _WF_MIN_VALID_TRADES → bypass（保守通過）。"""
        from openclaw.strategy_optimizer import (
            WalkForwardValidator, MetricsReport, _WF_MIN_VALID_TRADES
        )
        # 驗證期（最近 20 天）只有 1 筆交易
        _insert_matched_trade(opt_db, "2330", 100, 90, days_ago=5)

        vld = WalkForwardValidator(opt_db)
        train_metrics = MetricsReport(sample_n=30, confidence=1.0,
                                      win_rate=0.2, profit_factor=0.5)
        passed, reason = vld.validate("low_win_rate", train_metrics)
        assert passed is True
        assert "bypass" in reason

    def test_passes_when_validation_confirms_low_win_rate(self, opt_db):
        """驗證期也是低勝率 → 通過（確認問題真實）。"""
        from openclaw.strategy_optimizer import WalkForwardValidator, MetricsReport
        # 插入足夠筆數的全虧損交易（在驗證期內）
        for _ in range(10):
            _insert_matched_trade(opt_db, "2330", 100, 90, days_ago=5)

        vld = WalkForwardValidator(opt_db)
        train_metrics = MetricsReport(sample_n=30, confidence=1.0,
                                      win_rate=0.2, profit_factor=0.5)
        passed, reason = vld.validate("low_win_rate", train_metrics)
        assert passed is True
        assert "confirmed" in reason

    def test_rejects_when_validation_shows_good_win_rate(self, opt_db):
        """驗證期勝率恢復（>= 0.35）→ 拒絕調整（避免過度擬合）。"""
        from openclaw.strategy_optimizer import WalkForwardValidator, MetricsReport
        # 插入驗證期全是獲利交易（win_rate = 1.0）
        for _ in range(10):
            _insert_matched_trade(opt_db, "2330", 100, 120, days_ago=5)

        vld = WalkForwardValidator(opt_db)
        train_metrics = MetricsReport(sample_n=30, confidence=1.0,
                                      win_rate=0.2, profit_factor=0.5)
        passed, reason = vld.validate("low_win_rate", train_metrics)
        assert passed is False
        assert "rejected" in reason

    def test_unknown_condition_bypasses(self, opt_db):
        """未知條件 → bypass（保守通過）。"""
        from openclaw.strategy_optimizer import WalkForwardValidator, MetricsReport
        for _ in range(5):
            _insert_matched_trade(opt_db, "2330", 100, 90, days_ago=5)

        vld = WalkForwardValidator(opt_db)
        train_metrics = MetricsReport(sample_n=30, confidence=1.0,
                                      win_rate=0.2, profit_factor=0.5)
        passed, reason = vld.validate("unknown_condition", train_metrics)
        assert passed is True
        assert "bypass" in reason


class TestOptimizationGatewayWalkForward:
    """OptimizationGateway walk-forward 整合測試 [Issue #281]"""

    def _setup_gateway(self, opt_db):
        opt_db.execute(
            "INSERT OR REPLACE INTO param_bounds VALUES (?,?,?,?,?,?)",
            ("trailing_pct", 0.03, 0.10, 0.02, None, None)
        )
        _insert_trailing_pct(opt_db, 0.05)
        opt_db.commit()

    def test_adjustment_blocked_when_validation_recovers(self, opt_db):
        """訓練期低勝率但驗證期已恢復 → 調整被 walk-forward 拒絕。"""
        self._setup_gateway(opt_db)

        # 60+ 天前插入 30 筆虧損（訓練期）
        for _ in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 90, days_ago=50)

        # 最近 20 天（驗證期）插入 10 筆全部獲利
        for _ in range(10):
            _insert_matched_trade(opt_db, "0050", 100, 120, days_ago=5)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        # 訓練期 metrics（用 60 天窗口）
        metrics = StrategyMetricsEngine(opt_db).compute(window_days=60)
        adjustments = OptimizationGateway(opt_db).on_eod(metrics)

        trailing_adjs = [a for a in adjustments if a["param_key"] == "trailing_pct"]
        # 驗證期勝率恢復，不應發生調整
        assert trailing_adjs == []

    def test_adjustment_proceeds_when_validation_confirms(self, opt_db):
        """訓練期與驗證期都是低勝率 → walk-forward 通過，調整生效。"""
        self._setup_gateway(opt_db)

        # 訓練期 + 驗證期都是虧損
        for _ in range(30):
            _insert_matched_trade(opt_db, "2330", 100, 90, days_ago=5)

        from openclaw.strategy_optimizer import OptimizationGateway, StrategyMetricsEngine
        metrics = StrategyMetricsEngine(opt_db).compute()
        adjustments = OptimizationGateway(opt_db).on_eod(metrics)

        trailing_adjs = [a for a in adjustments if a["param_key"] == "trailing_pct"]
        assert len(trailing_adjs) == 1
        assert trailing_adjs[0]["new_value"] > trailing_adjs[0]["old_value"]


class TestReflectionAgent:
    def test_reflect_returns_list(self, opt_db, monkeypatch):
        """reflect_weekly 回傳 list（即使 LLM 未設定也不崩潰）"""
        import sys, types
        fake_minimax = types.ModuleType("openclaw.llm_minimax")
        fake_minimax.minimax_call = lambda model, prompt: {
            "_raw_response": '{"direction":"neutral","rationale":"test","proposals":[]}',
        }
        sys.modules["openclaw.llm_minimax"] = fake_minimax

        from openclaw.strategy_optimizer import ReflectionAgent
        agent = ReflectionAgent(opt_db)
        result = agent.reflect_weekly()
        assert isinstance(result, list)

    def test_reflect_no_crash_on_llm_error(self, opt_db, monkeypatch):
        """LLM 拋出例外時 reflect_weekly 回傳空 list 不崩潰"""
        import sys, types
        fake_minimax = types.ModuleType("openclaw.llm_minimax")
        def bad_call(model, prompt): raise RuntimeError("MiniMax timeout")
        fake_minimax.minimax_call = bad_call
        sys.modules["openclaw.llm_minimax"] = fake_minimax

        from openclaw.strategy_optimizer import ReflectionAgent
        result = ReflectionAgent(opt_db).reflect_weekly()
        assert result == []
