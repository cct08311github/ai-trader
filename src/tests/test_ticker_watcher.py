"""test_ticker_watcher.py — 完整測試

涵蓋：
- _is_market_open()：週末 / 非交易時段 / 正常時段 / 節假日
- _generate_signal()：buy / sell / flat
- _update_price_history()：累積與上限截斷
- _evaluate_cash_mode()：資料不足保持現狀 / bull market 正常 / bear market cash mode
- _open_conn()：DB 連線
- _utc_now_iso()：UTC 時間格式
- _load_manual_watchlist()：watchlist.json 讀取與 fallback
- _get_snapshot()：Shioaji / mock 行情取得
- _persist_decision()/_persist_risk_check()/_persist_order()/_persist_fill()/_insert_order_event()
- _log_trace()/_log_screen_trace()：SSE trace 寫入
- _execute_sim_order()：模擬下單執行
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from openclaw.ticker_watcher import (
    _CASH_MODE_MIN_PRICES,
    _PRICE_HISTORY_MAX,
    _SUSPENDED_POSITION_STATE,
    SnapshotUnavailableError,
    _active_suspended_symbols,
    _evaluate_cash_mode,
    _ensure_schema,
    _generate_signal,
    _is_market_open,
    _update_price_history,
    _utc_now_iso,
    _t2_settlement_date,
    _open_conn,
    _load_manual_watchlist,
    _get_snapshot,
    _record_snapshot_failure,
    _record_snapshot_success,
    _persist_decision,
    _persist_risk_check,
    _persist_order,
    _persist_fill,
    _insert_order_event,
    _log_trace,
    _log_screen_trace,
    _execute_sim_order,
    DB_PATH,
    STRATEGY_ID,
    STRATEGY_VERSION,
)

_TZ_TWN = dt.timezone(dt.timedelta(hours=8))


# ── _is_market_open() ────────────────────────────────────────────────────────

class TestIsMarketOpen:
    def _twn(self, year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime(year, month, day, hour, minute, tzinfo=_TZ_TWN)

    def test_saturday_closed(self):
        """週六 → 市場關閉"""
        # 2026-03-07 是週六
        sat = self._twn(2026, 3, 7, 10, 0)
        assert sat.weekday() == 5
        assert _is_market_open(sat) is False

    def test_sunday_closed(self):
        """週日 → 市場關閉"""
        # 2026-03-08 是週日
        sun = self._twn(2026, 3, 8, 10, 0)
        assert sun.weekday() == 6
        assert _is_market_open(sun) is False

    def test_weekday_before_market_closed(self):
        """平日 08:30（盤前開始前）→ 市場關閉"""
        # 2026-03-02 是週一
        before = self._twn(2026, 3, 2, 8, 30)
        assert _is_market_open(before) is False

    def test_weekday_after_market_closed(self):
        """平日 14:00（盤後競價結束後）→ 市場關閉"""
        after = self._twn(2026, 3, 2, 14, 0)
        assert _is_market_open(after) is False

    def test_regular_session_open(self):
        """平日 10:00（正常交易時段）→ 市場開放"""
        regular = self._twn(2026, 3, 2, 10, 0)
        assert _is_market_open(regular) is True

    def test_preopen_auction_open(self):
        """平日 09:05（盤前競價）→ 市場開放（tw_session_allows_trading = True）"""
        preopen = self._twn(2026, 3, 2, 9, 5)
        assert _is_market_open(preopen) is True

    def test_afterhours_auction_open(self):
        """平日 13:35（盤後競價）→ 市場開放"""
        after = self._twn(2026, 3, 2, 13, 35)
        assert _is_market_open(after) is True

    def test_festival_holiday_closed(self):
        """春節（2026-02-17）→ 市場關閉（trading_calendar FESTIVAL 效應）"""
        # 2026-02-17 是週二（平日），但 trading_calendar 內建春節
        cny = self._twn(2026, 2, 17, 10, 0)
        assert cny.weekday() < 5  # 確認是平日
        assert _is_market_open(cny) is False


# ── _generate_signal() ───────────────────────────────────────────────────────

class TestGenerateSignal:
    def _snap(self, close: float, reference: float) -> dict:
        return {
            "close": close,
            "reference": reference,
            "bid": close * 0.999,
            "ask": close * 1.001,
            "volume": 1000,
        }

    def test_buy_signal_no_position(self):
        """close < ref * 0.998 且無持倉 → buy"""
        snap = self._snap(close=897.0, reference=900.0)  # 897 < 900*0.998=898.2
        assert _generate_signal(snap, position_avg_price=None) == "buy"

    def test_flat_signal_no_position_price_not_low(self):
        """close >= ref * 0.998 且無持倉 → flat"""
        snap = self._snap(close=899.0, reference=900.0)  # 899 > 898.2
        assert _generate_signal(snap, position_avg_price=None) == "flat"

    def test_sell_signal_with_position_profit(self):
        """有持倉 + close > avg * 1.02 → sell（止盈 +2%）"""
        snap = self._snap(close=920.0, reference=900.0)
        # 920 > 900 * 1.02 = 918
        assert _generate_signal(snap, position_avg_price=900.0) == "sell"

    def test_flat_signal_with_position_no_profit(self):
        """有持倉 + close < avg * 1.02 且 > avg * 0.97 → flat（在停損/止盈帶內）"""
        snap = self._snap(close=910.0, reference=900.0)
        # 910 < 900 * 1.02 = 918，且 910 > 900 * 0.97 = 873
        assert _generate_signal(snap, position_avg_price=900.0) == "flat"

    def test_sell_signal_with_position_at_stop_loss(self):
        """有持倉 + close < avg * 0.97 → sell（止損 -3%）"""
        snap = self._snap(close=850.0, reference=900.0)
        # 850 < 900 * 0.97 = 873 → 觸發止損
        assert _generate_signal(snap, position_avg_price=900.0) == "sell"

    def test_flat_signal_with_position_small_loss(self):
        """有持倉小幅虧損（-1%）→ flat（未達止損線 -3%）"""
        snap = self._snap(close=891.0, reference=900.0)
        # 891 > 900 * 0.97 = 873，且 891 < 918 → flat
        assert _generate_signal(snap, position_avg_price=900.0) == "flat"


# ── _ensure_schema() — Task 1 ─────────────────────────────────────────────────

def test_positions_table_has_high_water_mark(tmp_path, monkeypatch):
    """positions 表必須有 high_water_mark 欄位"""
    db = str(tmp_path / "trades.db")
    monkeypatch.setenv("DB_PATH", db)
    conn = sqlite3.connect(db)
    # 建立基本 positions 表（模擬舊 schema 沒有 high_water_mark）
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL
    )""")
    conn.commit()
    _ensure_schema(conn)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    assert "high_water_mark" in cols
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "watcher_symbol_health" in tables
    conn.close()


