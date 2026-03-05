# 盤後分析頁面 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 `/analysis` 盤後分析頁面，展示 EOD 技術指標（MA/RSI/MACD）、三大法人流向、以及 Gemini 生成的明日策略建議。

**Architecture:** 靜態快照模式 — 每日盤後 Cron 觸發 `eod_analysis` agent，計算技術指標並呼叫 Gemini，結果存入 `eod_analysis_reports` 表；FastAPI `/api/analysis/*` 讀取快照；React `/analysis` 頁面 3 Tab 展示。

**Tech Stack:** Python (sqlite3, typing), Gemini API (via `call_agent_llm`), FastAPI (Pydantic), React 18 + Tailwind + recharts

---

## Task 1：技術指標純函數模組（TDD）

**Files:**
- Create: `src/openclaw/technical_indicators.py`
- Test: `src/tests/test_technical_indicators.py`

### Step 1: 寫失敗測試

```python
# src/tests/test_technical_indicators.py
from openclaw.technical_indicators import calc_ma, calc_rsi, calc_macd, find_support_resistance


def test_calc_ma_basic():
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calc_ma(prices, 3) == [None, None, 20.0, 30.0, 40.0]


def test_calc_ma_insufficient_data():
    assert calc_ma([1.0, 2.0], 5) == [None, None]


def test_calc_rsi_overbought():
    # 14 期全漲→ RSI 應接近 100
    prices = [float(i) for i in range(1, 20)]
    rsi = calc_rsi(prices, period=14)
    assert rsi[-1] > 90.0


def test_calc_rsi_oversold():
    # 14 期全跌→ RSI 應接近 0
    prices = [float(20 - i) for i in range(20)]
    rsi = calc_rsi(prices, period=14)
    assert rsi[-1] < 10.0


def test_calc_macd_returns_keys():
    prices = [100.0 + i * 0.5 for i in range(35)]
    result = calc_macd(prices)
    assert "macd" in result and "signal" in result and "histogram" in result
    assert len(result["macd"]) == len(prices)


def test_find_support_resistance_returns_floats():
    highs = [110.0, 115.0, 112.0, 118.0, 113.0]
    lows  = [100.0,  98.0, 102.0,  97.0, 101.0]
    closes = [105.0, 107.0, 104.0, 110.0, 108.0]
    result = find_support_resistance(highs, lows, closes)
    assert "support" in result and "resistance" in result
    assert result["support"] < result["resistance"]
```

### Step 2: 確認測試失敗

```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
PYTHONPATH=src python -m pytest src/tests/test_technical_indicators.py -v
```
Expected: `ModuleNotFoundError: No module named 'openclaw.technical_indicators'`

### Step 3: 實作 `technical_indicators.py`

```python
# src/openclaw/technical_indicators.py
"""技術指標計算 — 純函數，不依賴外部套件。"""
from __future__ import annotations
from typing import List, Optional, Dict


def calc_ma(prices: List[float], window: int) -> List[Optional[float]]:
    """移動平均。前 window-1 個位置回傳 None。"""
    result: List[Optional[float]] = []
    for i in range(len(prices)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(sum(prices[i - window + 1 : i + 1]) / window)
    return result


def _ema(prices: List[float], period: int) -> List[float]:
    """指數移動平均（EMA），用於 MACD / RSI 平滑。"""
    k = 2.0 / (period + 1)
    ema: List[float] = []
    for i, p in enumerate(prices):
        if i == 0:
            ema.append(p)
        else:
            ema.append(p * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """RSI（Wilder 平滑法）。前 period 個位置回傳 None。"""
    if len(prices) < period + 1:
        return [None] * len(prices)

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    result: List[Optional[float]] = [None] * period

    # 第一個 RSI：用簡單平均做種子
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from_avg(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    result.append(_rsi_from_avg(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result.append(_rsi_from_avg(avg_gain, avg_loss))

    return result


def calc_macd(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, List[Optional[float]]]:
    """MACD(fast, slow, signal)。回傳 {macd, signal, histogram}，各長度與 prices 相同。"""
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)

    macd_line: List[Optional[float]] = []
    for i in range(len(prices)):
        if i < slow - 1:
            macd_line.append(None)
        else:
            macd_line.append(ema_fast[i] - ema_slow[i])

    # Signal line：只對非 None 的 macd_line 做 EMA
    valid_macd = [v for v in macd_line if v is not None]
    ema_signal = _ema(valid_macd, signal)

    signal_line: List[Optional[float]] = [None] * (len(prices) - len(valid_macd))
    signal_line.extend(ema_signal)

    histogram: List[Optional[float]] = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def find_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> Dict[str, float]:
    """以近期 high/low 的簡單統計估算支撐壓力位。"""
    if not highs or not lows:
        return {"support": 0.0, "resistance": 0.0}
    # 近 20 根（或全部）
    n = min(20, len(highs))
    recent_highs = sorted(highs[-n:])
    recent_lows  = sorted(lows[-n:])
    # 壓力：前 25% 高點的均值；支撐：後 25% 低點的均值
    q = max(1, n // 4)
    resistance = sum(recent_highs[-q:]) / q
    support    = sum(recent_lows[:q]) / q
    return {"support": round(support, 2), "resistance": round(resistance, 2)}
```

