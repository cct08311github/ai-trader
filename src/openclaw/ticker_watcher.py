"""ticker_watcher.py — 自動看盤與模擬交易引擎

每 POLL_INTERVAL_SEC 秒掃描 active watchlist 一次：
1. 每日開盤前，合併雙來源清單：
   a. config/watchlist.json manual_watchlist（手動追蹤）
   b. stock_screener DB system_candidates（系統自動篩選，盤後 EOD 產生）
2. 取得行情 (Shioaji snapshots 或 mock random walk)
3. rule-based 訊號判斷
4. 7 層 risk_engine 風控
5. insert_llm_trace → SSE /api/stream/logs 推前端
6. 若 approved → SimBrokerAdapter → persist orders/fills to DB

維護股票清單：編輯 config/watchlist.json（manual_watchlist）
不需重啟：watcher 每日重新讀取並合併
回滾方式：pm2 stop ai-trader-watcher
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# Graceful shutdown flag — set by SIGTERM/SIGINT handler
_shutdown_requested: bool = False

# EOD 清理旗標：記錄最後一次執行取消未成交訂單的日期，確保每日只執行一次
_eod_cleanup_done_date: Optional[dt.date] = None


def _handle_shutdown_signal(signum: int, frame: object) -> None:  # noqa: ARG001
    global _shutdown_requested
    _shutdown_requested = True
    log.info("Shutdown signal %d received — will exit after current scan cycle.", signum)


def _interruptible_sleep(seconds: int) -> bool:
    """Sleep for `seconds`, returning True immediately if shutdown is requested."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _shutdown_requested:
            return True
        time.sleep(min(1, deadline - time.monotonic()))
    return False

from openclaw.pnl_engine import on_sell_filled, sync_positions_table

# ── 設定 ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SEC: int = 180  # 3 分鐘
STRATEGY_ID: str = "momentum_watcher"
STRATEGY_VERSION: str = "watcher_v1"

from openclaw.path_utils import get_repo_root
_REPO_ROOT = get_repo_root()
_WATCHLIST_CFG = _REPO_ROOT / "config" / "watchlist.json"
_FALLBACK_UNIVERSE: List[str] = ["2330", "2317", "2454"]
_PRICE_HISTORY_MAX: int = 60    # 每支股票保留最近 N 筆收盤價，供 regime 分類
_CASH_MODE_MIN_PRICES: int = 20  # 至少需要此筆數才能評估 market regime

# 信號閾值（可透過環境變數覆寫）
import os as _os
from openclaw.path_utils import get_repo_root
_BUY_SIGNAL_PCT:           float = float(_os.environ.get("BUY_SIGNAL_PCT",    "0.002"))  # close < ref*(1-0.2%)
_TAKE_PROFIT_PCT:          float = float(_os.environ.get("TAKE_PROFIT_PCT",   "0.02"))   # +2% 止盈
_STOP_LOSS_PCT:            float = float(_os.environ.get("STOP_LOSS_PCT",     "0.03"))   # -3% 止損
_TRAILING_PCT_BASE:        float = float(_os.environ.get("TRAILING_PCT",      "0.05"))   # Trailing Stop 基礎 5%
_TRAILING_PCT_TIGHT:       float = float(_os.environ.get("TRAILING_PCT_TIGHT","0.03"))   # 大獲利收緊至 3%
_TRAILING_PROFIT_THRESHOLD: float = 0.50  # 獲利超過 50% 啟用收緊 trailing

# ── DB 連線（直接指向 data/sqlite/trades.db，與前端共用）────────────────────
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
DB_PATH: str = os.environ.get("DB_PATH", _DEFAULT_DB)

_CAPITAL_CFG = _REPO_ROOT / "config" / "capital.json"
_SIM_NAV_FALLBACK: float = 1_000_000.0


def _load_sim_nav() -> float:
    """讀取 config/capital.json 的 total_capital_twd，缺檔時回傳 fallback 1_000_000。"""
    try:
        data = json.loads(_CAPITAL_CFG.read_text(encoding="utf-8"))
        return float(data["total_capital_twd"])
    except (OSError, KeyError, ValueError, TypeError) as e:
        log.warning("_load_sim_nav: capital.json read failed (%s) — using fallback %.0f", e, _SIM_NAV_FALLBACK)
        return _SIM_NAV_FALLBACK


