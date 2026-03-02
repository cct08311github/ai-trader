"""ticker_watcher.py — 自動看盤與模擬交易引擎

每 POLL_INTERVAL_SEC 秒掃描 active watchlist 一次：
1. 每日開盤前，從 config/watchlist.json universe 篩選 top movers → active watchlist
2. 取得行情 (Shioaji snapshots 或 mock random walk)
3. rule-based 訊號判斷
4. 7 層 risk_engine 風控
5. insert_llm_trace → SSE /api/stream/logs 推前端
6. 若 approved → SimBrokerAdapter → persist orders/fills to DB

維護股票清單：編輯 config/watchlist.json（universe / max_active）
不需重啟：watcher 每日重新讀取並篩選
回滾方式：pm2 stop ai-trader-watcher
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

# ── 設定 ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SEC: int = 180  # 3 分鐘
STRATEGY_ID: str = "momentum_watcher"
STRATEGY_VERSION: str = "watcher_v1"
SIM_NAV: float = 2_000_000.0   # 模擬資金 200 萬 TWD
SIM_CASH: float = 1_800_000.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WATCHLIST_CFG = _REPO_ROOT / "config" / "watchlist.json"
_FALLBACK_UNIVERSE: List[str] = ["2330", "2317", "2454"]

# ── DB 連線（直接指向 data/sqlite/trades.db，與前端共用）────────────────────
_DEFAULT_DB = str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
DB_PATH: str = os.environ.get("DB_PATH", _DEFAULT_DB)


def _open_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).isoformat()


# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ticker_watcher")

# ── 台灣市場時段 (UTC+8, 09:00–13:30, 週一至週五) ─────────────────────────
_TZ_TWN = dt.timezone(dt.timedelta(hours=8))


def _is_market_open() -> bool:
    now_twn = dt.datetime.now(tz=_TZ_TWN)
    if now_twn.weekday() >= 5:  # 六、日
        return False
    open_ = now_twn.replace(hour=9, minute=0, second=0, microsecond=0)
    close_ = now_twn.replace(hour=13, minute=30, second=0, microsecond=0)
    return open_ <= now_twn <= close_


# ── Watchlist 管理 ───────────────────────────────────────────────────────────
_BASE_PRICE_DEFAULT: Dict[str, float] = {
    "2330": 900.0,  "2317": 200.0,  "2454": 1200.0, "2308": 50.0,   "2382": 220.0,
    "2881": 28.0,   "2882": 48.0,   "2886": 38.0,   "2412": 120.0,  "3008": 380.0,
    "2002": 25.0,   "1301": 90.0,   "1303": 80.0,   "2603": 60.0,   "2609": 18.0,
}


def _load_universe() -> tuple[List[str], int]:
    """讀取 config/watchlist.json，回傳 (universe, max_active)。讀取失敗時用 fallback。"""
    try:
        cfg = json.loads(_WATCHLIST_CFG.read_text(encoding="utf-8"))
        universe = [str(s).strip() for s in cfg.get("universe", []) if str(s).strip()]
        max_active = int(cfg.get("max_active", 5))
        if not universe:
            raise ValueError("universe is empty")
        return universe, max_active
    except Exception as e:
        log.warning("watchlist.json read failed (%s) — using fallback %s", e, _FALLBACK_UNIVERSE)
        return _FALLBACK_UNIVERSE, len(_FALLBACK_UNIVERSE)


def _screen_top_movers(api, universe: List[str], max_active: int) -> List[str]:
    """從 universe 篩選漲跌幅絕對值最大的 max_active 支股票。

    Shioaji 可用時用真實 snapshots；否則用 mock 隨機漂移模擬。
    結果寫入 log，並以 llm_trace 形式推 SSE（由呼叫端傳入 conn 寫入）。
    """
    import random
    scores: List[tuple[float, str]] = []

    for symbol in universe:
        snap = _get_snapshot(api, symbol)
        ref = snap["reference"]
        close = snap["close"]
        if ref > 0:
            pct = abs(close - ref) / ref
        else:
            pct = abs(random.uniform(0, 0.01))
        scores.append((pct, symbol))

    scores.sort(reverse=True)
    selected = [sym for _, sym in scores[:max_active]]
    log.info("[SCREEN] universe=%d → active=%d: %s", len(universe), len(selected), selected)
    return selected


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
        except Exception as e:
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
def _generate_signal(snap: dict, position_avg_price: Optional[float]) -> str:
    """
    買訊：close < reference * 0.998 且無持倉
    賣訊：有持倉 且 close > avg_price * 1.01（獲利 1%）
    平：其他
    """
    close = snap["close"]
    ref   = snap["reference"]
    if position_avg_price is not None:
        return "sell" if close > position_avg_price * 1.01 else "flat"
    return "buy" if close < ref * 0.998 else "flat"


# ── DB 寫入 helpers ───────────────────────────────────────────────────────────
def _persist_decision(conn: sqlite3.Connection, *, decision_id: str, symbol: str,
                       signal: str, now_iso: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO decisions
           (decision_id, ts, symbol, strategy_id, strategy_version,
            signal_side, signal_score, signal_ttl_ms, llm_ref, reason_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (decision_id, now_iso, symbol, STRATEGY_ID, STRATEGY_VERSION,
         signal, 0.7 if signal != "flat" else 0.0, 30000, None,
         json.dumps({"source": "ticker_watcher"}, ensure_ascii=True)),
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
                    price: float, status: str = "submitted") -> None:
    conn.execute(
        """INSERT INTO orders
           (order_id, decision_id, broker_order_id, ts_submit,
            symbol, side, qty, price, order_type, tif, status, strategy_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_id, decision_id, broker_order_id, _utc_now_iso(),
         symbol, side, qty, price, "limit", "IOC", status, STRATEGY_VERSION),
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
               order=None, decision_id: Optional[str] = None) -> None:
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
        metadata={
            "symbol": symbol, "signal": signal, "snap": snap, "outcome": outcome,
            "created_at_ms": int(_time.time() * 1000),
        },
    )
    try:
        insert_llm_trace(conn, trace, auto_commit=True)
    except Exception as e:
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
    except Exception as e:
        log.warning("_log_screen_trace failed: %s", e)