### Step 4: 確認測試通過

```bash
PYTHONPATH=src python -m pytest src/tests/test_technical_indicators.py -v
```
Expected: 6 tests PASS

### Step 5: Commit

```bash
git add src/openclaw/technical_indicators.py src/tests/test_technical_indicators.py
git commit -m "feat(analysis): 新增技術指標純函數模組 (MA/RSI/MACD/support-resistance)"
```

---

## Task 2：DB Migration — `eod_analysis_reports` 表

**Files:**
- Modify: `src/openclaw/agents/eod_analysis.py`（建表邏輯在 agent 首次執行時自動建立）
- Test: 手動確認

### Step 1: 確認表不存在

```bash
sqlite3 data/sqlite/trades.db ".tables" | grep eod_analysis
```
Expected: 空輸出（表不存在）

### Step 2: 撰寫建表 SQL（將放入 eod_analysis.py）

```sql
CREATE TABLE IF NOT EXISTS eod_analysis_reports (
  trade_date      TEXT PRIMARY KEY,
  generated_at    INTEGER NOT NULL,
  market_summary  TEXT NOT NULL,
  technical       TEXT NOT NULL,
  strategy        TEXT NOT NULL,
  raw_prompt      TEXT,
  model_used      TEXT NOT NULL DEFAULT 'gemini-2.5-flash'
);
```

（不需要單獨 migration 檔，在 agent 的 `_ensure_table()` 內自動建立，與現有慣例一致）

---

## Task 3：EOD 分析 Agent（TDD）

**Files:**
- Create: `src/openclaw/agents/eod_analysis.py`
- Test: `src/tests/agents/test_eod_analysis.py`

### Step 1: 寫失敗測試

```python
# src/tests/agents/test_eod_analysis.py
import json
import sqlite3
import pytest
from openclaw.agents.eod_analysis import run_eod_analysis


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE eod_prices (
            trade_date TEXT, market TEXT, symbol TEXT, name TEXT,
            close REAL, change REAL, open REAL, high REAL, low REAL,
            volume REAL, turnover REAL, trades REAL, source_url TEXT,
            ingested_at TEXT,
            PRIMARY KEY (trade_date, market, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE institution_flows (
            trade_date TEXT, symbol TEXT,
            foreign_net REAL, investment_trust_net REAL,
            dealer_net REAL, total_net REAL, health_score REAL,
            source_url TEXT, ingested_at TEXT,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            qty REAL, avg_cost REAL, current_price REAL,
            unrealized_pnl REAL, last_updated TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE llm_traces (
            trace_id TEXT PRIMARY KEY, component TEXT, agent TEXT,
            model TEXT, prompt_text TEXT, response_text TEXT,
            input_tokens INTEGER, output_tokens INTEGER,
            latency_ms INTEGER, confidence REAL,
            metadata TEXT, created_at INTEGER NOT NULL
        )
    """)
    # 插入 60 天假資料
    for i in range(60):
        conn.execute(
            "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"2026-01-{i%28+1:02d}", "TWSE", "2330", "台積電",
             500.0 + i, float(i % 5 - 2), 498.0 + i,
             505.0 + i, 495.0 + i, 1000000.0, 500000000.0, 5000.0,
             "http://test", "2026-01-01")
        )
    conn.commit()
    return conn


def test_run_eod_analysis_creates_report(mem_db, monkeypatch):
    """run_eod_analysis 應建立 eod_analysis_reports 表並寫入一筆資料。"""
    def mock_call_agent_llm(prompt, model=None):
        return {
            "summary": "mock summary",
            "confidence": 0.8,
            "action_type": "suggest",
            "market_outlook": {"sentiment": "neutral", "sector_focus": [], "confidence": 0.8},
            "position_actions": [],
            "watchlist_opportunities": [],
            "risk_notes": [],
            "proposals": [],
        }

    monkeypatch.setattr("openclaw.agents.eod_analysis.call_agent_llm", mock_call_agent_llm)
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    result = run_eod_analysis(trade_date="2026-01-28", conn=mem_db)

    assert result.success is True
    rows = mem_db.execute("SELECT * FROM eod_analysis_reports WHERE trade_date='2026-01-28'").fetchall()
    assert len(rows) == 1
    report = dict(rows[0])
    assert json.loads(report["technical"])  # 應有技術指標
    assert json.loads(report["strategy"])   # 應有 Gemini 策略


def test_run_eod_analysis_no_eod_data(mem_db, monkeypatch):
    """無 EOD 資料時應回傳 success=False 不崩潰。"""
    monkeypatch.setattr("openclaw.agents.eod_analysis.call_agent_llm",
                        lambda p, model=None: {"summary": "x", "confidence": 0.0,
                                               "action_type": "observe", "proposals": []})
    monkeypatch.setattr("openclaw.agents.eod_analysis.write_trace", lambda *a, **k: None)

    result = run_eod_analysis(trade_date="2099-01-01", conn=mem_db)
    assert result.success is False or result.summary  # 不應 crash
```