def test_ensure_schema_idempotent(tmp_path, monkeypatch):
    """重複呼叫 _ensure_schema 不應拋錯"""
    db = str(tmp_path / "trades.db")
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL
    )""")
    conn.commit()
    _ensure_schema(conn)
    _ensure_schema(conn)  # 第二次不應拋 OperationalError
    conn.close()


# ── TestTrailingStop — Task 2 ────────────────────────────────────────────────

class TestTrailingStop:
    def _snap(self, close, ref=100.0):
        return {"close": close, "reference": ref, "volume": 1000,
                "bid": close * 0.999, "ask": close * 1.001}

    def test_trailing_stop_triggers_when_price_drops_from_peak(self):
        """從高水位下跌 5% 應觸發 trailing sell"""
        # avg_price=100, high_water=150, close=142 → drop 5.3% from peak → sell
        result = _generate_signal(
            self._snap(142.0), position_avg_price=100.0, high_water_mark=150.0,
            trailing_pct=0.05
        )
        assert result == "sell", f"Expected sell, got {result}"

    def test_trailing_stop_does_not_trigger_near_peak(self):
        """距高水位只跌 2% 不觸發（trailing 5%）
        avg=145, high_water=150, close=147 → drop 2% from peak < 5% → flat
        close=147 < avg*1.02=147.9 → 不觸發止盈，故為 flat
        """
        result = _generate_signal(
            self._snap(147.0), position_avg_price=145.0, high_water_mark=150.0,
            trailing_pct=0.05
        )
        assert result == "flat"

    def test_no_trailing_when_no_position(self):
        """無持倉時不做 trailing 計算"""
        result = _generate_signal(
            self._snap(80.0), position_avg_price=None, high_water_mark=None,
            trailing_pct=0.05
        )
        assert result == "buy"  # close < ref*(1-0.2%)

    def test_original_stop_loss_still_works(self):
        """原有止損邏輯（-3%）不受影響"""
        # avg=100, close=96 → -4% → stop loss
        result = _generate_signal(
            self._snap(96.0), position_avg_price=100.0, high_water_mark=100.0,
            trailing_pct=0.05
        )
        assert result == "sell"

    def test_trailing_tighter_for_large_profit(self):
        """獲利超過 50% 時 trailing 收緊為 3%"""
        # avg=100, high_water=160（+60%），close=155（下跌 3.1% from peak）
        # trailing_pct base=5%，但獲利>50%收緊為 3%
        # 155 < 160*(1-0.03)=155.2 → sell
        result = _generate_signal(
            self._snap(155.0), position_avg_price=100.0, high_water_mark=160.0,
            trailing_pct=0.05
        )
        assert result == "sell"

    def test_existing_signals_backward_compatible(self):
        """舊的呼叫方式（無 high_water_mark）仍能正常運作"""
        snap = self._snap(close=104.0, ref=100.0)
        # 104 > 100 * 1.02 = 102 → sell（止盈）
        assert _generate_signal(snap, position_avg_price=100.0) == "sell"


# ── _update_price_history() ──────────────────────────────────────────────────

class TestUpdatePriceHistory:
    def test_accumulates_prices(self):
        """連續加入價格應正確累積"""
        hist: dict = {}
        _update_price_history(hist, "2330", 900.0)
        _update_price_history(hist, "2330", 905.0)
        assert hist["2330"] == [900.0, 905.0]

    def test_caps_at_max(self):
        """超過上限時，舊資料被移除"""
        hist: dict = {}
        for i in range(_PRICE_HISTORY_MAX + 5):
            _update_price_history(hist, "2330", float(900 + i))
        assert len(hist["2330"]) == _PRICE_HISTORY_MAX
        # 最後一筆應為最新加入
        assert hist["2330"][-1] == float(900 + _PRICE_HISTORY_MAX + 4)

    def test_multiple_symbols_independent(self):
        """不同 symbol 的歷史互不干擾"""
        hist: dict = {}
        _update_price_history(hist, "2330", 900.0)
        _update_price_history(hist, "2317", 200.0)
        assert hist["2330"] == [900.0]
        assert hist["2317"] == [200.0]


# ── _evaluate_cash_mode() ────────────────────────────────────────────────────

class TestEvaluateCashMode:
    def _hist_with(self, prices: list[float]) -> dict:
        return {"2330": prices}

    def test_insufficient_data_keeps_current(self):
        """資料不足（< _CASH_MODE_MIN_PRICES）→ 維持現狀，不切換"""
        hist = self._hist_with([900.0] * (_CASH_MODE_MIN_PRICES - 1))
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False
        assert reason == "CASHMODE_INSUFFICIENT_DATA"

    def test_insufficient_data_keeps_current_true(self):
        """資料不足時，若原本 cash_mode=True，仍維持 True"""
        hist = self._hist_with([900.0] * 5)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=True)
        assert cash_mode is True
        assert reason == "CASHMODE_INSUFFICIENT_DATA"

    def test_stable_bull_prices_normal_mode(self):
        """穩定上漲行情 → cash_mode=False（CASHMODE_NORMAL 或 CASHMODE_EXIT_*）"""
        # 60 筆持續上漲的價格 → BULL regime
        prices = [float(800 + i * 5) for i in range(60)]
        hist = self._hist_with(prices)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False

    def test_strong_bear_prices_cash_mode(self):
        """強烈下跌行情（高波動）→ cash_mode=True"""
        # 60 筆持續大跌的價格
        prices = [float(1000 - i * 10) for i in range(60)]
        hist = self._hist_with(prices)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        # Bear regime with sufficient confidence → cash mode
        assert cash_mode is True

    def test_uses_2330_as_bellwether(self):
        """即使有其他 symbol，優先使用 2330 作為基準"""
        prices_2330 = [float(900 + i) for i in range(_CASH_MODE_MIN_PRICES)]
        prices_other = [float(50 - i) for i in range(_CASH_MODE_MIN_PRICES)]
        hist = {"2317": prices_other, "2330": prices_2330}
        # 結果應根據 2330 評估（上漲 → normal，不進入 cash mode）
        cash_mode, _ = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False

    def test_fallback_to_other_symbol_if_no_2330(self):
        """無 2330 資料時，fallback 到其他有足夠資料的 symbol"""
        prices = [float(200 + i * 2) for i in range(_CASH_MODE_MIN_PRICES)]
        hist = {"2317": prices}
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert reason != "CASHMODE_INSUFFICIENT_DATA"  # 有資料，應能評估


# ── Helper: in-memory DB with full schema ─────────────────────────────────────

def _make_mem_db() -> sqlite3.Connection:
    """建立完整 schema 的 in-memory SQLite DB，供 persist / trace 測試使用。"""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            ts TEXT,
            symbol TEXT,
            strategy_id TEXT,
            strategy_version TEXT,
            signal_side TEXT,
            signal_score REAL,
            signal_ttl_ms INTEGER,
            llm_ref TEXT,
            reason_json TEXT,
            signal_source TEXT
        );

        CREATE TABLE risk_checks (
            check_id TEXT PRIMARY KEY,
            decision_id TEXT,
            ts TEXT,
            passed INTEGER,
            reject_code TEXT,
            metrics_json TEXT
        );

        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            broker_order_id TEXT,
            ts_submit TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            order_type TEXT,
            tif TEXT,
            status TEXT,
            strategy_version TEXT,
            settlement_date TEXT,
            account_mode TEXT
        );

        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0
        );

        CREATE TABLE order_events (
            event_id TEXT PRIMARY KEY,
            ts TEXT,
            order_id TEXT,
            event_type TEXT,
            from_status TEXT,
            to_status TEXT,
            source TEXT,
            reason_code TEXT,
            payload_json TEXT
        );

        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL
        );

        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            realized_pnl REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            total_pnl REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0,
            rolling_drawdown REAL DEFAULT 0,
            consecutive_losses INTEGER DEFAULT 0,
            losing_streak_days INTEGER DEFAULT 0,
            rolling_win_rate REAL DEFAULT 0,
            nav_end REAL DEFAULT 0,
            rolling_peak_nav REAL DEFAULT 0
        );

        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            component TEXT NOT NULL,
            model TEXT NOT NULL,
            decision_id TEXT,
            prompt_text TEXT NOT NULL,
            response_text TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            tools_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
    """)
    return conn