# ── 模擬下單執行 ──────────────────────────────────────────────────────────────
def _execute_sim_order(conn: sqlite3.Connection, *, broker, decision_id: str,
                        symbol: str, side: str, qty: int, price: float,
                        candidate) -> tuple[bool, str]:
    """提交模擬單，poll 成交，寫入 orders/fills/order_events。"""
    order_id = str(uuid.uuid4())
    submission = broker.submit_order(order_id, candidate)

    if submission.status != "submitted":
        _persist_order(conn, order_id=order_id, decision_id=decision_id,
                       broker_order_id=submission.broker_order_id or "",
                       symbol=symbol, side=side, qty=qty, price=price, status="rejected")
        log.warning("[%s] broker rejected: %s", symbol, submission.reason)
        return False, order_id

    _persist_order(conn, order_id=order_id, decision_id=decision_id,
                   broker_order_id=submission.broker_order_id,
                   symbol=symbol, side=side, qty=qty, price=price, status="submitted")
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

    log.info("[%s] order_id=%s status=%s filled=%d/%d price=%.1f",
             symbol, order_id, final_status, last_filled_qty, qty, price)
    return (final_status == "filled"), order_id


# ── 主迴圈 ────────────────────────────────────────────────────────────────────
def run_watcher() -> None:
    from openclaw.risk_engine import (
        Decision, MarketState, PortfolioState, Position, SystemState,
        evaluate_and_build_order, default_limits,
    )
    from openclaw.broker import SimBrokerAdapter
    from openclaw.risk_store import LimitQuery, load_limits
    from openclaw.daily_pm_review import get_daily_pm_approval

    broker = SimBrokerAdapter()

    # 嘗試連接 Shioaji；無憑證或連線失敗時 fallback mock
    api = None
    sj_key    = os.environ.get("SHIOAJI_API_KEY")
    sj_secret = os.environ.get("SHIOAJI_SECRET_KEY")
    if sj_key and sj_secret:
        try:
            import shioaji as sj  # type: ignore
            api = sj.Shioaji(simulation=True)
            api.login(api_key=sj_key, secret_key=sj_secret)
            log.info("Shioaji connected (simulation=True)")
        except Exception as e:
            log.warning("Shioaji not available — mock data mode: %s", e)

    # 內存持倉追蹤：symbol → avg_price（watcher 重啟後清空）
    positions: Dict[str, float] = {}

    # 每日重新篩選 watchlist
    active_watchlist: List[str] = []
    last_screen_date: Optional[dt.date] = None

    universe, max_active = _load_universe()
    log.info("Ticker watcher started | universe=%d stocks | max_active=%d | INTERVAL=%ds | DB=%s",
             len(universe), max_active, POLL_INTERVAL_SEC, DB_PATH)

    while True:
        if not _is_market_open():
            now_twn = dt.datetime.now(tz=_TZ_TWN)
            log.info("Market closed (%s TWN). Next check in 60s.", now_twn.strftime("%H:%M %a"))
            time.sleep(60)
            continue

        today = dt.datetime.now(tz=_TZ_TWN).date()

        # 每日重新讀取 universe 並篩選 active watchlist（開盤後第一次掃描觸發）
        if last_screen_date != today:
            universe, max_active = _load_universe()
            log.info("[SCREEN] New day %s — screening top movers from universe (%d stocks)…",
                     today, len(universe))
            active_watchlist = _screen_top_movers(api, universe, max_active)
            last_screen_date = today

            # 篩選結果寫 SSE trace
            conn_tmp = _open_conn()
            try:
                _log_screen_trace(conn_tmp, universe=universe, active=active_watchlist)
            finally:
                conn_tmp.close()

        log.info("=== Watcher scan start | active=%s ===", active_watchlist)
        conn = _open_conn()
        try:
            # 載入風控限制（失敗時用 default_limits）
            try:
                limits = load_limits(conn, LimitQuery(strategy_id=STRATEGY_ID))
                if not limits:
                    limits = default_limits()
            except Exception as e:
                log.warning("load_limits failed (%s) — using defaults", e)
                limits = default_limits()

            # watcher 自行做 PM 檢查，不透過 risk_engine 的檔案讀取
            limits["pm_review_required"] = 0

            if not get_daily_pm_approval():
                log.info("PM not approved for today — scan skipped")
                _log_trace(conn, symbol="ALL", signal="none",
                           snap={"close": 0, "reference": 0, "bid": 0, "ask": 0, "volume": 0},
                           approved=False, reject_code="PM_NOT_APPROVED")
                conn.close()
                time.sleep(POLL_INTERVAL_SEC)
                continue

            for symbol in active_watchlist:
                snap      = _get_snapshot(api, symbol)
                avg_price = positions.get(symbol)
                signal    = _generate_signal(snap, avg_price)
                decision_id = str(uuid.uuid4())
                now_ms = int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000)

                decision = Decision(
                    decision_id=decision_id,
                    ts_ms=now_ms,
                    symbol=symbol,
                    strategy_id=STRATEGY_ID,
                    signal_side=signal,
                    signal_score=0.7 if signal != "flat" else 0.0,
                )
                market = MarketState(
                    best_bid=snap["bid"],
                    best_ask=snap["ask"],
                    volume_1m=snap["volume"],
                    feed_delay_ms=50,
                )
                pos_map = {}
                if avg_price is not None:
                    pos_map[symbol] = Position(
                        symbol=symbol, qty=1000,
                        avg_price=avg_price, last_price=snap["close"],
                    )
                portfolio = PortfolioState(
                    nav=SIM_NAV, cash=SIM_CASH,
                    realized_pnl_today=0.0, unrealized_pnl=0.0,
                    positions=pos_map,
                )
                system = SystemState(
                    now_ms=now_ms,
                    trading_locked=False,
                    broker_connected=True,
                    db_write_p99_ms=20,
                    orders_last_60s=0,
                )

                result = evaluate_and_build_order(decision, market, portfolio, limits, system)

                _log_trace(conn, symbol=symbol, signal=signal, snap=snap,
                           approved=result.approved, reject_code=result.reject_code,
                           order=result.order, decision_id=decision_id)

                log.info("[%s] signal=%-4s close=%.1f → %s",
                         symbol, signal, snap["close"],
                         "APPROVED" if result.approved else f"REJECTED({result.reject_code})")

                if not result.approved or result.order is None:
                    # 記錄 rejected decision 供稽核
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                        _persist_decision(conn, decision_id=decision_id, symbol=symbol,
                                          signal=signal, now_iso=_utc_now_iso())
                        _persist_risk_check(conn, decision_id=decision_id, passed=False,
                                            reject_code=result.reject_code, metrics=result.metrics)
                        conn.commit()
                    except Exception as e:
                        log.debug("persist rejected decision failed: %s", e)
                        try:
                            conn.execute("ROLLBACK")
                        except Exception:
                            pass
                    continue

                # ── 執行核准訂單 ──────────────────────────────────────────
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    _persist_decision(conn, decision_id=decision_id, symbol=symbol,
                                      signal=signal, now_iso=_utc_now_iso())
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
                    )
                    conn.commit()

                    if ok:
                        if result.order.side == "buy":
                            positions[symbol] = result.order.price
                        elif result.order.side == "sell":
                            positions.pop(symbol, None)
                except Exception as e:
                    log.error("[%s] order execution error: %s", symbol, e, exc_info=True)
                    try:
                        conn.execute("ROLLBACK")
                    except Exception:
                        pass

        except Exception as e:
            log.error("Scan cycle error: %s", e, exc_info=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        log.info("=== Scan done. Sleeping %ds ===", POLL_INTERVAL_SEC)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run_watcher()