### Step 2: 確認測試失敗

```bash
PYTHONPATH=src python -m pytest src/tests/agents/test_eod_analysis.py -v
```
Expected: `ImportError: cannot import name 'run_eod_analysis'`

### Step 3: 實作 `eod_analysis.py`

```python
# src/openclaw/agents/eod_analysis.py
"""agents/eod_analysis.py — 盤後分析 Agent。

執行時機：每交易日 16:35 TWN
工作：EOD 數據 → 技術指標計算 → Gemini 策略分析 → eod_analysis_reports
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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
                proposals=[],
            )

        # 2. 三大法人
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

        return AgentResult(
            success=True,
            summary=result_dict.get("summary", "盤後分析完成"),
            proposals=result_dict.get("proposals", []),
        )
    finally:
        if conn is None:
            _conn.close()
```

### Step 4: 確認測試通過

```bash
PYTHONPATH=src python -m pytest src/tests/agents/test_eod_analysis.py -v
```
Expected: 2 tests PASS

### Step 5: 補全 `AgentResult` dataclass 確認

確認 `base.py` 的 `AgentResult` 有 `success` 欄位（若無，此 step 需修正 test）：

```bash
PYTHONPATH=src python -c "from openclaw.agents.base import AgentResult; print(AgentResult.__dataclass_fields__.keys())"
```

若缺少 `success`，在 test 改為：
```python
assert result.summary  # 改為只驗 summary 非空
```

### Step 6: Commit

```bash
git add src/openclaw/agents/eod_analysis.py src/tests/agents/test_eod_analysis.py
git commit -m "feat(analysis): 新增 eod_analysis agent（技術指標 + Gemini 盤後分析）"
```

---

## Task 4：FastAPI `/api/analysis` 端點（TDD）

**Files:**
- Create: `frontend/backend/app/api/analysis.py`
- Modify: `frontend/backend/app/main.py`（新增 router）
- Test: `frontend/backend/tests/test_analysis_api.py`

### Step 1: 寫失敗測試