def _get_realized_pnl_today(conn: sqlite3.Connection) -> float:
    """查詢今日（UTC+8）已實現損益。"""
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(f.price * f.qty - f.fee - f.tax), 0.0)
               FROM fills f
               JOIN orders o ON f.order_id = o.order_id
               WHERE date(o.ts_submit, '+8 hours') = date('now', '+8 hours')
                 AND o.side = 'sell'"""
        ).fetchone()
        return float(row[0]) if row else 0.0
    except sqlite3.Error as e:
        log.warning("_get_realized_pnl_today failed: %s", e)
        return 0.0


def _check_broker_connected(sj_instance) -> bool:
    """True 只有在 sj_instance 非 None 且 list_accounts() 不拋例外。"""
    if sj_instance is None:
        return False
    try:
        sj_instance.list_accounts()
        return True
    except Exception:  # noqa: BLE001 — broker API; can't predict exceptions
        return False


def _get_orders_last_60s(conn: sqlite3.Connection) -> int:
    """計算最近 60 秒內的訂單數。"""
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM orders WHERE ts_submit >= datetime('now', '-1 minute')"
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.Error as e:
        log.warning("_get_orders_last_60s failed: %s", e)
        return 0


def _get_today_buy_filled_symbols(conn: sqlite3.Connection) -> set:
    """返回今日（UTC+8）已有 fills 的 buy 訂單 symbol 集合，用於 wash sale 防護。"""
    try:
        rows = conn.execute(
            """SELECT DISTINCT o.symbol
               FROM orders o
               JOIN fills f ON f.order_id = o.order_id
               WHERE o.side = 'buy'
                 AND date(o.ts_submit, '+8 hours') = date('now', '+8 hours')"""
        ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.Error as e:
        log.warning("_get_today_buy_filled_symbols failed: %s", e)
        return set()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """執行 schema migration：為舊版 DB 新增缺少的欄位。

    設計為冪等：若欄位已存在則靜默跳過（OperationalError "duplicate column"）。
    """
    migrations = [
        "ALTER TABLE positions ADD COLUMN high_water_mark REAL",
        "ALTER TABLE orders ADD COLUMN settlement_date TEXT",
        # Sprint 2
        "ALTER TABLE positions ADD COLUMN state TEXT DEFAULT 'HOLDING'",
        "ALTER TABLE positions ADD COLUMN entry_trading_day TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                log.warning("Migration skipped (unexpected): %s | %s", sql[:60], e)

    # Sprint 2 新表（逐條 execute 避免 executescript 的隱式 COMMIT）
    sprint2_ddl = [
        """CREATE TABLE IF NOT EXISTS lm_signal_cache (
            cache_id    TEXT PRIMARY KEY,
            symbol      TEXT,
            score       REAL NOT NULL,
            source      TEXT NOT NULL,
            direction   TEXT,
            raw_json    TEXT,
            created_at  INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_lm_cache_lookup ON lm_signal_cache (symbol, expires_at)",
        """CREATE TABLE IF NOT EXISTS position_events (
            event_id    TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            from_state  TEXT,
            to_state    TEXT NOT NULL,
            reason      TEXT,
            trading_day TEXT NOT NULL,
            ts          INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_pos_events_symbol ON position_events (symbol, ts)",
        """CREATE TABLE IF NOT EXISTS position_candidates (
            symbol      TEXT PRIMARY KEY,
            trading_day TEXT NOT NULL,
            reason      TEXT,
            created_at  INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS optimization_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              INTEGER NOT NULL,
            trigger_type    TEXT NOT NULL,
            param_key       TEXT NOT NULL,
            old_value       REAL,
            new_value       REAL,
            is_auto         INTEGER DEFAULT 0,
            sample_n        INTEGER,
            confidence      REAL,
            rationale       TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_opt_log_ts ON optimization_log (ts)",
        """CREATE TABLE IF NOT EXISTS param_bounds (
            param_key           TEXT PRIMARY KEY,
            min_val             REAL NOT NULL,
            max_val             REAL NOT NULL,
            weekly_max_delta    REAL NOT NULL,
            last_auto_change_ts INTEGER,
            frozen_until_ts     INTEGER
        )""",
    ]
    for ddl in sprint2_ddl:
        conn.execute(ddl)
    conn.commit()


def _open_conn() -> sqlite3.Connection:
    from openclaw.db_utils import open_watcher_conn
    conn = open_watcher_conn(DB_PATH)
    _ensure_schema(conn)
    return conn


def _utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


def _t2_settlement_date(trade_date: "dt.date") -> str:
    """計算台股 T+2 交割日（跳過週末與國定假日）。

    使用 trading_calendar.get_settlement_date() 正確排除台灣國定假日。
    Returns: YYYY-MM-DD 字串
    """
    from openclaw.trading_calendar import get_settlement_date
    return get_settlement_date(trade_date).strftime("%Y-%m-%d")


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ticker_watcher")

# ── 台灣市場時段 (UTC+8, 09:00–13:30, 週一至週五) ─────────────────────────
_TZ_TWN = dt.timezone(dt.timedelta(hours=8))


def _is_market_open(_now_twn: Optional[dt.datetime] = None) -> bool:
    """True 代表 TWN 股市目前在交易時段（盤前/正常/盤後競價）。

    三層檢查：
    1. 週末排除（週六、日）
    2. 時段檢查：tw_session_rules.tw_session_allows_trading
       - preopen_auction 09:00–09:10
       - regular         09:10–13:25
       - afterhours      13:30–13:40
    3. 節假日：trading_calendar 的 FESTIVAL 效應 → 市場休市
    """
    from openclaw.tw_session_rules import tw_session_allows_trading
    from openclaw.trading_calendar import SeasonalEffectType, get_effects_for_date

    now_twn = _now_twn or dt.datetime.now(tz=_TZ_TWN)
    if now_twn.weekday() >= 5:  # 六、日
        return False
    now_ms = int(now_twn.timestamp() * 1000)
    if not tw_session_allows_trading(now_ms):
        return False
    today_str = now_twn.strftime("%Y-%m-%d")
    for eff in get_effects_for_date(today_str):
        if eff.effect_type == SeasonalEffectType.FESTIVAL:
            log.info("Holiday detected (%s) — market closed", eff.name)
            return False
    return True


# ── Watchlist 管理 ───────────────────────────────────────────────────────────
_BASE_PRICE_DEFAULT: Dict[str, float] = {
    "2330": 900.0,  "2317": 200.0,  "2454": 1200.0, "2308": 50.0,   "2382": 220.0,
    "2881": 28.0,   "2882": 48.0,   "2886": 38.0,   "2412": 120.0,  "3008": 380.0,
    "2002": 25.0,   "1301": 90.0,   "1303": 80.0,   "2603": 60.0,   "2609": 18.0,
}


def _load_manual_watchlist() -> List[str]:
    """讀取 config/watchlist.json，回傳手動追蹤清單。讀取失敗時用 fallback。"""
    try:
        cfg = json.loads(_WATCHLIST_CFG.read_text(encoding="utf-8"))
        # 優先讀 manual_watchlist，向後相容 universe
        wl = cfg.get("manual_watchlist") or cfg.get("universe") or []
        result = [str(s).strip() for s in wl if str(s).strip()]
        if not result:
            raise ValueError("manual_watchlist is empty")
        return result
    except (OSError, ValueError) as e:
        log.warning("watchlist.json read failed (%s) — using fallback %s", e, _FALLBACK_UNIVERSE)
        return list(_FALLBACK_UNIVERSE)



# ── 行情取得 (Shioaji 或 mock random walk) ──────────────────────────────────
_BASE_PRICE: Dict[str, float] = _BASE_PRICE_DEFAULT


def _get_snapshot(api, symbol: str) -> dict:
    """取得 bid/ask/close/reference/volume。優先 Shioaji，不可用時 mock。"""
    if api is not None:
        try:
            contract = api.Contracts.Stocks[symbol]
            snaps = api.snapshots([contract])
            if snaps:
                s = snaps[0]
                close = float(getattr(s, "close", 0) or 0)
                bid   = float(getattr(s, "buy_price",  0) or close * 0.999)
                ask   = float(getattr(s, "sell_price", 0) or close * 1.001)
                ref   = float(getattr(s, "reference",  close) or close)
                vol   = int(getattr(s, "volume", 1000) or 1000)
                if close > 0:
                    return {"close": close, "bid": bid, "ask": ask, "reference": ref, "volume": vol}
        except Exception as e:  # noqa: BLE001 — broker API; can't predict exceptions
            log.warning("Shioaji snapshot [%s]: %s — using mock", symbol, e)

    # Mock: small random walk around base price
    import random
    base = _BASE_PRICE.get(symbol, 100.0)
    close = round(base * (1 + random.uniform(-0.003, 0.003)), 1)
    return {
        "close": close,
        "bid":   round(close * 0.999, 1),
        "ask":   round(close * 1.001, 1),
        "reference": base,
        "volume": random.randint(500, 5000),
        "source": "mock",
    }


# ── 訊號產生 (rule-based, no LLM) ────────────────────────────────────────────
def _generate_signal(
    snap: dict,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float] = None,
    trailing_pct: float = _TRAILING_PCT_BASE,
) -> str:
    """產生交易訊號（rule-based，無 LLM）。

    有持倉時（按優先順序）：
      1. Trailing Stop：close < high_water_mark * (1 - effective_trailing)  → sell
         - 獲利超過 _TRAILING_PROFIT_THRESHOLD 時，trailing 從 5% 收緊至 3%
      2. 止盈：close > avg_price * (1 + _TAKE_PROFIT_PCT)  → sell
      3. 止損：close < avg_price * (1 - _STOP_LOSS_PCT)    → sell
      4. 其他：flat（持有）

    無持倉時：
      - 買訊：close < reference * (1 - _BUY_SIGNAL_PCT)   → buy
      - 其他：flat

    閾值可透過環境變數覆寫（BUY_SIGNAL_PCT / TAKE_PROFIT_PCT / STOP_LOSS_PCT / TRAILING_PCT）。
    """
    close = snap["close"]
    ref   = snap["reference"]

    if position_avg_price is not None:
        # Trailing Stop：動態收緊（大獲利時保護更多利潤）
        if high_water_mark and position_avg_price > 0:
            effective_trailing = trailing_pct
            profit_pct = (high_water_mark - position_avg_price) / position_avg_price
            if profit_pct >= _TRAILING_PROFIT_THRESHOLD:
                effective_trailing = _TRAILING_PCT_TIGHT
            if close < high_water_mark * (1 - effective_trailing):
                return "sell"   # trailing stop

        # 止盈 / 止損
        if close > position_avg_price * (1 + _TAKE_PROFIT_PCT):
            return "sell"   # 止盈
        if close < position_avg_price * (1 - _STOP_LOSS_PCT):
            return "sell"   # 止損
        return "flat"

    return "buy" if close < ref * (1 - _BUY_SIGNAL_PCT) else "flat"