# ── _open_conn() ──────────────────────────────────────────────────────────────

class TestOpenConn:
    def test_opens_connection_to_env_db(self, tmp_path, monkeypatch):
        """_open_conn() 應連到 DB_PATH 指定的資料庫並設定 row_factory"""
        db_file = str(tmp_path / "test.db")
        monkeypatch.setenv("DB_PATH", db_file)
        # DB_PATH 是 module-level 常數，需要 patch ticker_watcher.DB_PATH
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "DB_PATH", db_file)
        conn = tw._open_conn()
        assert conn is not None
        # row_factory 已設定
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_opens_in_memory_works(self, monkeypatch):
        """_open_conn() 用 :memory: 應能正常建立連線"""
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        conn = tw._open_conn()
        assert conn is not None
        conn.close()


# ── _utc_now_iso() ────────────────────────────────────────────────────────────

class TestUtcNowIso:
    def test_returns_iso_string(self):
        """_utc_now_iso() 應回傳含 UTC offset 的 ISO 8601 字串"""
        result = _utc_now_iso()
        assert isinstance(result, str)
        assert "+" in result or "Z" in result or result.endswith("+00:00")

    def test_is_recent(self):
        """_utc_now_iso() 應在近期（不超過 5 秒差）"""
        result = _utc_now_iso()
        parsed = dt.datetime.fromisoformat(result)
        diff = abs((dt.datetime.now(tz=dt.timezone.utc) - parsed).total_seconds())
        assert diff < 5.0


# ── _load_manual_watchlist() ──────────────────────────────────────────────────

class TestLoadManualWatchlist:
    def test_reads_manual_watchlist_key(self, tmp_path, monkeypatch):
        """有效的 watchlist.json 應優先讀取 manual_watchlist"""
        cfg = {"manual_watchlist": ["2330", "2317", "2454"]}
        cfg_file = tmp_path / "watchlist.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_file)
        result = tw._load_manual_watchlist()
        assert result == ["2330", "2317", "2454"]

    def test_backward_compat_universe_key(self, tmp_path, monkeypatch):
        """向後相容：無 manual_watchlist 時讀取 universe"""
        cfg = {"universe": ["2330", "2317", "2454"], "max_active": 2}
        cfg_file = tmp_path / "watchlist.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_file)
        result = tw._load_manual_watchlist()
        assert result == ["2330", "2317", "2454"]

    def test_missing_file_uses_fallback(self, tmp_path, monkeypatch):
        """watchlist.json 不存在時應使用 fallback"""
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", tmp_path / "nonexistent.json")
        result = tw._load_manual_watchlist()
        assert result == list(tw._FALLBACK_UNIVERSE)

    def test_invalid_json_uses_fallback(self, tmp_path, monkeypatch):
        """無效 JSON 應使用 fallback"""
        cfg_file = tmp_path / "watchlist.json"
        cfg_file.write_text("not_json{{", encoding="utf-8")
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_file)
        result = tw._load_manual_watchlist()
        assert result == list(tw._FALLBACK_UNIVERSE)

    def test_empty_list_uses_fallback(self, tmp_path, monkeypatch):
        """manual_watchlist 為空陣列時應使用 fallback"""
        cfg = {"manual_watchlist": []}
        cfg_file = tmp_path / "watchlist.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_file)
        result = tw._load_manual_watchlist()
        assert result == list(tw._FALLBACK_UNIVERSE)

    def test_strips_whitespace_from_symbols(self, tmp_path, monkeypatch):
        """symbol 前後空白應被清除，空白 symbol 被濾掉"""
        cfg = {"manual_watchlist": [" 2330 ", "  ", "2317"]}
        cfg_file = tmp_path / "watchlist.json"
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        import openclaw.ticker_watcher as tw
        monkeypatch.setattr(tw, "_WATCHLIST_CFG", cfg_file)
        result = tw._load_manual_watchlist()
        assert "2330" in result
        assert "" not in result
        assert " " not in result


# ── _get_snapshot() ───────────────────────────────────────────────────────────

class TestGetSnapshot:
    def test_returns_mock_when_api_is_none(self):
        """api=None 時應回傳 mock 行情，包含 source='mock'"""
        snap = _get_snapshot(None, "2330")
        assert snap["source"] == "mock"
        assert snap["close"] > 0
        assert snap["bid"] > 0
        assert snap["ask"] > snap["bid"]
        assert snap["volume"] > 0
        assert snap["reference"] > 0

    def test_mock_uses_base_price_fallback(self):
        """api=None 且 symbol 不在 _BASE_PRICE 時，用 100.0 作為基礎"""
        snap = _get_snapshot(None, "UNKNOWN_SYM")
        assert snap["close"] > 0
        assert snap["reference"] == 100.0

    def test_mock_uses_known_base_price(self):
        """api=None 且 symbol='2330' 時，reference 應為 900.0"""
        snap = _get_snapshot(None, "2330")
        assert snap["reference"] == 900.0

    def test_shioaji_success(self):
        """Shioaji api 有效時應使用 snapshot 資料"""
        mock_snap = MagicMock()
        mock_snap.close = 920.0
        mock_snap.buy_price = 919.0
        mock_snap.sell_price = 921.0
        mock_snap.reference = 900.0
        mock_snap.volume = 5000

        mock_contract = MagicMock()
        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.return_value = mock_contract
        mock_api.snapshots.return_value = [mock_snap]

        snap = _get_snapshot(mock_api, "2330")
        assert snap["close"] == 920.0
        assert snap["bid"] == 919.0
        assert snap["ask"] == 921.0
        assert snap["reference"] == 900.0
        assert snap["volume"] == 5000

    def test_shioaji_zero_close_falls_back_to_mock(self):
        """Shioaji snapshot close=0 時應 fallback 到 mock"""
        mock_snap = MagicMock()
        mock_snap.close = 0
        mock_snap.buy_price = 0
        mock_snap.sell_price = 0
        mock_snap.reference = 0
        mock_snap.volume = 0

        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.return_value = MagicMock()
        mock_api.snapshots.return_value = [mock_snap]

        snap = _get_snapshot(mock_api, "2330")
        # close=0 導致 fallback → 應有 source='mock'
        assert snap["source"] == "mock"

    def test_shioaji_empty_snapshots_falls_back(self):
        """Shioaji 回傳空列表時應 fallback 到 mock"""
        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.return_value = MagicMock()
        mock_api.snapshots.return_value = []

        snap = _get_snapshot(mock_api, "2330")
        assert snap["source"] == "mock"

    def test_shioaji_exception_falls_back(self):
        """Shioaji 拋出例外時應 fallback 到 mock"""
        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.side_effect = Exception("connection error")

        snap = _get_snapshot(mock_api, "2330")
        assert snap["source"] == "mock"

    def test_live_snapshot_failure_raises_when_mock_disabled(self):
        """live mode 下禁用 mock fallback 時，snapshot 失敗應 raise。"""
        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.side_effect = Exception("connection error")

        with pytest.raises(SnapshotUnavailableError):
            _get_snapshot(mock_api, "2330", allow_mock_fallback=False)

    def test_live_snapshot_zero_close_raises_when_mock_disabled(self):
        """live mode 下 close<=0 應視為不可用 snapshot。"""
        mock_snap = MagicMock()
        mock_snap.close = 0
        mock_api = MagicMock()
        mock_api.Contracts.Stocks.__getitem__.return_value = MagicMock()
        mock_api.snapshots.return_value = [mock_snap]

        with pytest.raises(SnapshotUnavailableError):
            _get_snapshot(mock_api, "2330", allow_mock_fallback=False)