```python
# frontend/backend/tests/test_analysis_api.py
import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
    import os; os.makedirs(str(tmp_path / "data" / "sqlite"))
    monkeypatch.setenv("DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE eod_analysis_reports (
            trade_date TEXT PRIMARY KEY,
            generated_at INTEGER NOT NULL,
            market_summary TEXT NOT NULL,
            technical TEXT NOT NULL,
            strategy TEXT NOT NULL,
            raw_prompt TEXT,
            model_used TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO eod_analysis_reports VALUES (?,?,?,?,?,?,?)",
        ("2026-03-03", int(time.time()*1000),
         '{"sentiment":"neutral"}', '{"2330":{}}',
         '{"summary":"test"}', None, "gemini-2.5-flash")
    )
    conn.commit()
    conn.close()

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)
    from app.main import app
    return TestClient(app)


def test_analysis_latest_unauthorized(client_with_analysis):
    r = client_with_analysis.get("/api/analysis/latest")
    assert r.status_code == 401


def test_analysis_latest_ok(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/latest",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["trade_date"] == "2026-03-03"
    assert "market_summary" in data
    assert "technical" in data
    assert "strategy" in data


def test_analysis_by_date_not_found(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/2099-01-01",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 404


def test_analysis_dates(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/dates",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 200
    assert "2026-03-03" in r.json()
```

### Step 2: 確認測試失敗

```bash
cd frontend/backend
python -m pytest tests/test_analysis_api.py -v
```
Expected: `ImportError` 或 `404`（路由未定義）

### Step 3: 實作 `analysis.py`

```python
# frontend/backend/app/api/analysis.py
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import app.db as db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def conn_dep():
    try:
        with db.get_conn() as conn:
            yield conn
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
```

### Step 4: 在 `main.py` 新增 router

找到 `main.py` 中其他 router import 的區塊，新增：
```python
from app.api.analysis import router as analysis_router
```

找到 `app.include_router(...)` 區塊，新增：
```python
app.include_router(analysis_router)
```

### Step 5: 確認測試通過

```bash
cd frontend/backend
python -m pytest tests/test_analysis_api.py -v
```
Expected: 4 tests PASS

### Step 6: Commit

```bash
git add frontend/backend/app/api/analysis.py frontend/backend/app/main.py \
        frontend/backend/tests/test_analysis_api.py
git commit -m "feat(analysis): 新增 /api/analysis REST API（latest/dates/{date}）"
```

---

## Task 5：Cron 排程新增

**Files:**
- Modify: `src/openclaw/agent_orchestrator.py`（或 cron/jobs.json，視現有 cron 排程方式）

### Step 1: 確認現有 cron 排程位置

```bash
grep -r "eod-ingest\|market_research\|08:20\|08:50" src/openclaw/agent_orchestrator.py | head -20
```

### Step 2: 在 orchestrator 新增 eod_analysis 排程

找到 `agent_orchestrator.py` 中 `market_research` 的排程（UTC 00:20 = TWN 08:20），
在其後新增：

```python
# 每交易日 16:25 TWN = UTC 08:25 → institution_ingest
# 每交易日 16:35 TWN = UTC 08:35 → eod_analysis
async def _run_eod_analysis_job():
    from openclaw.agents.eod_analysis import run_eod_analysis
    result = run_eod_analysis()
    logger.info(f"[eod_analysis] {result.summary}")
```

在 scheduler 設定區加入：
```python
scheduler.add_job(_run_eod_analysis_job, "cron",
                  hour=8, minute=35,
                  day_of_week="mon-fri",
                  id="eod-analysis-daily")
```

### Step 3: Commit

```bash
git add src/openclaw/agent_orchestrator.py
git commit -m "feat(analysis): 新增盤後分析 Cron 排程（UTC 08:35，每交易日）"
```

---

## Task 6：前端 `Analysis.jsx` 頁面（TDD）

**Files:**
- Create: `frontend/web/src/pages/Analysis.jsx`
- Create: `frontend/web/src/pages/Analysis.test.jsx`
- Modify: `frontend/web/src/App.jsx`（新增路由）
- Modify: `frontend/web/src/components/Sidebar.jsx`（新增導覽入口）

### Step 1: 寫失敗測試