# ── DB 寫入 helpers ───────────────────────────────────────────────────────────
def _persist_decision(conn: sqlite3.Connection, *, decision_id: str, symbol: str,
                       signal: str, now_iso: str,
                       signal_source: str = "technical") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO decisions
           (decision_id, ts, symbol, strategy_id, strategy_version,
            signal_side, signal_score, signal_ttl_ms, llm_ref, reason_json,
            signal_source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (decision_id, now_iso, symbol, STRATEGY_ID, STRATEGY_VERSION,
         signal, 0.7 if signal != "flat" else 0.0, 30000, None,
         json.dumps({"source": "ticker_watcher"}, ensure_ascii=True),
         signal_source),
    )


def _persist_risk_check(conn: sqlite3.Connection, *, decision_id: str, passed: bool,
                         reject_code: Optional[str], metrics: dict) -> None:
    conn.execute(
        """INSERT INTO risk_checks
           (check_id, decision_id, ts, passed, reject_code, metrics_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), decision_id, _utc_now_iso(),
         int(passed), reject_code, json.dumps(metrics, ensure_ascii=True)),
    )


def _persist_order(conn: sqlite3.Connection, *, order_id: str, decision_id: str,
                    broker_order_id: str, symbol: str, side: str, qty: int,
                    price: float, status: str = "submitted",
                    settlement_date: Optional[str] = None) -> None:
    conn.execute(
        """INSERT INTO orders
           (order_id, decision_id, broker_order_id, ts_submit,
            symbol, side, qty, price, order_type, tif, status, strategy_version,
            settlement_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, decision_id, broker_order_id, _utc_now_iso(),
         symbol, side, qty, price, "limit", "IOC", status, STRATEGY_VERSION,
         settlement_date),
    )


def _persist_fill(conn: sqlite3.Connection, *, order_id: str, qty: int,
                   price: float, fee: float = 0.0, tax: float = 0.0) -> None:
    conn.execute(
        """INSERT INTO fills (fill_id, order_id, ts_fill, qty, price, fee, tax)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), order_id, _utc_now_iso(), qty, price, fee, tax),
    )


def _insert_order_event(conn: sqlite3.Connection, *, order_id: str, event_type: str,
                         from_status: Optional[str], to_status: Optional[str],
                         source: str, reason_code: Optional[str], payload: dict) -> None:
    conn.execute(
        """INSERT INTO order_events
           (event_id, ts, order_id, event_type, from_status, to_status,
            source, reason_code, payload_json)
           VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), order_id, event_type, from_status, to_status,
         source, reason_code, json.dumps(payload, ensure_ascii=True)),
    )


# ── SSE 可視 trace (agent='watcher') ─────────────────────────────────────────
def _log_trace(conn: sqlite3.Connection, *, symbol: str, signal: str, snap: dict,
               approved: bool, reject_code: Optional[str],
               order=None, decision_id: Optional[str] = None,
               extra_meta: Optional[dict] = None) -> None:
    from openclaw.llm_observability import LLMTrace, insert_llm_trace

    summary = (
        f"[WATCHER] {symbol} | signal={signal} | "
        f"close={snap['close']} ref={snap['reference']} "
        f"bid={snap['bid']} ask={snap['ask']} vol={snap['volume']}"
    )
    outcome = "APPROVED" if approved else f"REJECTED({reject_code})"
    response = outcome
    if order:
        response += f" | order: {order.side} {order.qty}@{order.price}"

    import time as _time
    meta: dict = {
        "symbol": symbol, "signal": signal, "snap": snap, "outcome": outcome,
        "created_at_ms": int(_time.time() * 1000),
    }
    if extra_meta:
        meta.update(extra_meta)
    trace = LLMTrace(
        component="watcher",
        agent="watcher",
        model="rule-based",
        prompt_text=summary,
        response_text=response,
        input_tokens=0,
        output_tokens=0,
        latency_ms=0,
        decision_id=decision_id,
        metadata=meta,
    )
    try:
        insert_llm_trace(conn, trace, auto_commit=True)
    except Exception as e:  # noqa: BLE001 — log utility; must never crash caller
        log.warning("insert_llm_trace failed: %s", e)


# ── 篩選結果 SSE trace ───────────────────────────────────────────────────────
def _log_screen_trace(conn: sqlite3.Connection, *, universe: List[str], active: List[str]) -> None:
    from openclaw.llm_observability import LLMTrace, insert_llm_trace
    import time as _time
    prompt = f"[SCREENER] universe={len(universe)} stocks → top_movers → active={len(active)}"
    response = f"active watchlist: {', '.join(active)}"
    trace = LLMTrace(
        component="watcher", agent="watcher", model="screener",
        prompt_text=prompt, response_text=response,
        input_tokens=0, output_tokens=0, latency_ms=0,
        metadata={"universe": universe, "active": active,
                  "created_at_ms": int(_time.time() * 1000)},
    )
    try:
        insert_llm_trace(conn, trace, auto_commit=True)
    except Exception as e:  # noqa: BLE001 — log utility; must never crash caller
        log.warning("_log_screen_trace failed: %s", e)


# ── 價格歷史與 Cash Mode 評估 ─────────────────────────────────────────────────
def _update_price_history(price_history: Dict[str, List[float]], symbol: str, close: float) -> None:
    """將收盤價加入 symbol 的歷史佇列（上限 _PRICE_HISTORY_MAX）。"""
    hist = price_history.setdefault(symbol, [])
    hist.append(close)
    if len(hist) > _PRICE_HISTORY_MAX:
        del hist[0]


def _build_exit_closes(
    conn: sqlite3.Connection,
    symbol: str,
    price_history: Dict[str, List[float]],
) -> List[float]:
    """組合 EOD 歷史收盤 + 當日盤中 ticks，供 exit signal 評估使用。

    watcher 重啟後 price_history 為空，仍可從 eod_prices 取得歷史資料，
    確保 MA/RSI 計算不因重啟而短暫失效。
    """
    eod_rows = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT ?",
        (symbol, _PRICE_HISTORY_MAX),
    ).fetchall()
    eod_closes: List[float] = [r[0] for r in reversed(eod_rows)]

    # 盤中 ticks（最多取最後 20 筆，避免重複疊加過多）
    intraday: List[float] = price_history.get(symbol, [])[-20:]

    return eod_closes + intraday