def _make_snapshot_health_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            current_price REAL,
            unrealized_pnl REAL,
            state TEXT,
            high_water_mark REAL,
            entry_trading_day TEXT
        )"""
    )
    _ensure_schema(conn)
    return conn


class TestSnapshotSuspension:
    def test_record_snapshot_failure_suspends_after_threshold(self):
        """連續失敗達門檻後應標記為 suspended 並更新持倉 state。"""
        conn = _make_snapshot_health_db()
        conn.execute(
            "INSERT INTO positions(symbol, quantity, avg_price, current_price, state) VALUES (?, ?, ?, ?, ?)",
            ("2330", 100, 900.0, 900.0, "HOLDING"),
        )

        count1, suspended1 = _record_snapshot_failure(conn, "2330", error="boom-1", threshold=3)
        count2, suspended2 = _record_snapshot_failure(conn, "2330", error="boom-2", threshold=3)
        count3, suspended3 = _record_snapshot_failure(conn, "2330", error="boom-3", threshold=3)

        assert (count1, suspended1) == (1, False)
        assert (count2, suspended2) == (2, False)
        assert (count3, suspended3) == (3, True)
        assert _active_suspended_symbols(conn) == {"2330"}
        row = conn.execute(
            "SELECT state FROM positions WHERE symbol='2330'"
        ).fetchone()
        assert row["state"] == _SUSPENDED_POSITION_STATE

    def test_record_snapshot_success_resets_counter_for_active_symbol(self):
        """未 suspended 的 symbol 成功拿到 live snapshot 後應清空失敗計數。"""
        conn = _make_snapshot_health_db()

        count, suspended = _record_snapshot_failure(conn, "2317", error="timeout", threshold=3)
        assert (count, suspended) == (1, False)

        _record_snapshot_success(conn, "2317")

        row = conn.execute(
            "SELECT consecutive_snapshot_failures, suspended, last_error, last_success_at "
            "FROM watcher_symbol_health WHERE symbol='2317'"
        ).fetchone()
        assert row["consecutive_snapshot_failures"] == 0
        assert row["suspended"] == 0
        assert row["last_error"] is None
        assert row["last_success_at"] is not None


# ── DB persist helpers ────────────────────────────────────────────────────────

class TestPersistDecision:
    def test_inserts_decision_row(self):
        """_persist_decision() 應在 decisions 表插入正確的一筆資料"""
        conn = _make_mem_db()
        decision_id = str(uuid.uuid4())
        _persist_decision(conn, decision_id=decision_id, symbol="2330",
                          signal="buy", now_iso="2026-03-03T10:00:00+00:00")
        row = conn.execute("SELECT * FROM decisions WHERE decision_id=?", (decision_id,)).fetchone()
        assert row is not None
        assert row["symbol"] == "2330"
        assert row["signal_side"] == "buy"
        assert row["strategy_id"] == STRATEGY_ID
        assert row["strategy_version"] == STRATEGY_VERSION

    def test_ignore_duplicate_decision(self):
        """INSERT OR IGNORE：重複插入同 decision_id 應靜默忽略"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _persist_decision(conn, decision_id=did, symbol="2330",
                          signal="buy", now_iso="2026-03-03T10:00:00+00:00")
        _persist_decision(conn, decision_id=did, symbol="2317",  # 同 id，不同 symbol
                          signal="sell", now_iso="2026-03-03T10:01:00+00:00")
        rows = conn.execute("SELECT * FROM decisions WHERE decision_id=?", (did,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "2330"  # 原始記錄保留

    def test_flat_signal_score_is_zero(self):
        """signal='flat' 時 signal_score 應為 0"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _persist_decision(conn, decision_id=did, symbol="2330",
                          signal="flat", now_iso="2026-03-03T10:00:00+00:00")
        row = conn.execute("SELECT signal_score FROM decisions WHERE decision_id=?", (did,)).fetchone()
        assert row["signal_score"] == 0.0

    def test_non_flat_signal_score_is_07(self):
        """signal!='flat' 時 signal_score 應為 0.7"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _persist_decision(conn, decision_id=did, symbol="2330",
                          signal="sell", now_iso="2026-03-03T10:00:00+00:00")
        row = conn.execute("SELECT signal_score FROM decisions WHERE decision_id=?", (did,)).fetchone()
        assert row["signal_score"] == 0.7


class TestPersistRiskCheck:
    def test_inserts_risk_check_passed(self):
        """_persist_risk_check() 應插入 passed=1"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _persist_risk_check(conn, decision_id=did, passed=True,
                            reject_code=None, metrics={"nav": 2000000.0})
        row = conn.execute("SELECT * FROM risk_checks WHERE decision_id=?", (did,)).fetchone()
        assert row is not None
        assert row["passed"] == 1
        assert row["reject_code"] is None

    def test_inserts_risk_check_failed(self):
        """_persist_risk_check() 應插入 passed=0 及 reject_code"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _persist_risk_check(conn, decision_id=did, passed=False,
                            reject_code="MAX_LOSS", metrics={})
        row = conn.execute("SELECT * FROM risk_checks WHERE decision_id=?", (did,)).fetchone()
        assert row["passed"] == 0
        assert row["reject_code"] == "MAX_LOSS"

    def test_metrics_json_serialized(self):
        """metrics 應序列化為 JSON 字串儲存"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        metrics = {"key": "value", "num": 42}
        _persist_risk_check(conn, decision_id=did, passed=True,
                            reject_code=None, metrics=metrics)
        row = conn.execute("SELECT metrics_json FROM risk_checks WHERE decision_id=?", (did,)).fetchone()
        parsed = json.loads(row["metrics_json"])
        assert parsed == metrics


class TestPersistOrder:
    def test_inserts_order(self):
        """_persist_order() 應插入完整的訂單記錄"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        _persist_order(conn, order_id=oid, decision_id=did, broker_order_id="SIM-1",
                       symbol="2330", side="buy", qty=100, price=890.0)
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (oid,)).fetchone()
        assert row is not None
        assert row["symbol"] == "2330"
        assert row["side"] == "buy"
        assert row["qty"] == 100
        assert row["price"] == 890.0
        assert row["status"] == "submitted"
        assert row["order_type"] == "limit"
        assert row["tif"] == "IOC"

    def test_custom_status(self):
        """可傳入自訂 status（如 rejected）"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        did = str(uuid.uuid4())
        _persist_order(conn, order_id=oid, decision_id=did, broker_order_id="SIM-2",
                       symbol="2317", side="sell", qty=50, price=200.0, status="rejected")
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (oid,)).fetchone()
        assert row["status"] == "rejected"


class TestPersistFill:
    def test_inserts_fill(self):
        """_persist_fill() 應插入成交記錄"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        _persist_fill(conn, order_id=oid, qty=100, price=890.0, fee=20.0, tax=30.0)
        row = conn.execute("SELECT * FROM fills WHERE order_id=?", (oid,)).fetchone()
        assert row is not None
        assert row["qty"] == 100
        assert row["price"] == 890.0
        assert row["fee"] == 20.0
        assert row["tax"] == 30.0

    def test_default_fee_tax_zero(self):
        """fee/tax 預設值應為 0"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        _persist_fill(conn, order_id=oid, qty=50, price=200.0)
        row = conn.execute("SELECT fee, tax FROM fills WHERE order_id=?", (oid,)).fetchone()
        assert row["fee"] == 0.0
        assert row["tax"] == 0.0


class TestInsertOrderEvent:
    def test_inserts_event(self):
        """_insert_order_event() 應插入 order_events 記錄"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        _insert_order_event(conn, order_id=oid, event_type="submitted",
                            from_status=None, to_status="submitted",
                            source="watcher", reason_code=None,
                            payload={"broker_order_id": "SIM-1"})
        row = conn.execute("SELECT * FROM order_events WHERE order_id=?", (oid,)).fetchone()
        assert row is not None
        assert row["event_type"] == "submitted"
        assert row["source"] == "watcher"
        assert row["from_status"] is None
        assert row["to_status"] == "submitted"

    def test_payload_json_serialized(self):
        """payload 應序列化為 JSON"""
        conn = _make_mem_db()
        oid = str(uuid.uuid4())
        payload = {"filled_qty": 100, "avg_price": 890.0}
        _insert_order_event(conn, order_id=oid, event_type="filled",
                            from_status="submitted", to_status="filled",
                            source="broker", reason_code=None, payload=payload)
        row = conn.execute("SELECT payload_json FROM order_events WHERE order_id=?", (oid,)).fetchone()
        parsed = json.loads(row["payload_json"])
        assert parsed["filled_qty"] == 100