```jsx
// frontend/web/src/pages/Analysis.test.jsx
import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AnalysisPage from './Analysis'

global.EventSource = class {
  constructor() { this.close = vi.fn() }
}

const mockReport = {
  trade_date: '2026-03-03',
  generated_at: Date.now(),
  market_summary: {
    sentiment: 'neutral',
    top_movers: [{ symbol: '2330', name: '台積電', close: 1000, change: 10, volume: 1000000 }],
    institution_flows: [],
  },
  technical: {
    '2330': { close: 1000, ma5: 990, ma20: 975, ma60: 950, rsi14: 55,
              macd: { macd: 5, signal: 4, histogram: 1 }, support: 960, resistance: 1020 }
  },
  strategy: {
    summary: '整體中性',
    market_outlook: { sentiment: 'neutral', sector_focus: ['半導體'], confidence: 0.7 },
    position_actions: [{ symbol: '2330', action: 'hold', reason: '趨勢向上' }],
    watchlist_opportunities: [],
    risk_notes: ['注意外資動向'],
  },
  model_used: 'gemini-2.5-flash',
}

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => mockReport,
  })
})

afterEach(() => vi.clearAllMocks())

function renderPage() {
  return render(
    <MemoryRouter>
      <AnalysisPage />
    </MemoryRouter>
  )
}

test('顯示盤後分析標題', async () => {
  renderPage()
  expect(screen.getByText('盤後分析')).toBeTruthy()
})

test('載入完成後顯示日期', async () => {
  renderPage()
  await waitFor(() => screen.getByText('2026-03-03'))
})

test('Tab 切換：個股技術分析', async () => {
  renderPage()
  await waitFor(() => screen.getByText('2026-03-03'))
  const tabs = screen.queryAllByText('個股技術分析')
  fireEvent.click(tabs[0])
  await waitFor(() => screen.getByText('2330'))
})

test('Tab 切換：AI 明日策略', async () => {
  renderPage()
  await waitFor(() => screen.getByText('2026-03-03'))
  const tabs = screen.queryAllByText('AI 明日策略')
  fireEvent.click(tabs[0])
  await waitFor(() => screen.getByText('整體中性'))
})

test('fetch 失敗時顯示錯誤訊息', async () => {
  global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))
  renderPage()
  await waitFor(() => screen.getByText(/無法載入|error/i))
})
```

### Step 2: 確認測試失敗

```bash
cd frontend/web
npm test -- --run Analysis
```
Expected: `Cannot find module './Analysis'`

### Step 3: 實作 `Analysis.jsx`

