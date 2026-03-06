"""agents/eod_analysis.py — 盤後分析 Agent。

執行時機：每交易日 16:35 TWN
工作：EOD 數據 → 技術指標計算 → Gemini 策略分析 → eod_analysis_reports
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

from openclaw.agents.base import (
    AgentResult, DEFAULT_MODEL, call_agent_llm, open_conn,
    query_db, write_trace,
)
from openclaw.technical_indicators import (
    calc_ma, calc_rsi, calc_macd, find_support_resistance,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_PROMPT_TEMPLATE = """\
你是 AI Trader 系統的 EODAnalysisAgent（盤後分析師）。

## 分析日期：{trade_date}

### 今日市場概覽
{market_overview}

### 三大法人流向（外資/投信/自營商）
{institution_data}

### 持倉技術指標
{technical_summary}

## 任務
1. 評估今日整體多空氣氛（bullish/neutral/bearish）及主力板塊
2. 針對每個持倉提出明日操作建議（hold/reduce/stop_profit）
3. 從技術指標中找出明日觀察名單機會
4. 列出需要注意的風險點

## 輸出格式（必須是 JSON）
```json
{{
  "summary": "...",
  "confidence": 0.75,
  "action_type": "suggest",
  "market_outlook": {{
    "sentiment": "bullish",
    "sector_focus": ["半導體"],
    "confidence": 0.75
  }},
  "position_actions": [
    {{"symbol": "2330", "action": "hold", "reason": "..."}}
  ],
  "watchlist_opportunities": [
    {{"symbol": "6442", "entry_condition": "...", "stop_loss": 2100}}
  ],
  "risk_notes": ["..."],
  "proposals": []
}}
```
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_analysis_reports (
            trade_date      TEXT PRIMARY KEY,
            generated_at    INTEGER NOT NULL,
            market_summary  TEXT NOT NULL,
            technical       TEXT NOT NULL,
            strategy        TEXT NOT NULL,
            raw_prompt      TEXT,
            model_used      TEXT NOT NULL DEFAULT 'gemini-2.5-flash'
        )
    """)
    conn.commit()


def _calc_symbol_indicators(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> dict:
    """查歷史收盤價，計算技術指標。"""
    rows = query_db(
        conn,
        "SELECT close, high, low FROM eod_prices "
        "WHERE symbol=? AND trade_date<=? AND close IS NOT NULL "
        "ORDER BY trade_date DESC LIMIT 60",
        (symbol, trade_date),
    )
    if not rows:
        return {}

    # 資料由新到舊，需反轉
    rows = list(reversed(rows))
    closes = [r["close"] for r in rows]
    highs  = [r["high"] or r["close"] for r in rows]
    lows   = [r["low"] or r["close"] for r in rows]

    ma5  = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60)
    rsi  = calc_rsi(closes, 14)
    macd_result = calc_macd(closes)
    sr   = find_support_resistance(highs, lows, closes)

    def _last(lst):
        for v in reversed(lst):
            if v is not None:
                return round(v, 2)
        return None

    return {
        "close": closes[-1],
        "ma5": _last(ma5),
        "ma20": _last(ma20),
        "ma60": _last(ma60),
        "rsi14": _last(rsi),
        "macd": {
            "macd": _last(macd_result["macd"]),
            "signal": _last(macd_result["signal"]),
            "histogram": _last(macd_result["histogram"]),
        },
        "support": sr["support"],
        "resistance": sr["resistance"],
    }


def run_eod_analysis(
    trade_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> AgentResult:
    _db_path = db_path or str(_REPO_ROOT / "data" / "sqlite" / "trades.db")
    _conn = conn or open_conn(_db_path)
    _date = trade_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    try:
        _ensure_table(_conn)

        # 0. 抓取盤後公開資料（三大法人 + 融資借券）
        try:
            from openclaw.market_data_fetcher import run_daily_fetch
            run_daily_fetch(_date, _conn)
        except Exception as _e:
            log.warning("[eod_analysis] market_data_fetcher 失敗，繼續執行: %s", _e)

        # 0.5 篩選潛力候選股
        try:
            from openclaw.stock_screener import screen_candidates
            watchlist_cfg_path = _REPO_ROOT / "config" / "watchlist.json"
            manual_wl = []
            if watchlist_cfg_path.exists():
                wl_cfg = json.loads(watchlist_cfg_path.read_text())
                manual_wl = wl_cfg.get("manual_watchlist", wl_cfg.get("universe", []))
            screen_candidates(
                _conn, _date,
                manual_watchlist=set(manual_wl),
                max_candidates=10,
                llm_refine=True,
            )
        except Exception as _e:
            log.warning("[eod_analysis] stock_screener 失敗，繼續執行: %s", _e)

        # 1. 市場概覽
        top_movers = query_db(
            _conn,
            "SELECT symbol, name, close, change, volume FROM eod_prices "
            "WHERE trade_date=? AND market='TWSE' AND close IS NOT NULL "
            "ORDER BY ABS(change) DESC LIMIT 10",
            (_date,),
        )
        if not top_movers:
            return AgentResult(
                success=False,
                summary=f"無 {_date} EOD 資料，跳過分析",
                confidence=0.0,
                action_type="observe",
                proposals=[],
                raw={},
            )

        # 2. 三大法人（優先查新表 eod_institution_flows，舊表 institution_flows 作 fallback）
        institution_data = query_db(
            _conn,
            "SELECT symbol, name, foreign_net, trust_net AS investment_trust_net, "
            "dealer_net, total_net "
            "FROM eod_institution_flows WHERE trade_date=? ORDER BY ABS(total_net) DESC LIMIT 10",
            (_date,),
        )
        if not institution_data:
            institution_data = query_db(
                _conn,
                "SELECT symbol, foreign_net, investment_trust_net, dealer_net, total_net "
                "FROM institution_flows WHERE trade_date=? ORDER BY ABS(total_net) DESC LIMIT 10",
                (_date,),
            )

        # 3. 持倉 + watchlist 技術指標
        positions = query_db(_conn, "SELECT symbol FROM positions", ())
        pos_symbols = [r["symbol"] for r in positions]

        watchlist_path = _REPO_ROOT / "config" / "watchlist.json"
        watchlist_symbols: list = []
        if watchlist_path.exists():
            wl = json.loads(watchlist_path.read_text())
            watchlist_symbols = wl.get("active_watchlist", [])[:10]

        all_symbols = list(dict.fromkeys(pos_symbols + watchlist_symbols))[:20]
        technical: dict = {}
        for sym in all_symbols:
            indicators = _calc_symbol_indicators(_conn, sym, _date)
            if indicators:
                technical[sym] = indicators

        # 4. 組 Prompt
        prompt = _PROMPT_TEMPLATE.format(
            trade_date=_date,
            market_overview=json.dumps(top_movers, ensure_ascii=False, indent=2),
            institution_data=json.dumps(institution_data, ensure_ascii=False, indent=2) or "（無三大法人資料）",
            technical_summary=json.dumps(technical, ensure_ascii=False, indent=2),
        )

        # 5. 呼叫 Gemini
        result_dict = call_agent_llm(prompt, model=DEFAULT_MODEL)
        write_trace(_conn, agent="eod_analysis", prompt=prompt[:500], result=result_dict)

        # 6. 組 market_summary JSON
        market_summary = {
            "trade_date": _date,
            "top_movers": top_movers[:10],
            "institution_flows": institution_data,
            "sentiment": result_dict.get("market_outlook", {}).get("sentiment", "neutral"),
        }

        # 7. 寫入 eod_analysis_reports（upsert）
        _conn.execute(
            """
            INSERT OR REPLACE INTO eod_analysis_reports
            (trade_date, generated_at, market_summary, technical, strategy, raw_prompt, model_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _date,
                int(time.time() * 1000),
                json.dumps(market_summary, ensure_ascii=False),
                json.dumps(technical, ensure_ascii=False),
                json.dumps(result_dict, ensure_ascii=False),
                prompt[:2000],
                DEFAULT_MODEL,
            ),
        )
        _conn.commit()

        # EOD 統計優化（每日）
        try:
            from openclaw.strategy_optimizer import StrategyMetricsEngine, OptimizationGateway
            metrics = StrategyMetricsEngine(_conn).compute(window_days=28)
            adjustments = OptimizationGateway(_conn).on_eod(metrics)
            if adjustments:
                log.info("[eod_analysis] 自動調整 %d 項參數", len(adjustments))
        except Exception as e:
            log.warning("[eod_analysis] strategy_optimizer 失敗：%s", e)

        return AgentResult(
            success=True,
            summary=result_dict.get("summary", "盤後分析完成"),
            confidence=float(result_dict.get("confidence", 0.7)),
            action_type=str(result_dict.get("action_type", "suggest")),
            proposals=result_dict.get("proposals", []),
            raw=result_dict,
        )
    finally:
        if conn is None:
            _conn.close()