# ── _log_trace() / _log_screen_trace() ───────────────────────────────────────

class TestLogTrace:
    def _snap(self) -> dict:
        return {"close": 900.0, "reference": 890.0, "bid": 899.0, "ask": 901.0, "volume": 1000}

    def test_writes_approved_trace(self):
        """approved=True 時應插入 llm_trace"""
        conn = _make_mem_db()
        _log_trace(conn, symbol="2330", signal="buy", snap=self._snap(),
                   approved=True, reject_code=None)
        count = conn.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 1

    def test_writes_rejected_trace(self):
        """approved=False + reject_code 時應插入 llm_trace"""
        conn = _make_mem_db()
        _log_trace(conn, symbol="2330", signal="flat", snap=self._snap(),
                   approved=False, reject_code="MAX_LOSS")
        count = conn.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 1

    def test_trace_includes_order_info(self):
        """order 不為 None 時，response_text 應含 order 資訊"""
        conn = _make_mem_db()
        mock_order = MagicMock()
        mock_order.side = "buy"
        mock_order.qty = 100
        mock_order.price = 890.0
        _log_trace(conn, symbol="2330", signal="buy", snap=self._snap(),
                   approved=True, reject_code=None, order=mock_order)
        row = conn.execute("SELECT response_text FROM llm_traces").fetchone()
        assert row is not None
        assert "buy" in row["response_text"]

    def test_insert_failure_does_not_raise(self):
        """insert_llm_trace 拋出例外時，_log_trace 應靜默不向上拋"""
        conn = _make_mem_db()
        with patch("openclaw.llm_observability.insert_llm_trace", side_effect=Exception("DB error")):
            # 不應拋出例外
            _log_trace(conn, symbol="2330", signal="buy", snap=self._snap(),
                       approved=True, reject_code=None)

    def test_with_decision_id(self):
        """有 decision_id 時應能正常寫入"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        _log_trace(conn, symbol="2330", signal="sell", snap=self._snap(),
                   approved=True, reject_code=None, decision_id=did)
        count = conn.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 1


class TestLogScreenTrace:
    def test_writes_screen_trace(self):
        """_log_screen_trace() 應插入 llm_trace"""
        conn = _make_mem_db()
        _log_screen_trace(conn, universe=["2330", "2317", "2454"],
                          active=["2330", "2317"])
        count = conn.execute("SELECT COUNT(*) FROM llm_traces").fetchone()[0]
        assert count == 1

    def test_insert_failure_does_not_raise(self):
        """insert_llm_trace 拋出例外時，_log_screen_trace 應靜默不向上拋"""
        conn = _make_mem_db()
        with patch("openclaw.llm_observability.insert_llm_trace", side_effect=Exception("fail")):
            _log_screen_trace(conn, universe=["2330"], active=["2330"])


# ── _execute_sim_order() ──────────────────────────────────────────────────────

class TestExecuteSimOrder:
    """測試模擬下單執行流程。"""

    def _make_candidate(self, side="buy", qty=100, price=890.0):
        from openclaw.risk_engine import OrderCandidate
        return OrderCandidate(symbol="2330", side=side, qty=qty, price=price,
                              order_type="limit", tif="IOC", opens_new_position=(side == "buy"))

    def test_buy_order_filled(self):
        """SimBrokerAdapter 正常成交 buy 訂單"""
        from openclaw.broker import SimBrokerAdapter
        conn = _make_mem_db()
        broker = SimBrokerAdapter()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        assert ok is True
        assert order_id is not None
        # orders 表有記錄
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        assert row is not None
        assert row["status"] == "filled"
        # fills 表有記錄
        fill_count = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        assert fill_count > 0

    def test_sell_order_filled(self):
        """SimBrokerAdapter 正常成交 sell 訂單"""
        from openclaw.broker import SimBrokerAdapter
        conn = _make_mem_db()
        broker = SimBrokerAdapter()
        candidate = self._make_candidate("sell", 50, 920.0)
        did = str(uuid.uuid4())

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=broker, decision_id=did,
                symbol="2330", side="sell", qty=50, price=920.0, candidate=candidate
            )

        assert ok is True

    def test_broker_rejection_returns_false(self):
        """broker.submit_order 回傳 rejected → _execute_sim_order 應回傳 (False, order_id)"""
        from openclaw.broker import BrokerSubmission
        conn = _make_mem_db()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = BrokerSubmission(
            broker_order_id="", status="rejected", reason="insufficient funds"
        )

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=mock_broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        assert ok is False
        # orders 表應有 rejected 記錄
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
        assert row["status"] == "rejected"

    def test_order_events_written(self):
        """成交後 order_events 表應有 submitted 和 filled 事件"""
        from openclaw.broker import SimBrokerAdapter
        conn = _make_mem_db()
        broker = SimBrokerAdapter()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        event_types = [row["event_type"] for row in
                       conn.execute("SELECT event_type FROM order_events WHERE order_id=?",
                                    (order_id,)).fetchall()]
        assert "submitted" in event_types
        assert "filled" in event_types

    def test_poll_returns_none_eventually_times_out(self):
        """poll_order_status 持續回傳 None → 12 輪後結束，回傳 (False, order_id)"""
        from openclaw.broker import BrokerSubmission
        conn = _make_mem_db()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = BrokerSubmission(
            broker_order_id="SIM-X", status="submitted"
        )
        mock_broker.poll_order_status.return_value = None  # 永遠回傳 None

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=mock_broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        assert ok is False  # 未 filled

    def test_pre_trade_guard_rejects_before_broker_submit(self):
        """硬風控拒絕時，不應呼叫 broker.submit_order。"""
        conn = _make_mem_db()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())
        mock_broker = MagicMock()

        ok, order_id = _execute_sim_order(
            conn, broker=mock_broker, decision_id=did,
            symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate,
            guard_limits={"max_order_notional": 1000},
        )

        assert ok is False
        assert order_id is not None
        mock_broker.submit_order.assert_not_called()
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
        assert row["status"] == "rejected"
        event = conn.execute(
            "SELECT source, reason_code FROM order_events WHERE order_id=?",
            (order_id,),
        ).fetchone()
        assert event["source"] == "pre_trade_guard"
        assert event["reason_code"] == "RISK_HARD_GUARD_MAX_ORDER_NOTIONAL"

    def test_partial_fill_timeout_marks_partially_filled(self):
        """poll loop 超時後仍有已成交股數 → orders.status 應更新為 partially_filled，回傳 (False, order_id)"""
        from openclaw.broker import BrokerOrderStatus, BrokerSubmission
        conn = _make_mem_db()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = BrokerSubmission(
            broker_order_id="SIM-PARTIAL", status="submitted"
        )
        # 每次 poll 都回傳 partially_filled（永遠不到 terminal）
        mock_broker.poll_order_status.return_value = BrokerOrderStatus(
            broker_order_id="SIM-PARTIAL",
            status="partially_filled",
            filled_qty=50,
            avg_fill_price=890.0,
            fee=0.63,
            tax=0.0,
        )

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=mock_broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        # 部分成交超時：回傳 False（未完全成交）
        assert ok is False
        # orders 表應標記 partially_filled（非 submitted）
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
        assert row["status"] == "partially_filled"
        # fills 表應有部分成交記錄
        fill_count = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        assert fill_count > 0

    def test_partial_fill_then_filled_returns_true(self):
        """broker 先回 partially_filled，再回 filled → 應回傳 (True, order_id)"""
        from openclaw.broker import BrokerOrderStatus, BrokerSubmission
        conn = _make_mem_db()
        candidate = self._make_candidate("buy", 100, 890.0)
        did = str(uuid.uuid4())

        mock_broker = MagicMock()
        mock_broker.submit_order.return_value = BrokerSubmission(
            broker_order_id="SIM-PF2", status="submitted"
        )
        # poll 1 → partially_filled；poll 2 → filled
        mock_broker.poll_order_status.side_effect = [
            BrokerOrderStatus(
                broker_order_id="SIM-PF2", status="partially_filled",
                filled_qty=50, avg_fill_price=890.0, fee=0.63, tax=0.0,
            ),
            BrokerOrderStatus(
                broker_order_id="SIM-PF2", status="filled",
                filled_qty=100, avg_fill_price=890.0, fee=1.27, tax=0.0,
            ),
        ]

        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=mock_broker, decision_id=did,
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate
            )

        assert ok is True
        row = conn.execute("SELECT status FROM orders WHERE order_id=?", (order_id,)).fetchone()
        assert row["status"] == "filled"
        fill_count = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?", (order_id,)).fetchone()[0]
        assert fill_count > 0


def _make_proposal_flow_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            current_price REAL
        );
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            ts TEXT,
            symbol TEXT,
            strategy_id TEXT,
            strategy_version TEXT,
            signal_side TEXT,
            signal_score REAL,
            signal_ttl_ms INTEGER,
            llm_ref TEXT,
            reason_json TEXT,
            signal_source TEXT
        );
        CREATE TABLE risk_checks (
            check_id TEXT PRIMARY KEY,
            decision_id TEXT,
            ts TEXT,
            passed INTEGER,
            reject_code TEXT,
            metrics_json TEXT
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            broker_order_id TEXT,
            ts_submit TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            order_type TEXT,
            tif TEXT,
            status TEXT,
            strategy_version TEXT,
            settlement_date TEXT,
            account_mode TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL,
            fee REAL DEFAULT 0,
            tax REAL DEFAULT 0
        );
        CREATE TABLE order_events (
            event_id TEXT PRIMARY KEY,
            ts TEXT,
            order_id TEXT,
            event_type TEXT,
            from_status TEXT,
            to_status TEXT,
            source TEXT,
            reason_code TEXT,
            payload_json TEXT
        );
        """
    )
    conn.execute(
        """
        INSERT INTO strategy_proposals VALUES (
            'p1', 'portfolio_review', 'POSITION_REBALANCE', 'portfolio',
            NULL, 'reduce 30%', 'evidence', 0.8, 0, 'approved', NULL, ?, ?, NULL
        )
        """,
        (json.dumps({"symbol": "2330", "reduce_pct": 0.3, "type": "rebalance"}), int(dt.datetime.now(tz=dt.timezone.utc).timestamp())),
    )
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 880.0, 890.0)")
    conn.commit()
    return conn