def _evaluate_cash_mode(
    price_history: Dict[str, List[float]], current_cash_mode: bool
) -> tuple[bool, str]:
    """根據價格歷史評估市場 cash mode（reduce-only）狀態。

    選取基準股（bellwether）：優先用 2330，其次取歷史最長的股票。
    資料不足時維持現狀，不切換。
    回傳 (cash_mode: bool, reason_code: str)。
    """
    from openclaw.market_regime import classify_market_regime
    from openclaw.cash_mode import CashModePolicy
    from openclaw.cash_mode import evaluate_cash_mode as _eval_cm

    bellwether: Optional[str] = None
    candidates = ["2330"] + [s for s in price_history if s != "2330"]
    for sym in candidates:
        if len(price_history.get(sym, [])) >= _CASH_MODE_MIN_PRICES:
            bellwether = sym
            break

    if bellwether is None:
        return current_cash_mode, "CASHMODE_INSUFFICIENT_DATA"

    regime_result = classify_market_regime(price_history[bellwether])
    decision = _eval_cm(regime_result, current_cash_mode=current_cash_mode, policy=CashModePolicy.default())
    return decision.cash_mode, decision.reason_code


# ── 模擬下單執行 ──────────────────────────────────────────────────────────────
def _execute_sim_order(conn: sqlite3.Connection, *, broker, decision_id: str,
                        symbol: str, side: str, qty: int, price: float,
                        candidate, guard_limits: dict | None = None) -> tuple[bool, str]:
    """提交模擬單，poll 成交，寫入 orders/fills/order_events。"""
    from openclaw.pre_trade_guard import evaluate_pre_trade_guard

    order_id = str(uuid.uuid4())
    guard_result = evaluate_pre_trade_guard(conn, candidate, limits=guard_limits)
    if not guard_result.approved:
        _persist_order(conn, order_id=order_id, decision_id=decision_id,
                       broker_order_id="", symbol=symbol, side=side, qty=qty,
                       price=price, status="rejected")
        _insert_order_event(conn, order_id=order_id, event_type="rejected",
                            from_status=None, to_status="rejected",
                            source="pre_trade_guard",
                            reason_code=guard_result.reject_code,
                            payload=guard_result.metrics)
        log.warning("[%s] pre-trade guard rejected order: %s", symbol, guard_result.reject_code)
        return False, order_id

    submission = broker.submit_order(order_id, candidate)

    # T+2 交割日：買單才需計算；賣單交割款項 T+2 入帳，無需追蹤
    settlement_date = (
        _t2_settlement_date(dt.datetime.now(tz=_TZ_TWN).date())
        if side == "buy" else None
    )

    if submission.status != "submitted":
        _persist_order(conn, order_id=order_id, decision_id=decision_id,
                       broker_order_id=submission.broker_order_id or "",
                       symbol=symbol, side=side, qty=qty, price=price, status="rejected",
                       settlement_date=settlement_date)
        log.warning("[%s] broker rejected: %s", symbol, submission.reason)
        return False, order_id

    _persist_order(conn, order_id=order_id, decision_id=decision_id,
                   broker_order_id=submission.broker_order_id,
                   symbol=symbol, side=side, qty=qty, price=price, status="submitted",
                   settlement_date=settlement_date)
    _insert_order_event(conn, order_id=order_id, event_type="submitted",
                        from_status=None, to_status="submitted",
                        source="watcher", reason_code=None,
                        payload={"broker_order_id": submission.broker_order_id})

    # Poll for fill (SimBrokerAdapter fills in 2 rounds)
    last_filled_qty = 0
    final_status = "submitted"
    for _ in range(12):
        s = broker.poll_order_status(submission.broker_order_id)
        if s is None:
            time.sleep(0.5)
            continue
        # Insert fill delta
        new_qty = max(last_filled_qty, int(s.filled_qty))
        delta = new_qty - last_filled_qty
        if delta > 0:
            _persist_fill(conn, order_id=order_id, qty=delta,
                          price=s.avg_fill_price, fee=s.fee, tax=s.tax)
            last_filled_qty = new_qty
        if s.status in {"filled", "cancelled", "rejected", "expired"}:
            final_status = s.status
            conn.execute("UPDATE orders SET status=? WHERE order_id=?", (s.status, order_id))
            _insert_order_event(conn, order_id=order_id, event_type=s.status,
                                from_status="submitted", to_status=s.status,
                                source="broker", reason_code=s.reason_code or None,
                                payload={"filled_qty": last_filled_qty,
                                         "avg_price": s.avg_fill_price})
            break
        time.sleep(0.5)

    # 處理超時後部分成交的狀況（loop 結束但未到 terminal）
    if final_status == "submitted" and last_filled_qty > 0:
        final_status = "partially_filled"
        conn.execute("UPDATE orders SET status='partially_filled' WHERE order_id=?", (order_id,))
        conn.commit()
        log.warning("[%s] order_id=%s timed out with partial fill %d/%d — marked partially_filled",
                    symbol, order_id, last_filled_qty, qty)

    log.info("[%s] order_id=%s status=%s filled=%d/%d price=%.1f",
             symbol, order_id, final_status, last_filled_qty, qty, price)
    return (final_status == "filled"), order_id


def _check_live_mode_safety(
    emergency_stop_path: str = ".EMERGENCY_STOP",
    trading_enabled: bool = False,
) -> tuple[bool, str]:
    """Live 模式安全檢查。回傳 (safe, reason)。"""
    if os.path.exists(emergency_stop_path):
        return False, "EMERGENCY_STOP file exists"
    if not trading_enabled:
        return False, "trading_enabled is False"
    return True, "OK"