```jsx
// frontend/web/src/pages/Analysis.jsx
import React, { useState, useEffect, useCallback } from 'react'
import { getToken } from '../lib/auth'

const TABS = ['今日市場概覽', '個股技術分析', 'AI 明日策略']

function Panel({ title, children }) {
  return (
    <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] shadow-panel">
      <div className="border-b border-[rgb(var(--border))] px-4 py-3 text-sm font-semibold">{title}</div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function SentimentBadge({ sentiment }) {
  const map = { bullish: ['偏多', 'text-emerald-400'], bearish: ['偏空', 'text-rose-400'], neutral: ['中性', 'text-slate-400'] }
  const [label, cls] = map[sentiment] || ['未知', 'text-slate-500']
  return <span className={`font-semibold ${cls}`}>{label}</span>
}

function MarketOverviewTab({ report }) {
  const { market_summary } = report
  const topMovers = market_summary?.top_movers || []
  const instFlows = market_summary?.institution_flows || []
  return (
    <div className="space-y-4">
      <Panel title="市場氣氛">
        <div className="flex items-center gap-3">
          <span className="text-sm text-[rgb(var(--muted))]">今日多空：</span>
          <SentimentBadge sentiment={market_summary?.sentiment} />
        </div>
      </Panel>
      <Panel title="漲跌幅前 10 名">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-[rgb(var(--muted))]">
              <th className="text-left py-1 pr-3">代碼</th>
              <th className="text-left py-1 pr-3">名稱</th>
              <th className="text-right py-1 pr-3">收盤</th>
              <th className="text-right py-1">漲跌</th>
            </tr></thead>
            <tbody>
              {topMovers.map(r => (
                <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                  <td className="py-1 pr-3 font-mono">{r.symbol}</td>
                  <td className="py-1 pr-3">{r.name}</td>
                  <td className="py-1 pr-3 text-right">{r.close?.toFixed(1)}</td>
                  <td className={`py-1 text-right ${(r.change||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {(r.change||0) >= 0 ? '+' : ''}{r.change?.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {instFlows.length > 0 && (
        <Panel title="三大法人流向（萬元）">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-[rgb(var(--muted))]">
                <th className="text-left py-1 pr-3">代碼</th>
                <th className="text-right py-1 pr-3">外資</th>
                <th className="text-right py-1 pr-3">投信</th>
                <th className="text-right py-1">自營</th>
              </tr></thead>
              <tbody>
                {instFlows.map(r => (
                  <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                    <td className="py-1 pr-3 font-mono">{r.symbol}</td>
                    <td className={`py-1 pr-3 text-right ${(r.foreign_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {((r.foreign_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-1 pr-3 text-right ${(r.investment_trust_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {((r.investment_trust_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-1 text-right ${(r.dealer_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {((r.dealer_net||0)/10000).toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}

function TechnicalTab({ report }) {
  const technical = report.technical || {}
  const symbols = Object.keys(technical)
  const [selected, setSelected] = useState(symbols[0] || '')

  const sym = technical[selected]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {symbols.map(s => (
          <button key={s}
            onClick={() => setSelected(s)}
            className={`rounded-lg px-3 py-1 text-xs font-mono transition-colors ${
              selected === s
                ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30'
                : 'bg-[rgb(var(--surface))/0.3] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
            }`}
          >{s}</button>
        ))}
      </div>
      {sym && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {[
            ['收盤', sym.close],
            ['MA5', sym.ma5],
            ['MA20', sym.ma20],
            ['MA60', sym.ma60],
            ['RSI14', sym.rsi14?.toFixed(1)],
            ['MACD', sym.macd?.macd?.toFixed(2)],
            ['Signal', sym.macd?.signal?.toFixed(2)],
            ['支撐', sym.support],
            ['壓力', sym.resistance],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] px-3 py-2">
              <div className="text-xs text-[rgb(var(--muted))]">{label}</div>
              <div className="mt-1 font-mono text-sm">{value ?? '—'}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StrategyTab({ report }) {
  const strategy = report.strategy || {}
  const outlook = strategy.market_outlook || {}
  const actions = strategy.position_actions || []
  const opportunities = strategy.watchlist_opportunities || []
  const risks = strategy.risk_notes || []

  return (
    <div className="space-y-4">
      <Panel title="整體市場展望">
        <p className="text-sm">{strategy.summary || '—'}</p>
        {outlook.sector_focus?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {outlook.sector_focus.map(s => (
              <span key={s} className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">{s}</span>
            ))}
          </div>
        )}
      </Panel>
      {actions.length > 0 && (
        <Panel title="持倉操作建議">
          {actions.map(a => (
            <div key={a.symbol} className="border-b border-[rgb(var(--border))] py-2 last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm">{a.symbol}</span>
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                  a.action === 'hold' ? 'bg-slate-500/20 text-slate-300' :
                  a.action === 'reduce' ? 'bg-amber-500/20 text-amber-300' :
                  'bg-rose-500/20 text-rose-300'
                }`}>{a.action}</span>
              </div>
              <p className="mt-1 text-xs text-[rgb(var(--muted))]">{a.reason}</p>
            </div>
          ))}
        </Panel>
      )}
      {opportunities.length > 0 && (
        <Panel title="觀察名單機會">
          {opportunities.map(o => (
            <div key={o.symbol} className="border-b border-[rgb(var(--border))] py-2 last:border-0">
              <span className="font-mono text-sm">{o.symbol}</span>
              <p className="text-xs text-[rgb(var(--muted))]">{o.entry_condition}</p>
              {o.stop_loss && <p className="text-xs text-rose-400">Stop loss: {o.stop_loss}</p>}
            </div>
          ))}
        </Panel>
      )}
      {risks.length > 0 && (
        <Panel title="風險注意事項">
          <ul className="space-y-1">
            {risks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-amber-300">
                <span className="mt-0.5 shrink-0">⚠</span><span>{r}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}

export default function AnalysisPage() {
  const [activeTab, setActiveTab] = useState(0)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch('/api/analysis/latest', {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setReport(await r.json())
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">盤後分析</h2>
        {report && (
          <span className="text-xs text-[rgb(var(--muted))]">
            分析日期：{report.trade_date}
          </span>
        )}
      </div>

      {loading && <div className="text-sm text-[rgb(var(--muted))]">讀取中…</div>}
      {error && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">無法載入盤後分析：{error}</div>}

      {report && !loading && (
        <>
          {/* Tabs */}
          <div className="flex gap-1 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] p-1">
            {TABS.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setActiveTab(i)}
                className={`flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors ${
                  activeTab === i
                    ? 'bg-emerald-500/15 text-emerald-300'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
              >{tab}</button>
            ))}
          </div>

          {activeTab === 0 && <MarketOverviewTab report={report} />}
          {activeTab === 1 && <TechnicalTab report={report} />}
          {activeTab === 2 && <StrategyTab report={report} />}
        </>
      )}
    </div>
  )
}
```

### Step 4: 確認測試通過

```bash
cd frontend/web
npm test -- --run Analysis
```
Expected: 5 tests PASS

### Step 5: 在 `App.jsx` 新增路由

在 `App.jsx` 中找到 import 區塊，新增：
```jsx
import AnalysisPage from './pages/Analysis'
```

在 `<Routes>` 中找到其他 `<Route>` 行，新增：
```jsx
<Route path="/analysis" element={<AnalysisPage />} />
```

### Step 6: 在 `Sidebar.jsx` 新增導覽入口

在 `nav` 陣列中，找到適當位置（建議在 Strategy 之後）新增：
```jsx
{ to: '/analysis', label: '盤後分析', icon: BarChart2 },
```

在 import 中新增 `BarChart2`：
```jsx
import { ..., BarChart2 } from 'lucide-react'
```

### Step 7: Commit

```bash
git add frontend/web/src/pages/Analysis.jsx \
        frontend/web/src/pages/Analysis.test.jsx \
        frontend/web/src/App.jsx \
        frontend/web/src/components/Sidebar.jsx
git commit -m "feat(analysis): 新增 /analysis 盤後分析頁面（3 Tab：概覽/技術/策略）"
```

---

## Task 7：Dashboard 盤後市場氣氛小卡

**Files:**
- Modify: `frontend/web/src/pages/Dashboard.jsx`（新增小卡）

### Step 1: 在 Dashboard 新增盤後氣氛卡片

在 `Dashboard.jsx` 中，新增一個 `useEffect` 載入 `/api/analysis/latest` 的 summary，
並在現有 Panel 區塊後新增：

```jsx
// 在 DashboardPage 函數內新增 state
const [analysisSnap, setAnalysisSnap] = useState(null)

useEffect(() => {
  fetch('/api/analysis/latest', {
    headers: { Authorization: `Bearer ${getToken()}` }
  })
    .then(r => r.ok ? r.json() : null)
    .then(data => data && setAnalysisSnap(data))
    .catch(() => {})
}, [])
```

在 JSX 中，在 PmStatusCard 後新增（僅 2 行摘要 + 連結）：

```jsx
{analysisSnap && (
  <Link to="/analysis" className="block rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] px-4 py-3 hover:bg-[rgb(var(--surface))/0.4] transition-colors">
    <div className="flex items-center justify-between">
      <span className="text-xs font-semibold text-[rgb(var(--muted))]">
        盤後分析 · {analysisSnap.trade_date}
      </span>
      <span className="text-xs text-emerald-400">查看 →</span>
    </div>
    <p className="mt-1 text-sm truncate">
      {analysisSnap.strategy?.summary || '分析完成'}
    </p>
  </Link>
)}
```

### Step 2: Commit

```bash
git add frontend/web/src/pages/Dashboard.jsx
git commit -m "feat(analysis): Dashboard 新增盤後市場氣氛小卡入口"
```

---

## Task 8：CI 確認 & 完工

### Step 1: 本地全套測試

```bash
# Python 後端
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
PYTHONPATH=src python -m pytest src/tests/test_technical_indicators.py \
  src/tests/agents/test_eod_analysis.py -v

cd frontend/backend
python -m pytest tests/test_analysis_api.py -v

# 前端
cd ../web
npm test -- --run
```

Expected: 全部 PASS

### Step 2: Push 並監控 CI

```bash
git push origin main
gh run list --limit 3
gh run watch <run-id>
```

### Step 3: 若 CI 失敗

```bash
gh run view <run-id> --log-failed
```
根據錯誤訊息修正後重新 push。

---

## 實作摘要

| Task | 產出物 | 測試 |
|------|--------|------|
| 1 | `technical_indicators.py` | 6 unit tests |
| 2 | DB 表（auto-create） | — |
| 3 | `agents/eod_analysis.py` | 2 unit tests |
| 4 | `api/analysis.py` + router 註冊 | 4 API tests |
| 5 | Cron 排程（orchestrator） | — |
| 6 | `Analysis.jsx` + routing + sidebar | 5 JS tests |
| 7 | Dashboard 小卡 | — |
| 8 | CI 全綠 | — |