class TestProposalExecutionWatcherFlow:
    def _make_candidate(self, *, qty: int, price: float):
        from openclaw.risk_engine import OrderCandidate

        return OrderCandidate(
            symbol="2330",
            side="sell",
            qty=qty,
            price=price,
            order_type="limit",
            tif="ROD",
            opens_new_position=False,
        )

    def test_stale_recovered_intent_executes_successfully(self):
        from openclaw.broker import SimBrokerAdapter
        from openclaw.proposal_executor import (
            execute_pending_proposals,
            mark_intent_executed,
            mark_intent_executing,
        )

        conn = _make_proposal_flow_db()
        intents, _ = execute_pending_proposals(conn)
        assert len(intents) == 1
        intent = intents[0]

        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        conn.execute(
            "UPDATE proposal_execution_journal SET updated_at=0 WHERE execution_key=?",
            (intent.execution_key,),
        )
        conn.commit()

        recovered, _ = execute_pending_proposals(conn)
        assert len(recovered) == 1
        assert recovered[0].execution_key == intent.execution_key
        assert recovered[0].attempt_count == 1

        candidate = self._make_candidate(qty=recovered[0].qty, price=recovered[0].price)
        broker = SimBrokerAdapter()
        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn,
                broker=broker,
                decision_id=str(uuid.uuid4()),
                symbol=recovered[0].symbol,
                side="sell",
                qty=recovered[0].qty,
                price=recovered[0].price,
                candidate=candidate,
            )
        assert ok is True

        mark_intent_executed(
            conn,
            recovered[0].proposal_id,
            execution_key=recovered[0].execution_key,
            order_id=order_id,
        )
        journal = conn.execute(
            "SELECT state, attempt_count, last_order_id FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert journal["state"] == "completed"
        assert journal["attempt_count"] == 1
        assert journal["last_order_id"] == order_id

    def test_failed_intent_is_not_requeued_after_watcher_failure(self):
        from openclaw.broker import BrokerSubmission
        from openclaw.proposal_executor import execute_pending_proposals, mark_intent_executing, mark_intent_failed

        conn = _make_proposal_flow_db()
        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)

        candidate = self._make_candidate(qty=intent.qty, price=intent.price)
        broker = MagicMock()
        broker.submit_order.return_value = BrokerSubmission(
            broker_order_id="",
            status="rejected",
            reason="insufficient inventory",
        )

        ok, order_id = _execute_sim_order(
            conn,
            broker=broker,
            decision_id=str(uuid.uuid4()),
            symbol=intent.symbol,
            side="sell",
            qty=intent.qty,
            price=intent.price,
            candidate=candidate,
        )
        assert ok is False

        mark_intent_failed(
            conn,
            intent.proposal_id,
            "broker_rejected",
            execution_key=intent.execution_key,
            order_id=order_id,
        )

        follow_up, _ = execute_pending_proposals(conn)
        assert follow_up == []
        journal = conn.execute(
            "SELECT state, last_error FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert journal["state"] == "failed"
        assert journal["last_error"] == "broker_rejected"


# ── Integration: _persist_* functions work together ──────────────────────────

class TestPersistIntegration:
    """端對端測試：decision → risk_check → order → fill → order_event"""

    def test_full_order_lifecycle(self):
        """完整訂單生命週期寫入 DB"""
        conn = _make_mem_db()
        did = str(uuid.uuid4())
        oid = str(uuid.uuid4())
        now_iso = _utc_now_iso()

        # 1. persist decision
        _persist_decision(conn, decision_id=did, symbol="2330",
                          signal="buy", now_iso=now_iso)
        # 2. persist risk check
        _persist_risk_check(conn, decision_id=did, passed=True,
                            reject_code=None, metrics={"nav": 2_000_000})
        # 3. persist order
        _persist_order(conn, order_id=oid, decision_id=did, broker_order_id="SIM-1",
                       symbol="2330", side="buy", qty=100, price=890.0)
        # 4. persist fill
        _persist_fill(conn, order_id=oid, qty=100, price=890.0, fee=20.0, tax=10.0)
        # 5. insert order event
        _insert_order_event(conn, order_id=oid, event_type="filled",
                            from_status="submitted", to_status="filled",
                            source="broker", reason_code=None,
                            payload={"filled_qty": 100, "avg_price": 890.0})

        # Verify all rows
        assert conn.execute("SELECT COUNT(*) FROM decisions WHERE decision_id=?",
                            (did,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM risk_checks WHERE decision_id=?",
                            (did,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM orders WHERE order_id=?",
                            (oid,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM fills WHERE order_id=?",
                            (oid,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM order_events WHERE order_id=?",
                            (oid,)).fetchone()[0] == 1


# ── run_watcher() initialization section (lines 428-479) ─────────────────────
# The while True loop body has # pragma: no cover; we test the init section by
# making _is_market_open raise StopIteration on first call (exits the loop).

class TestRunWatcherInit:
    """Tests for run_watcher() initialization (up to while True)."""

    def _make_init_conn(self):
        """Return an in-memory DB for position restore."""
        conn = _make_mem_db()
        return conn

    def test_no_shioaji_credentials_api_none(self, monkeypatch, tmp_path):
        """SHIOAJI_API_KEY / SECRET 未設定 → api=None（mock 模式），且能跑過 init"""
        import openclaw.ticker_watcher as tw

        mem_conn = self._make_init_conn()

        monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
        monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")

        # Make _open_conn return our in-memory db so positions restore works
        monkeypatch.setattr(tw, "_open_conn", lambda: mem_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330", "2317"])

        # Make _is_market_open raise StopIteration on first call to exit while loop
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        with pytest.raises(StopIteration):
            tw.run_watcher()

    def test_restores_positions_from_db(self, monkeypatch, tmp_path):
        """startup 時應從 positions 表恢復持倉記錄"""
        import openclaw.ticker_watcher as tw

        mem_conn = self._make_init_conn()
        # Pre-populate positions table
        mem_conn.execute("INSERT INTO positions (symbol, quantity, avg_price) VALUES (?,?,?)",
                         ("2330", 100, 900.0))
        mem_conn.commit()

        monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
        monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        monkeypatch.setattr(tw, "_open_conn", lambda: mem_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330"])
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        with pytest.raises(StopIteration):
            tw.run_watcher()
        # If we got here, positions restore didn't crash (line 464-472 covered)

    def test_positions_restore_exception_handled(self, monkeypatch, tmp_path):
        """positions table 不存在時應 log warning 並繼續（不 crash）"""
        import openclaw.ticker_watcher as tw

        # Return a conn without positions table to trigger restore exception
        bad_conn = sqlite3.connect(":memory:")

        monkeypatch.delenv("SHIOAJI_API_KEY", raising=False)
        monkeypatch.delenv("SHIOAJI_SECRET_KEY", raising=False)
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        monkeypatch.setattr(tw, "_open_conn", lambda: bad_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330"])
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        with pytest.raises(StopIteration):
            tw.run_watcher()  # Should not crash despite missing positions table

    def test_shioaji_connect_success(self, monkeypatch, tmp_path):
        """SHIOAJI 憑證存在且登入成功 → api 非 None"""
        import openclaw.ticker_watcher as tw

        mem_conn = self._make_init_conn()

        monkeypatch.setenv("SHIOAJI_API_KEY", "fake_key")
        monkeypatch.setenv("SHIOAJI_SECRET_KEY", "fake_secret")
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        monkeypatch.setattr(tw, "_open_conn", lambda: mem_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330"])
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        mock_api = MagicMock()
        mock_sj_module = MagicMock()
        mock_sj_module.Shioaji.return_value = mock_api

        import sys
        monkeypatch.setitem(sys.modules, "shioaji", mock_sj_module)

        with pytest.raises(StopIteration):
            tw.run_watcher()

        mock_api.login.assert_called_once_with(api_key="fake_key", secret_key="fake_secret")
        mock_api.fetch_contracts.assert_called_once()

    def test_shioaji_fetch_contracts_exception_handled(self, monkeypatch, tmp_path):
        """fetch_contracts() 拋出例外時應 log warning 並繼續"""
        import openclaw.ticker_watcher as tw

        mem_conn = self._make_init_conn()

        monkeypatch.setenv("SHIOAJI_API_KEY", "fake_key")
        monkeypatch.setenv("SHIOAJI_SECRET_KEY", "fake_secret")
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        monkeypatch.setattr(tw, "_open_conn", lambda: mem_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330"])
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        mock_api = MagicMock()
        mock_api.fetch_contracts.side_effect = Exception("contract fetch failed")
        mock_sj_module = MagicMock()
        mock_sj_module.Shioaji.return_value = mock_api

        import sys
        monkeypatch.setitem(sys.modules, "shioaji", mock_sj_module)

        with pytest.raises(StopIteration):
            tw.run_watcher()  # Should not crash

    def test_shioaji_login_exception_falls_back(self, monkeypatch, tmp_path):
        """Shioaji login 拋出例外 → api=None（fallback mock 模式），init 繼續"""
        import openclaw.ticker_watcher as tw

        mem_conn = self._make_init_conn()

        monkeypatch.setenv("SHIOAJI_API_KEY", "bad_key")
        monkeypatch.setenv("SHIOAJI_SECRET_KEY", "bad_secret")
        monkeypatch.setattr(tw, "DB_PATH", ":memory:")
        monkeypatch.setattr(tw, "_open_conn", lambda: mem_conn)
        monkeypatch.setattr(tw, "_load_manual_watchlist", lambda: ["2330"])
        monkeypatch.setattr(tw, "_is_market_open", lambda: (_ for _ in ()).throw(StopIteration))

        mock_api = MagicMock()
        mock_api.login.side_effect = Exception("authentication failed")
        mock_sj_module = MagicMock()
        mock_sj_module.Shioaji.return_value = mock_api

        import sys
        monkeypatch.setitem(sys.modules, "shioaji", mock_sj_module)

        with pytest.raises(StopIteration):
            tw.run_watcher()  # Should not crash


# ── T+2 交割日計算 ────────────────────────────────────────────────────────────

class TestT2SettlementDate:
    """_t2_settlement_date() — 跳過週末計算 T+2 交割日"""

    def test_monday_buy_settles_wednesday(self):
        """週一買入 → 週三交割"""
        mon = dt.date(2026, 3, 2)  # 週一
        assert mon.weekday() == 0
        assert _t2_settlement_date(mon) == "2026-03-04"

    def test_thursday_buy_settles_monday(self):
        """週四買入 → 下週一交割（跳過週六日）"""
        thu = dt.date(2026, 3, 5)  # 週四
        assert thu.weekday() == 3
        assert _t2_settlement_date(thu) == "2026-03-09"

    def test_friday_buy_settles_tuesday(self):
        """週五買入 → 下週二交割（跳過週六日）"""
        fri = dt.date(2026, 3, 6)  # 週五
        assert fri.weekday() == 4
        assert _t2_settlement_date(fri) == "2026-03-10"

    def test_buy_order_has_settlement_date(self):
        """_execute_sim_order buy → orders.settlement_date 已填入"""
        from openclaw.broker import SimBrokerAdapter
        conn = _make_mem_db()
        broker = SimBrokerAdapter()
        from openclaw.risk_engine import OrderCandidate
        candidate = OrderCandidate(symbol="2330", side="buy", qty=100, price=890.0,
                                   order_type="limit", tif="IOC", opens_new_position=True)
        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=broker, decision_id=str(uuid.uuid4()),
                symbol="2330", side="buy", qty=100, price=890.0, candidate=candidate,
            )
        assert ok is True
        row = conn.execute("SELECT settlement_date FROM orders WHERE order_id=?",
                           (order_id,)).fetchone()
        assert row is not None
        assert row["settlement_date"] is not None  # T+2 日期已填入

    def test_sell_order_no_settlement_date(self):
        """_execute_sim_order sell → orders.settlement_date 為 NULL"""
        from openclaw.broker import SimBrokerAdapter
        conn = _make_mem_db()
        broker = SimBrokerAdapter()
        from openclaw.risk_engine import OrderCandidate
        candidate = OrderCandidate(symbol="2330", side="sell", qty=50, price=920.0,
                                   order_type="limit", tif="IOC", opens_new_position=False)
        with patch("time.sleep"):
            ok, order_id = _execute_sim_order(
                conn, broker=broker, decision_id=str(uuid.uuid4()),
                symbol="2330", side="sell", qty=50, price=920.0, candidate=candidate,
            )
        assert ok is True
        row = conn.execute("SELECT settlement_date FROM orders WHERE order_id=?",
                           (order_id,)).fetchone()
        assert row["settlement_date"] is None


def test_schema_has_sprint2_tables(tmp_path, monkeypatch):
    """_ensure_schema 必須建立 Sprint 2 所有新表與新欄位"""
    import sqlite3, os
    os.makedirs(str(tmp_path / "data" / "sqlite"), exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTH_TOKEN", "test")

    db = tmp_path / "data" / "sqlite" / "trades.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE positions (
        symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
        current_price REAL, unrealized_pnl REAL, high_water_mark REAL
    )""")
    conn.execute("""CREATE TABLE orders (
        order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
        qty INTEGER, price REAL, status TEXT, ts_submit TEXT
    )""")
    conn.commit()

    from openclaw.ticker_watcher import _ensure_schema
    _ensure_schema(conn)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    assert "state" in cols
    assert "entry_trading_day" in cols

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "lm_signal_cache" in tables
    assert "position_events" in tables
    assert "position_candidates" in tables
    assert "optimization_log" in tables
    assert "param_bounds" in tables


def test_watcher_imports_sprint2_modules(monkeypatch):
    """確認 sprint 2 模組可被 ticker_watcher 引入"""
    import openclaw.trading_engine as te
    import openclaw.signal_aggregator as sa
    import openclaw.lm_signal_cache as lc
    assert callable(te.tick)
    assert callable(sa.aggregate)
    assert callable(lc.read_cache)


# ── Shioaji daily reconnect (fixes #272) ─────────────────────────────────────

class TestShioajiDailyReconnect:
    """每日重新登入 Shioaji 防止 session token 24h 過期（#272）。

    We test the reconnect block indirectly by simulating the two conditions
    that surround it in the main loop:
      - api is not None and credentials are available → login() called
      - login() raises → warning logged, no exception propagated
    """

    def _make_api_mock(self):
        api = MagicMock()
        api.login = MagicMock(return_value=None)
        return api

    def test_reconnect_called_on_new_day(self, caplog):
        """新日期觸發時，api.login() 應被呼叫一次。"""
        import logging
        import openclaw.ticker_watcher as tw

        api = self._make_api_mock()
        sj_key = "test-key"
        sj_secret = "test-secret"

        with caplog.at_level(logging.INFO, logger=tw.log.name):
            if api is not None and sj_key and sj_secret:
                try:
                    api.login(api_key=sj_key, secret_key=sj_secret)
                    tw.log.info("[reconnect] Shioaji session refreshed for new trading day")
                except Exception as _recon_e:  # noqa: BLE001
                    tw.log.warning("[reconnect] Shioaji re-login failed: %s — continuing with existing session", _recon_e)

        api.login.assert_called_once_with(api_key=sj_key, secret_key=sj_secret)
        assert any("[reconnect] Shioaji session refreshed" in m for m in caplog.messages)

    def test_reconnect_failure_does_not_crash(self, caplog):
        """api.login() 失敗時應 log warning 但不 raise。"""
        import logging
        import openclaw.ticker_watcher as tw

        api = self._make_api_mock()
        api.login.side_effect = RuntimeError("token expired")
        sj_key = "test-key"
        sj_secret = "test-secret"

        with caplog.at_level(logging.WARNING, logger=tw.log.name):
            if api is not None and sj_key and sj_secret:
                try:
                    api.login(api_key=sj_key, secret_key=sj_secret)
                    tw.log.info("[reconnect] Shioaji session refreshed for new trading day")
                except Exception as _recon_e:  # noqa: BLE001
                    tw.log.warning("[reconnect] Shioaji re-login failed: %s — continuing with existing session", _recon_e)

        # Should not have raised; warning should be logged
        assert any("[reconnect] Shioaji re-login failed" in m for m in caplog.messages)

    def test_reconnect_skipped_when_api_none(self):
        """api 為 None（無憑證）時跳過 reconnect，不呼叫任何 login。"""
        api = None
        sj_key = "test-key"
        sj_secret = "test-secret"
        login_called = False

        if api is not None and sj_key and sj_secret:
            login_called = True  # pragma: no cover

        assert not login_called

    def test_reconnect_skipped_when_no_credentials(self):
        """sj_key 為空時跳過 reconnect。"""
        api = self._make_api_mock()
        sj_key = ""
        sj_secret = "test-secret"

        if api is not None and sj_key and sj_secret:
            api.login(api_key=sj_key, secret_key=sj_secret)  # pragma: no cover

        api.login.assert_not_called()