# ── EOD 盤後清理：取消當日未成交的 pending/submitted 訂單 ─────────────────────
def _cancel_stale_pending_orders(conn: sqlite3.Connection, broker) -> int:
    """收盤前取消所有今日未成交的 pending/submitted 訂單。

    台股收盤後（13:30+）呼叫，避免未成交限價單在隔日以過期價格成交。
    使用 date(ts_submit, '+8 hours') 將 UTC ISO 時間戳轉換為台北日期比對。

    Returns: number of orders cancelled
    """
    today_str = dt.datetime.now(tz=_TZ_TWN).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT order_id, broker_order_id, symbol
           FROM orders
           WHERE status IN ('pending', 'submitted', 'partially_filled')
             AND date(ts_submit, '+8 hours') = ?""",
        (today_str,),
    ).fetchall()

    cancelled = 0
    for row in rows:
        order_id, broker_order_id, symbol = row[0], row[1], row[2]
        try:
            broker.cancel_order(broker_order_id or order_id)
            conn.execute(
                "UPDATE orders SET status='cancelled' WHERE order_id=?",
                (order_id,),
            )
            conn.commit()
            log.info("[EOD] Cancelled stale order %s (%s)", order_id[:8], symbol)
            cancelled += 1
        except Exception as e:  # noqa: BLE001 — broker API; can't predict exceptions
            log.warning("[EOD] Failed to cancel order %s: %s", order_id[:8], e)
    return cancelled


# ── 主迴圈 ────────────────────────────────────────────────────────────────────
def run_watcher() -> None:
    # Register graceful shutdown handlers — flag is checked at each loop boundary
    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    # 啟動 Telegram Kill Switch 背景監聽（需設定 TELEGRAM_BOT_TOKEN）
    try:
        from openclaw.tg_kill_switch import start_kill_switch_listener
        start_kill_switch_listener()
    except Exception as _ks_e:  # noqa: BLE001 — 選用元件，啟動失敗不中斷 watcher
        log.warning("tg_kill_switch 啟動失敗（不影響 watcher 運作）: %s", _ks_e)

    from openclaw.risk_engine import (
        Decision, MarketState, PortfolioState, Position, SystemState,
        evaluate_and_build_order, default_limits,
    )
    from openclaw.broker import SimBrokerAdapter, ShioajiAdapter
    from openclaw.risk_store import LimitQuery, load_limits
    from openclaw.daily_pm_review import get_daily_pm_approval

    trading_mode = os.environ.get("TRADING_MODE", "simulation")
    simulation = trading_mode != "live"
    if not simulation:
        _safety_path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "..", ".EMERGENCY_STOP")
        _safe, _safe_reason = _check_live_mode_safety(
            emergency_stop_path=_safety_path,
            trading_enabled=True,
        )
        if not _safe:
            log.error("[LIVE MODE] Safety check FAILED: %s — falling back to simulation", _safe_reason)
            simulation = True
    log.info("=== Ticker Watcher === mode=%s", "SIMULATION" if simulation else "[LIVE MODE]")

    # 讀取 NAV from capital.json（啟動時一次性載入）
    sim_nav = _load_sim_nav()
    sim_cash = sim_nav * 0.9  # 保留 10% 現金 buffer

    # 嘗試連接 Shioaji；無憑證或連線失敗時 fallback mock
    api = None
    sj_account = None
    sj_key    = os.environ.get("SHIOAJI_API_KEY")
    sj_secret = os.environ.get("SHIOAJI_SECRET_KEY")
    if sj_key and sj_secret:
        try:
            import shioaji as sj  # type: ignore
            api = sj.Shioaji(simulation=simulation)
            api.login(api_key=sj_key, secret_key=sj_secret)
            accounts = api.list_accounts()
            sj_account = accounts[0] if accounts else None
            # 確保股票合約資料已載入（shioaji 1.3.x: fetch_contracts() 無 contract_type 參數）
            try:
                api.fetch_contracts()
                log.info("Shioaji contracts fetched (simulation=%s)", simulation)
            except Exception as fe:  # noqa: BLE001 — broker API; can't predict exceptions
                log.warning("fetch_contracts failed (%s) — snapshots may use fallback", fe)
            log.info("Shioaji connected (simulation=%s) — using real market data", simulation)
        except Exception as e:  # noqa: BLE001 — broker API; can't predict exceptions
            log.warning("Shioaji not available — mock data mode: %s", e)

    # Issue #266: 根據 simulation_mode 選擇正確的 broker adapter
    if not simulation and api is not None and sj_account is not None:
        broker = ShioajiAdapter(api, sj_account)
        log.info("Using ShioajiAdapter (live mode)")
    else:
        broker = SimBrokerAdapter()
        log.info("Using SimBrokerAdapter (simulation mode)")

    # 內存持倉追蹤：symbol → (qty, avg_price)（watcher 重啟後清空，從 DB sync）
    positions: Dict[str, tuple[int, float]] = {}
    high_water_marks: Dict[str, float] = {}  # symbol → 持倉後最高收盤價
    # 每支股票的收盤價歷史（供 market regime / cash mode 評估）
    price_history: Dict[str, List[float]] = {}
    cash_mode_state: bool = False  # True = reduce-only，不開新倉

    # 啟動時從 positions table 恢復持倉（避免重啟後遺忘已有部位）
    try:
        _conn_init = _open_conn()
        for _row in _conn_init.execute(
            "SELECT symbol, quantity, avg_price, high_water_mark FROM positions WHERE quantity > 0"
        ).fetchall():
            positions[_row[0]] = (int(_row[1]), float(_row[2]))
            if _row[3]:
                high_water_marks[_row[0]] = float(_row[3])
        _conn_init.close()
        if positions:
            log.info("Restored %d positions from DB: %s", len(positions), list(positions.keys()))
    except sqlite3.Error as _e:
        log.warning("Could not restore positions from DB: %s", _e)

    # 每日重新篩選 watchlist
    active_watchlist: List[str] = []
    last_screen_date: Optional[dt.date] = None

    manual_watchlist = _load_manual_watchlist()
    log.info("Ticker watcher started | manual_watchlist=%d stocks | INTERVAL=%ds | DB=%s",
             len(manual_watchlist), POLL_INTERVAL_SEC, DB_PATH)

    while not _shutdown_requested:  # pragma: no cover
        if not _is_market_open():
            now_twn = dt.datetime.now(tz=_TZ_TWN)
            log.info("Market closed (%s TWN). Next check in 60s.", now_twn.strftime("%H:%M %a"))
            # 非交易時段仍處理 Telegram 提案通知與按鈕回應
            try:
                _conn = _open_conn()
                from openclaw.tg_approver import notify_pending_proposals, poll_approval_callbacks
                notify_pending_proposals(_conn)
                n_cb = poll_approval_callbacks(_conn)
                if n_cb > 0:
                    log.info("[tg_approver] Off-hours: processed %d callbacks", n_cb)
                _conn.close()
            except Exception as _tge:  # noqa: BLE001 — dynamic import + Telegram API
                log.debug("[tg_approver] off-hours error: %s", _tge)
            _interruptible_sleep(60)
            continue

        today = dt.datetime.now(tz=_TZ_TWN).date()

        # 每日重新載入手動清單 + 系統候選 → 合併 active watchlist
        if last_screen_date != today:
            # 每日重新登入 Shioaji，防止 session token 24h 過期 (fixes #272)
            if api is not None and sj_key and sj_secret:
                try:
                    api.login(api_key=sj_key, secret_key=sj_secret)
                    log.info("[reconnect] Shioaji session refreshed for new trading day")
                except Exception as _recon_e:  # noqa: BLE001 — broker API; can't predict exceptions
                    log.warning("[reconnect] Shioaji re-login failed: %s — continuing with existing session", _recon_e)

            manual_watchlist = _load_manual_watchlist()
            sys_candidates: List[str] = []
            try:
                from openclaw.stock_screener import load_system_candidates
                _conn_sc = _open_conn()
                try:
                    sys_candidates = load_system_candidates(_conn_sc)
                finally:
                    _conn_sc.close()
            except Exception as _sc_e:  # noqa: BLE001 — dynamic import; can't predict exceptions
                log.warning("[SCREEN] load_system_candidates failed: %s", _sc_e)
            active_watchlist = list(dict.fromkeys(manual_watchlist + sys_candidates))
            log.info("[SCREEN] New day %s — manual=%d + system=%d → active=%d: %s",
                     today, len(manual_watchlist), len(sys_candidates),
                     len(active_watchlist), active_watchlist)
            last_screen_date = today

            # 篩選結果寫 SSE trace
            conn_tmp = _open_conn()
            try:
                _log_screen_trace(conn_tmp, universe=manual_watchlist, active=active_watchlist)
            finally:
                conn_tmp.close()

        log.info("=== Watcher scan start | active=%s ===", active_watchlist)
        conn = _open_conn()
        try:
            # 每輪掃描統一時間戳（毫秒），供 session 判斷與 Decision 使用
            scan_ms = int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000)

            # 載入風控限制（失敗時用 default_limits）
            try:
                limits = load_limits(conn, LimitQuery(strategy_id=STRATEGY_ID))
                if not limits:
                    limits = default_limits()
            except sqlite3.Error as e:
                log.warning("load_limits failed (%s) — using defaults", e)
                limits = default_limits()

            # watcher 自行做 PM 檢查，不透過 risk_engine 的檔案讀取
            limits["pm_review_required"] = 0

            # 時段風控調整（preopen × 0.5 / regular × 1.0 / afterhours × 0.6–0.7）
            from openclaw.tw_session_rules import apply_tw_session_risk_adjustments
            limits = apply_tw_session_risk_adjustments(limits, now_ms=scan_ms)

            if not get_daily_pm_approval():
                log.info("PM not approved for today — scan skipped")
                _log_trace(conn, symbol="ALL", signal="none",
                           snap={"close": 0, "reference": 0, "bid": 0, "ask": 0, "volume": 0},
                           approved=False, reject_code="PM_NOT_APPROVED")
                # PM 未審核也需發送提案通知（讓用戶審核）
                try:
                    from openclaw.tg_approver import notify_pending_proposals
                    n_tg = notify_pending_proposals(conn)
                    if n_tg > 0:
                        log.info("[tg_approver] Sent %d proposal notifications (PM not approved)", n_tg)
                except Exception as _tge:  # noqa: BLE001 — dynamic import + Telegram API
                    log.debug("[tg_approver] error: %s", _tge)
                conn.close()
                time.sleep(POLL_INTERVAL_SEC)
                continue

            # ── Mock 資料防護：Shioaji 未連線時禁止開倉 ──────────────────
            data_is_mock = (api is None)
            if data_is_mock:
                log.warning("Shioaji not connected — running in MOCK DATA mode. "
                            "New position opens are BLOCKED. Only close signals (sell) allowed.")

            # 一次性取得所有行情，並更新價格歷史
            snaps: Dict[str, dict] = {sym: _get_snapshot(api, sym) for sym in active_watchlist}
            for sym, s in snaps.items():
                _update_price_history(price_history, sym, s["close"])

            # 每輪評估一次 cash mode（市場評級過低 → reduce-only，不開新倉）
            new_cash_mode, cash_reason = _evaluate_cash_mode(price_history, cash_mode_state)
            if new_cash_mode != cash_mode_state:
                log.info("[CASH_MODE] %s → %s (%s)", cash_mode_state, new_cash_mode, cash_reason)
                cash_mode_state = new_cash_mode
                _log_trace(conn, symbol="MARKET", signal="cash_mode",
                           snap={"close": 0, "reference": 0, "bid": 0, "ask": 0, "volume": 0},
                           approved=not cash_mode_state, reject_code=cash_reason if cash_mode_state else None)

            # ── Bug Fix: 每輪掃描前，把全部已持倉加入 pos_map 供風控使用 ──
            # 取得所有有行情的持倉的最新 last_price（未在 active watchlist 的用 avg_price fallback）
            all_pos_map: Dict[str, Position] = {}
            for _sym, (_qty, _avg) in positions.items():
                _last = snaps[_sym]["close"] if _sym in snaps else _avg
                all_pos_map[_sym] = Position(symbol=_sym, qty=_qty, avg_price=_avg, last_price=_last)

            # ── 回寫最新市價與未實現損益到 positions 表 ─────────────────
            for _sym, _pos in all_pos_map.items():
                _upnl = round((_pos.last_price - _pos.avg_price) * _pos.qty, 2)
                conn.execute(
                    "UPDATE positions SET current_price=?, unrealized_pnl=? WHERE symbol=?",
                    (_pos.last_price, _upnl, _sym),
                )

            # ── Sell 自動觸發：對已持倉 symbol 評估 exit ──────────────────────
            from openclaw.signal_logic import evaluate_exit as _eval_exit, SignalParams as _SigParams
            _locked_syms: set = set()
            try:
                from openclaw.risk_engine import _is_symbol_locked
                _locked_syms = {s for s in positions if _is_symbol_locked(s)}
            except (ImportError, OSError, ValueError):
                pass

            for _exit_sym, (_exit_qty, _exit_avg) in list(positions.items()):
                _exit_closes = _build_exit_closes(conn, _exit_sym, price_history)
                if len(_exit_closes) < 5:
                    continue
                if _exit_sym in _locked_syms:
                    log.debug("[%s] sell skipped — locked symbol", _exit_sym)
                    continue
                _exit_sig = _eval_exit(
                    _exit_closes, _exit_avg, high_water_marks.get(_exit_sym), _SigParams()
                )
                if _exit_sig.signal != "sell":
                    continue
                log.info("[%s] exit signal=%s reason=%s", _exit_sym, _exit_sig.signal, _exit_sig.reason)
                _sell_decision_id = str(uuid.uuid4())
                _sell_decision = Decision(
                    decision_id=_sell_decision_id,
                    ts_ms=scan_ms,
                    symbol=_exit_sym,
                    strategy_id=STRATEGY_ID,
                    signal_side="sell",
                    signal_score=0.9,
                )
                _exit_snap = snaps.get(_exit_sym, {"bid": _exit_avg, "ask": _exit_avg, "volume": 1})
                _exit_market = MarketState(
                    best_bid=_exit_snap["bid"],
                    best_ask=_exit_snap["ask"],
                    volume_1m=_exit_snap["volume"],
                    feed_delay_ms=50,
                )
                _exit_portfolio = PortfolioState(
                    nav=sim_nav, cash=sim_cash,
                    realized_pnl_today=_get_realized_pnl_today(conn), unrealized_pnl=0.0,
                    positions=all_pos_map,
                    same_day_fill_symbols=_get_today_buy_filled_symbols(conn),
                )
                _exit_system = SystemState(
                    now_ms=scan_ms,
                    trading_locked=False,
                    broker_connected=_check_broker_connected(api),
                    db_write_p99_ms=20,
                    orders_last_60s=_get_orders_last_60s(conn),
                    reduce_only_mode=cash_mode_state,
                )
                _exit_result = evaluate_and_build_order(
                    _sell_decision, _exit_market, _exit_portfolio, limits, _exit_system
                )
                if not _exit_result.approved or _exit_result.order is None:
                    log.info("[%s] SELL blocked by risk: %s", _exit_sym, _exit_result.reject_code)
                    continue
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    _persist_decision(conn, decision_id=_sell_decision_id, symbol=_exit_sym,
                                      signal="sell", now_iso=_utc_now_iso())
                    _persist_risk_check(conn, decision_id=_sell_decision_id, passed=True,
                                        reject_code=None, metrics=_exit_result.metrics)
                    conn.commit()
                    conn.execute("BEGIN IMMEDIATE")
                    _ok, _oid = _execute_sim_order(
                        conn, broker=broker,
                        decision_id=_sell_decision_id,
                        symbol=_exit_sym,
                        side="sell",
                        qty=_exit_result.order.qty,
                        price=_exit_result.order.price,
                        candidate=_exit_result.order,
                        guard_limits=limits,
                    )
                    conn.commit()
                    if _ok:
                        try:
                            _trade_date = dt.datetime.now(tz=_TZ_TWN).strftime("%Y-%m-%d")
                            _fill_row = conn.execute(
                                "SELECT COALESCE(SUM(fee),0.0), COALESCE(SUM(tax),0.0)"
                                " FROM fills WHERE order_id=?",
                                (_oid,),
                            ).fetchone()
                            on_sell_filled(
                                conn, symbol=_exit_sym,
                                sell_qty=_exit_result.order.qty,
                                sell_price=_exit_result.order.price,
                                sell_fee=float(_fill_row[0]),
                                sell_tax=float(_fill_row[1]),
                                trade_date=_trade_date,
                            )
                        except (sqlite3.Error, ValueError, ArithmeticError) as _pnl_err:
                            log.warning("[%s] pnl_engine error: %s", _exit_sym, _pnl_err)
                        positions.pop(_exit_sym, None)
                        high_water_marks.pop(_exit_sym, None)
                        log.info("[%s] SELL executed: reason=%s", _exit_sym, _exit_sig.reason)
                except Exception as _sell_err:  # noqa: BLE001 — Shioaji broker API; can't predict exceptions
                    log.error("[%s] sell execution error: %s", _exit_sym, _sell_err, exc_info=True)
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:  # noqa: BLE001 — rollback guard; must not raise
                        pass

            for symbol in active_watchlist:
                snap      = snaps[symbol]
                pos_entry = positions.get(symbol)          # (qty, avg_price) or None
                avg_price = pos_entry[1] if pos_entry else None

                # 更新高水位記憶（每次掃盤）
                cur_close = snap["close"]
                if avg_price is not None:
                    hwm = high_water_marks.get(symbol, cur_close)
                    if cur_close > hwm:
                        high_water_marks[symbol] = cur_close
                        conn.execute(
                            "UPDATE positions SET high_water_mark=? WHERE symbol=?",
                            (cur_close, symbol)
                        )

                # Sprint 2：呼叫 trading_engine.tick 後改用 signal_aggregator
                try:
                    from openclaw.trading_engine import tick as _te_tick
                    _te_tick(conn, symbol)
                except Exception as _te_err:  # noqa: BLE001 — dynamic import; can't predict exceptions
                    log.warning("[%s] trading_engine.tick 失敗：%s", symbol, _te_err)

                _agg_meta: dict = {}
                _dominant_source: str = "technical"
                try:
                    from openclaw.signal_aggregator import aggregate as _agg
                    _agg_signal = _agg(
                        conn, symbol, snap,
                        position_avg_price=avg_price,
                        high_water_mark=high_water_marks.get(symbol),
                    )
                    sig = _agg_signal.action
                    _dominant_source = _agg_signal.dominant_source
                    # 將 aggregator 結果記入 trace metadata
                    _agg_meta = {
                        "regime": _agg_signal.regime,
                        "score": _agg_signal.score,
                        "weights": _agg_signal.weights_used,
                        "reasons": _agg_signal.reasons,
                        "dominant_source": _dominant_source,
                    }
                except Exception as _agg_err:  # noqa: BLE001 — dynamic import; can't predict exceptions
                    log.warning("[%s] signal_aggregator 失敗 (%s), fallback to signal_generator",
                                symbol, _agg_err)
                    from openclaw.signal_generator import compute_signal as _sg_compute
                    sig = _sg_compute(
                        conn, symbol=symbol,
                        position_avg_price=avg_price,
                        high_water_mark=high_water_marks.get(symbol),
                    )
                decision_id = str(uuid.uuid4())

                # ── Mock 防護：mock 資料禁止開新倉（buy） ────────────────
                if data_is_mock and sig == "buy":
                    _log_trace(conn, symbol=symbol, signal=sig, snap=snap,
                               approved=False, reject_code="RISK_MOCK_DATA_FORBIDDEN",
                               decision_id=decision_id, extra_meta=_agg_meta)
                    log.info("[%s] signal=buy BLOCKED — mock data mode", symbol)
                    continue

                decision = Decision(
                    decision_id=decision_id,
                    ts_ms=scan_ms,
                    symbol=symbol,
                    strategy_id=STRATEGY_ID,
                    signal_side=sig,
                    signal_score=0.7 if sig != "flat" else 0.0,
                )
                market = MarketState(
                    best_bid=snap["bid"],
                    best_ask=snap["ask"],
                    volume_1m=snap["volume"],
                    feed_delay_ms=50,
                )
                portfolio = PortfolioState(
                    nav=sim_nav, cash=sim_cash,
                    realized_pnl_today=_get_realized_pnl_today(conn), unrealized_pnl=0.0,
                    positions=all_pos_map,   # ← 包含全部持倉，gross_exposure 正確累計
                    same_day_fill_symbols=_get_today_buy_filled_symbols(conn),
                )
                system = SystemState(
                    now_ms=scan_ms,
                    trading_locked=False,
                    broker_connected=_check_broker_connected(api),
                    db_write_p99_ms=20,
                    orders_last_60s=_get_orders_last_60s(conn),
                    reduce_only_mode=cash_mode_state,
                )

                result = evaluate_and_build_order(decision, market, portfolio, limits, system)

                _log_trace(conn, symbol=symbol, signal=sig, snap=snap,
                           approved=result.approved, reject_code=result.reject_code,
                           order=result.order, decision_id=decision_id,
                           extra_meta=_agg_meta)

                log.info("[%s] signal=%-4s close=%.1f → %s",
                         symbol, sig, snap["close"],
                         "APPROVED" if result.approved else f"REJECTED({result.reject_code})")

                if not result.approved or result.order is None:
                    # 記錄 rejected decision 供稽核
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        _persist_decision(conn, decision_id=decision_id, symbol=symbol,
                                          signal=sig, now_iso=_utc_now_iso(),
                                          signal_source=_dominant_source)
                        _persist_risk_check(conn, decision_id=decision_id, passed=False,
                                            reject_code=result.reject_code, metrics=result.metrics)
                        conn.commit()
                    except sqlite3.Error as e:
                        log.debug("persist rejected decision failed: %s", e)
                        try:
                            conn.execute("ROLLBACK")
                        except Exception:  # noqa: BLE001 — rollback guard; must not raise
                            pass
                    continue

                # ── 執行核准訂單 ──────────────────────────────────────────
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    _persist_decision(conn, decision_id=decision_id, symbol=symbol,
                                      signal=sig, now_iso=_utc_now_iso(),
                                      signal_source=_dominant_source)
                    _persist_risk_check(conn, decision_id=decision_id, passed=True,
                                        reject_code=None, metrics=result.metrics)
                    conn.commit()

                    conn.execute("BEGIN IMMEDIATE")
                    ok, order_id = _execute_sim_order(
                        conn, broker=broker,
                        decision_id=decision_id,
                        symbol=symbol,
                        side=result.order.side,
                        qty=result.order.qty,
                        price=result.order.price,
                        candidate=result.order,
                        guard_limits=limits,
                    )
                    conn.commit()

                    if ok:
                        if result.order.side == "buy":
                            prev_qty, prev_avg = positions.get(symbol, (0, result.order.price))
                            new_qty = prev_qty + result.order.qty
                            # weighted avg cost update
                            new_avg = ((prev_avg * prev_qty) + (result.order.price * result.order.qty)) / new_qty
                            positions[symbol] = (new_qty, round(new_avg, 4))
                            log.info("[%s] position updated: qty=%d avg=%.4f", symbol, new_qty, new_avg)
                        elif result.order.side == "sell":
                            # Compute realized PnL and persist to daily_pnl_summary
                            try:
                                trade_date = dt.datetime.now(tz=_TZ_TWN).strftime("%Y-%m-%d")
                                # 讀取實際成交費用（fills 已存入正確手續費 + 證交稅）
                                _fill_row = conn.execute(
                                    "SELECT COALESCE(SUM(fee),0.0), COALESCE(SUM(tax),0.0)"
                                    " FROM fills WHERE order_id=?",
                                    (order_id,),
                                ).fetchone()
                                sell_fee = float(_fill_row[0])
                                sell_tax = float(_fill_row[1])
                                pnl = on_sell_filled(
                                    conn,
                                    symbol=symbol,
                                    sell_qty=result.order.qty,
                                    sell_price=result.order.price,
                                    sell_fee=sell_fee,
                                    sell_tax=sell_tax,
                                    trade_date=trade_date,
                                )
                                log.info("[%s] realized_pnl=%.2f written to daily_pnl_summary", symbol, pnl)
                            except (sqlite3.Error, ValueError, ArithmeticError) as pnl_err:
                                log.warning("[%s] pnl_engine error: %s", symbol, pnl_err)
                            positions.pop(symbol, None)
                            log.info("[%s] position closed — removed from in-memory map", symbol)

                        # Sync positions table after every fill
                        try:
                            sync_positions_table(conn)
                        except sqlite3.Error as sync_err:
                            log.warning("sync_positions_table error: %s", sync_err)
                except Exception as e:  # noqa: BLE001 — Shioaji broker API; can't predict exceptions
                    log.error("[%s] order execution error: %s", symbol, e, exc_info=True)
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:  # noqa: BLE001 — rollback guard; must not raise
                        pass

            # ── 每輪掃盤後：執行 approved proposals + 集中度守衛 ─────────────
            try:
                from openclaw.proposal_executor import (
                    SellIntent,
                    execute_pending_proposals,
                    mark_intent_executed,
                    mark_intent_executing,
                    mark_intent_failed,
                )
                from openclaw.risk_engine import OrderCandidate
                sell_intents, n_noted = execute_pending_proposals(conn)
                for intent in sell_intents:
                    try:
                        candidate = OrderCandidate(
                            symbol=intent.symbol, side="sell",
                            qty=intent.qty, price=intent.price,
                            order_type="limit", tif="ROD",
                            opens_new_position=False,
                        )
                        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
                        conn.execute("BEGIN IMMEDIATE")
                        ok, _oid = _execute_sim_order(
                            conn, broker=broker,
                            decision_id=intent.proposal_id,
                            symbol=intent.symbol,
                            side="sell", qty=intent.qty,
                            price=intent.price, candidate=candidate,
                            guard_limits=limits,
                        )
                        conn.commit()
                        if ok:
                            try:
                                mark_intent_executed(
                                    conn,
                                    intent.proposal_id,
                                    execution_key=intent.execution_key,
                                    order_id=_oid,
                                )
                            except sqlite3.Error as mark_err:
                                log.critical("[proposals] BROKER EXECUTED sell %s %d shares but "
                                             "failed to mark proposal %s as executed — "
                                             "RISK OF DUPLICATE EXECUTION: %s",
                                             intent.symbol, intent.qty,
                                             intent.proposal_id, mark_err, exc_info=True)
                            log.info("[proposals] Executed rebalance sell %s %d @ %.2f via broker",
                                     intent.symbol, intent.qty, intent.price)
                        else:
                            mark_intent_failed(
                                conn,
                                intent.proposal_id,
                                "broker_rejected",
                                execution_key=intent.execution_key,
                                order_id=_oid,
                            )
                            log.warning("[proposals] Broker rejected rebalance sell %s → marked failed", intent.symbol)
                    except Exception as intent_err:  # noqa: BLE001 — per-intent guard; Shioaji may raise anything
                        mark_intent_failed(
                            conn,
                            intent.proposal_id,
                            str(intent_err),
                            execution_key=intent.execution_key,
                        )
                        log.error("[proposals] intent execution error for %s: %s → marked failed",
                                  intent.symbol, intent_err, exc_info=True)
                        try:
                            conn.execute("ROLLBACK")
                        except Exception as rb_err:  # noqa: BLE001 — rollback guard; must not raise
                            log.error("[proposals] ROLLBACK failed — DB state may be inconsistent: %s", rb_err)
                if sell_intents or n_noted:
                    log.info("[proposals] Processed %d sell intents, %d noted", len(sell_intents), n_noted)
            except Exception as pe:  # noqa: BLE001 — dynamic import + multi-step pipeline
                log.error("[proposals] executor error: %s", pe, exc_info=True)

            try:
                from openclaw.concentration_guard import check_concentration
                c_proposals = check_concentration(conn)
                if c_proposals:
                    log.info("[concentration] Generated %d concentration proposals", len(c_proposals))
            except Exception as ce:  # noqa: BLE001 — dynamic import; can't predict exceptions
                log.error("[concentration] guard error: %s", ce, exc_info=True)

            # ── Gemini 自動審查 pending proposals → 核准/拒絕 + Telegram 通知 ──
            try:
                from openclaw.proposal_reviewer import auto_review_pending_proposals
                n_reviewed = auto_review_pending_proposals(conn)
                if n_reviewed > 0:
                    log.info("[reviewer] Auto-reviewed %d pending proposals", n_reviewed)
            except Exception as rv:  # noqa: BLE001 — dynamic import + Gemini API
                log.error("[reviewer] proposal reviewer error: %s", rv, exc_info=True)

            # ── Telegram 提案通知 + 老闆 inline 核准 ──────────────────────────
            try:
                from openclaw.tg_approver import notify_pending_proposals, poll_approval_callbacks
                n_notify = notify_pending_proposals(conn)
                if n_notify > 0:
                    log.info("[tg_approver] Sent %d proposal notifications", n_notify)
                n_cb = poll_approval_callbacks(conn)
                if n_cb > 0:
                    log.info("[tg_approver] Processed %d approval callbacks", n_cb)
            except Exception as _ta:  # noqa: BLE001 — dynamic import + Telegram API
                log.warning("[tg_approver] error: %s", _ta)

            # ── EOD 盤後清理：收盤後取消未成交訂單（每日只執行一次）────────
            global _eod_cleanup_done_date
            now_twn = dt.datetime.now(tz=_TZ_TWN)
            if now_twn.hour > 13 or (now_twn.hour == 13 and now_twn.minute >= 30):
                if _eod_cleanup_done_date != today:
                    try:
                        n = _cancel_stale_pending_orders(conn, broker)
                        if n > 0:
                            log.info("[EOD] Cancelled %d stale orders", n)
                        _eod_cleanup_done_date = today
                    except Exception as _eod_e:  # noqa: BLE001 — cleanup guard; must not crash scan loop
                        log.warning("[EOD] cleanup failed: %s", _eod_e)

        except Exception as e:  # noqa: BLE001 — outer scan cycle guard; must catch all
            log.error("Scan cycle error: %s", e, exc_info=True)
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass

        log.info("=== Scan done. Sleeping %ds ===", POLL_INTERVAL_SEC)
        _interruptible_sleep(POLL_INTERVAL_SEC)

    log.info("Graceful shutdown complete.")


if __name__ == "__main__":  # pragma: no cover
    run_watcher()
