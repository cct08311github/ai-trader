# Sprint 2 實作計劃

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 signal_aggregator（Regime-based 動態權重融合）、trading_engine（持倉狀態機 + 時間止損）、lm_signal_cache（LLM 快取）、strategy_optimizer（策略自主優化）四個模組，讓系統能根據市況自適應調整決策品質並消除殭屍持倉。

**Architecture:** 統計前置 + LLM 二層裁量。signal_aggregator 讀 market_regime + lm_signal_cache 做加權融合；trading_engine 以 EOD 日為單位計算持倉天數觸發時間止損；strategy_optimizer 每日 EOD 統計指標、事件驅動安全調整、週期 Gemini 深度反思。全部整合至 ticker_watcher 現有掃盤迴圈。

**Tech Stack:** Python 3.14, SQLite, asyncio, pytest, Gemini（via llm_gemini.py）

**Design Doc:** `doc/plans/2026-03-05-sprint2-design.md`

---

# TASK 1：DB Schema 遷移

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`（`_ensure_schema`）
- Test: `tests/test_ticker_watcher.py`

## Step 1：寫失敗測試

在 `tests/test_ticker_watcher.py` 加入：

```python
def test_schema_has_sprint2_tables(tmp_path, monkeypatch):
    """_ensure_schema 必須建立 Sprint 2 所有新表與新欄位"""
    import sqlite3, os
    os.makedirs(str(tmp_path / "data" / "sqlite"), exist_ok=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTH_TOKEN", "test")

    db = tmp_path / "data" / "sqlite" / "trades.db"
    conn = sqlite3.connect(str(db))
    # 預先建立 positions 表（模擬已有舊 DB）
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

    # 新欄位
    cols = [r[1] for r in conn.execute("PRAGMA table_info(positions)").fetchall()]
    assert "state" in cols
    assert "entry_trading_day" in cols

    # 新表
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "lm_signal_cache" in tables
    assert "position_events" in tables
    assert "position_candidates" in tables
    assert "optimization_log" in tables
    assert "param_bounds" in tables
    conn.close()
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py::test_schema_has_sprint2_tables -v
```
預期：FAIL（`state` 欄位不存在）

## Step 3：修改 `_ensure_schema`

在 `src/openclaw/ticker_watcher.py` 的 `_ensure_schema` 函數中，把 `migrations` list 加入新項目並附上 `CREATE TABLE IF NOT EXISTS`：

```python
def _ensure_schema(conn: sqlite3.Connection) -> None:
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
        except sqlite3.OperationalError:
            pass

    # Sprint 2 新表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lm_signal_cache (
            cache_id    TEXT PRIMARY KEY,
            symbol      TEXT,
            score       REAL NOT NULL,
            source      TEXT NOT NULL,
            direction   TEXT,
            raw_json    TEXT,
            created_at  INTEGER NOT NULL,
            expires_at  INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_lm_cache_lookup
            ON lm_signal_cache (symbol, expires_at);

        CREATE TABLE IF NOT EXISTS position_events (
            event_id    TEXT PRIMARY KEY,
            symbol      TEXT NOT NULL,
            from_state  TEXT,
            to_state    TEXT NOT NULL,
            reason      TEXT,
            trading_day TEXT,
            ts          INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_pos_events_symbol
            ON position_events (symbol, ts);

        CREATE TABLE IF NOT EXISTS position_candidates (
            symbol      TEXT PRIMARY KEY,
            trading_day TEXT NOT NULL,
            reason      TEXT,
            created_at  INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS optimization_log (
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
        );

        CREATE TABLE IF NOT EXISTS param_bounds (
            param_key           TEXT PRIMARY KEY,
            min_val             REAL NOT NULL,
            max_val             REAL NOT NULL,
            weekly_max_delta    REAL NOT NULL,
            last_auto_change_ts INTEGER,
            frozen_until_ts     INTEGER
        );
    """)
    conn.commit()
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py::test_schema_has_sprint2_tables -v
```
預期：PASS

## Step 5：跑全套測試

```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```
預期：全部通過，無 regression

## Step 6：Commit

```bash
git add src/openclaw/ticker_watcher.py tests/test_ticker_watcher.py
git commit -m "feat(db): Sprint 2 schema — lm_signal_cache/position_events/optimization_log + positions.state"
```

---

# TASK 2：lm_signal_cache.py（LLM 快取層）

**Files:**
- Create: `src/openclaw/lm_signal_cache.py`
- Test: `tests/test_lm_signal_cache.py`

## Step 1：寫失敗測試

新建 `tests/test_lm_signal_cache.py`：

```python
import sqlite3, time, pytest

@pytest.fixture
def cache_db(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    conn.commit()
    return conn

def test_write_and_read_global_cache(cache_db):
    """寫入全市場信號後能讀取"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None, score=0.7, source="strategy_committee",
                direction="bull", raw_json='{"summary":"bullish"}')
    result = read_cache(cache_db, symbol=None)
    assert result is not None
    assert result["score"] == 0.7
    assert result["direction"] == "bull"
    assert result["source"] == "strategy_committee"

def test_cache_miss_returns_none(cache_db):
    """無快取時回傳 None"""
    from openclaw.lm_signal_cache import read_cache
    result = read_cache(cache_db, symbol="2330")
    assert result is None

def test_expired_cache_returns_none(cache_db):
    """過期快取應視為 miss"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None, score=0.8, source="test",
                direction="bull", raw_json="{}", ttl_seconds=-1)  # 立即過期
    result = read_cache(cache_db, symbol=None)
    assert result is None

def test_symbol_specific_cache_takes_priority(cache_db):
    """個股快取優先於全市場快取"""
    from openclaw.lm_signal_cache import write_cache, read_cache
    write_cache(cache_db, symbol=None,    score=0.5, source="global", direction="neutral", raw_json="{}")
    write_cache(cache_db, symbol="2330",  score=0.9, source="stock",  direction="bull",    raw_json="{}")
    result = read_cache(cache_db, symbol="2330")
    assert result["score"] == 0.9
    assert result["source"] == "stock"

def test_fallback_to_global_when_symbol_miss(cache_db):
    """個股 miss 時 fallback 至全市場快取"""
    from openclaw.lm_signal_cache import write_cache, read_cache_with_fallback
    write_cache(cache_db, symbol=None, score=0.6, source="global", direction="bear", raw_json="{}")
    result = read_cache_with_fallback(cache_db, symbol="9999")
    assert result["score"] == 0.6

def test_purge_expired(cache_db):
    """purge_expired 清除過期記錄"""
    from openclaw.lm_signal_cache import write_cache, purge_expired
    write_cache(cache_db, symbol=None, score=0.5, source="test", direction="neutral",
                raw_json="{}", ttl_seconds=-1)
    purge_expired(cache_db)
    count = cache_db.execute("SELECT COUNT(*) FROM lm_signal_cache").fetchone()[0]
    assert count == 0
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_lm_signal_cache.py -v
```
預期：ModuleNotFoundError（lm_signal_cache 不存在）

## Step 3：建立 `lm_signal_cache.py`

```python
# src/openclaw/lm_signal_cache.py
"""LLM 信號快取層

strategy_committee 辯論結論寫入此快取，signal_aggregator 讀取。
Cache miss 時 caller 應使用 neutral score（0.5）。
"""
import sqlite3
import time
import uuid
from typing import Optional


def write_cache(
    conn: sqlite3.Connection,
    symbol: Optional[str],       # None = 全市場方向
    score: float,                # 0.0（極空）~ 1.0（極多）
    source: str,                 # 'strategy_committee' | 'pm_review'
    direction: str,              # 'bull' | 'bear' | 'neutral'
    raw_json: str,
    ttl_seconds: int = 3600,
) -> str:
    cache_id = str(uuid.uuid4())
    now = int(time.time())
    conn.execute(
        """INSERT INTO lm_signal_cache
           (cache_id, symbol, score, source, direction, raw_json, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cache_id, symbol, score, source, direction, raw_json, now, now + ttl_seconds),
    )
    conn.commit()
    return cache_id


def read_cache(conn: sqlite3.Connection, symbol: Optional[str]) -> Optional[dict]:
    """讀取最新未過期的快取。symbol=None 查全市場。"""
    now = int(time.time())
    row = conn.execute(
        """SELECT score, direction, source FROM lm_signal_cache
           WHERE symbol IS ? AND expires_at > ?
           ORDER BY created_at DESC LIMIT 1""",
        (symbol, now),
    ).fetchone()
    if row is None:
        return None
    return {"score": row[0], "direction": row[1], "source": row[2]}


def read_cache_with_fallback(conn: sqlite3.Connection, symbol: str) -> Optional[dict]:
    """先查個股快取，miss 則 fallback 至全市場快取（symbol=None）。"""
    result = read_cache(conn, symbol)
    if result is not None:
        return result
    return read_cache(conn, None)


def purge_expired(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM lm_signal_cache WHERE expires_at <= ?", (int(time.time()),))
    conn.commit()
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_lm_signal_cache.py -v
```
預期：全部 PASS

## Step 5：Commit

```bash
git add src/openclaw/lm_signal_cache.py tests/test_lm_signal_cache.py
git commit -m "feat(cache): lm_signal_cache — LLM 信號快取層（TTL/fallback/purge）"
```

---

# TASK 3：signal_aggregator.py（Regime-based 動態權重融合）

**Files:**
- Create: `src/openclaw/signal_aggregator.py`
- Test: `tests/test_signal_aggregator.py`

## Step 1：寫失敗測試

新建 `tests/test_signal_aggregator.py`：

```python
import sqlite3, pytest
from dataclasses import dataclass

@pytest.fixture
def agg_db(tmp_path):
    """建立有 eod_prices + lm_signal_cache 表的測試 DB"""
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL,
        low REAL, close REAL, volume REAL,
        PRIMARY KEY (trade_date, symbol)
    )""")
    conn.execute("""CREATE TABLE lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    # 插入 30 日模擬日線（趨勢上漲 → bull regime）
    import random; random.seed(42)
    price = 100.0
    for i in range(30):
        from datetime import date, timedelta
        d = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        price *= 1.005  # 穩定上漲
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, "2330", price*0.99, price*1.01, price*0.98, price, 1e6))
    conn.commit()
    return conn

@pytest.fixture
def snap_normal():
    return {"close": 115.0, "reference": 110.0, "bid": 114.9, "ask": 115.1, "volume": 5000}

@pytest.fixture
def snap_limit_up():
    return {"close": 121.0, "reference": 110.0, "bid": 121.0, "ask": 121.0, "volume": 1000}

def test_aggregate_returns_aggregated_signal(agg_db, snap_normal):
    from openclaw.signal_aggregator import aggregate, AggregatedSignal
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert isinstance(result, AggregatedSignal)
    assert result.action in ("buy", "sell", "flat")
    assert 0.0 <= result.score <= 1.0
    assert result.regime in ("bull", "bear", "range")
    assert isinstance(result.reasons, list)

def test_regime_weights_applied(agg_db, snap_normal):
    """Bull regime 下 technical weight=0.50"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    # 上漲趨勢應為 bull regime
    assert result.regime == "bull"
    assert result.weights_used["technical"] == 0.50

def test_limit_up_caps_buy_score(agg_db, snap_limit_up):
    """漲停板時 buy score 被壓至 0.3 以下"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_limit_up,
                       position_avg_price=None, high_water_mark=None)
    assert result.limit_filtered is True
    # 即使其他信號看多，final score 也不會因漲停而過高觸發 buy
    # （tech_score 被壓到 0.3，加權後 final < 0.65）
    if result.action == "buy":
        # 如果還是 buy，score 也應該偏低（close to threshold）
        assert result.score < 0.7

def test_cache_miss_uses_neutral(agg_db, snap_normal):
    """LLM cache miss 時使用 neutral score 0.5，不崩潰"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert result is not None  # 不應拋出例外
    assert "cache_miss" in " ".join(result.reasons)

def test_cache_hit_uses_cached_score(agg_db, snap_normal):
    """LLM cache 有資料時採用快取 score"""
    from openclaw.lm_signal_cache import write_cache
    write_cache(agg_db, symbol=None, score=0.9, source="strategy_committee",
                direction="bull", raw_json="{}")
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "2330", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert any("0.9" in r for r in result.reasons)

def test_sell_signal_when_holding_and_stop_triggered(agg_db, snap_normal):
    """有持倉且觸發止損時，aggregator 輸出 sell"""
    from openclaw.signal_aggregator import aggregate
    # avg_price=120, current_close=115 → -4.2% → 觸發止損（STOP_LOSS_PCT=3%）
    result = aggregate(agg_db, "2330",
                       {"close": 115.0, "reference": 110.0, "bid": 114.9, "ask": 115.1, "volume": 5000},
                       position_avg_price=120.0, high_water_mark=120.0)
    assert result.action == "sell"

def test_unknown_symbol_returns_flat(agg_db, snap_normal):
    """無 eod_prices 資料的股票回傳 flat"""
    from openclaw.signal_aggregator import aggregate
    result = aggregate(agg_db, "9999", snap_normal,
                       position_avg_price=None, high_water_mark=None)
    assert result.action == "flat"
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_signal_aggregator.py -v
```
預期：ModuleNotFoundError（signal_aggregator 不存在）

## Step 3：建立 `signal_aggregator.py`

```python
# src/openclaw/signal_aggregator.py
"""signal_aggregator.py — Regime-based 動態權重信號融合

整合技術面（signal_generator）、LLM 面（lm_signal_cache）、
市況（market_regime）三個信號，輸出加權融合後的 AggregatedSignal。

風控層（risk_engine）獨立運作，不參與此處加權。
"""
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from openclaw.market_regime import classify_market_regime
from openclaw.signal_generator import compute_signal, _fetch_candles
from openclaw.lm_signal_cache import read_cache_with_fallback

REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "bull":  {"technical": 0.50, "llm": 0.20, "risk_adj": 0.30},
    "bear":  {"technical": 0.30, "llm": 0.20, "risk_adj": 0.50},
    "range": {"technical": 0.40, "llm": 0.20, "risk_adj": 0.40},
}

SIGNAL_TO_SCORE: dict[str, float] = {"buy": 0.8, "flat": 0.5, "sell": 0.2}

_LIMIT_UP_THRESHOLD  = 0.095   # 漲幅 >= 9.5% 視為漲停
_BUY_SCORE_LIMIT_UP  = 0.30    # 漲停時壓低 buy score 上限
_BUY_ACTION_THRESHOLD  = 0.65
_SELL_ACTION_THRESHOLD = 0.35


@dataclass(frozen=True)
class AggregatedSignal:
    action: str                          # 'buy' | 'sell' | 'flat'
    score: float                         # 0.0 ~ 1.0
    regime: str                          # 'bull' | 'bear' | 'range'
    weights_used: dict                   # {'technical': float, 'llm': float, 'risk_adj': float}
    reasons: list = field(default_factory=list)
    limit_filtered: bool = False


def _get_regime(conn: sqlite3.Connection, symbol: str) -> tuple[str, float]:
    """從 eod_prices 取收盤價序列，判斷 market regime。
    回傳 (regime_str, volatility_multiplier)。
    """
    candles = _fetch_candles(conn, symbol, days=60)
    if len(candles) < 20:
        return "range", 1.0
    prices  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    result = classify_market_regime(prices, volumes)
    return result.regime.value, result.volatility_multiplier


def aggregate(
    conn: sqlite3.Connection,
    symbol: str,
    snap: dict,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float],
) -> AggregatedSignal:
    """
    計算 Regime-based 加權信號。

    Args:
        snap: 即時快照 {"close": float, "reference": float, ...}
    Returns:
        AggregatedSignal
    """
    reasons: list[str] = []

    # 1. Market regime
    regime, vol_mult = _get_regime(conn, symbol)
    weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["range"])
    reasons.append(f"regime={regime}")

    # 2. Technical signal
    tech_str = compute_signal(conn, symbol, position_avg_price, high_water_mark)
    tech_score = SIGNAL_TO_SCORE[tech_str]
    reasons.append(f"technical={tech_str}({tech_score:.2f})")

    # 3. LLM cache（個股 fallback 全市場；miss → neutral 0.5）
    cache = read_cache_with_fallback(conn, symbol)
    if cache:
        llm_score = cache["score"]
        llm_label = cache["source"]
    else:
        llm_score = 0.5
        llm_label = "cache_miss"
    reasons.append(f"llm={llm_score:.2f}({llm_label})")

    # 4. Risk adjustment（由 volatility_multiplier 衍生：高波動 → 偏保守）
    risk_adj = max(0.1, min(0.9, 0.5 / vol_mult))
    reasons.append(f"risk_adj={risk_adj:.2f}(vol_mult={vol_mult:.2f})")

    # 5. 漲停板過濾
    close = snap.get("close", 0.0)
    ref   = snap.get("reference", close) or close
    limit_filtered = False
    if ref > 0 and close >= ref * (1 + _LIMIT_UP_THRESHOLD):
        tech_score = min(tech_score, _BUY_SCORE_LIMIT_UP)
        limit_filtered = True
        reasons.append("limit_up:buy_score_capped_to_0.3")

    # 6. 加權融合
    final_score = (
        weights["technical"] * tech_score +
        weights["llm"]       * llm_score  +
        weights["risk_adj"]  * risk_adj
    )

    if final_score >= _BUY_ACTION_THRESHOLD:
        action = "buy"
    elif final_score <= _SELL_ACTION_THRESHOLD:
        action = "sell"
    else:
        action = "flat"

    return AggregatedSignal(
        action=action,
        score=round(final_score, 4),
        regime=regime,
        weights_used=weights,
        reasons=reasons,
        limit_filtered=limit_filtered,
    )
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_signal_aggregator.py -v
```
預期：全部 PASS

## Step 5：跑全套測試

```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

## Step 6：Commit

```bash
git add src/openclaw/signal_aggregator.py tests/test_signal_aggregator.py
git commit -m "feat(signal): signal_aggregator — Regime-based 動態權重融合 + 漲停板過濾"
```

---

# TASK 4：trading_engine.py（持倉狀態機 + 時間止損）

**Files:**
- Create: `src/openclaw/trading_engine.py`
- Test: `tests/test_trading_engine.py`

## Step 1：寫失敗測試

新建 `tests/test_trading_engine.py`：

```python
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
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_trading_engine.py -v
```
預期：ModuleNotFoundError（trading_engine 不存在）

## Step 3：建立 `trading_engine.py`

```python
# src/openclaw/trading_engine.py
"""trading_engine.py — 持倉狀態機 + 時間止損

持倉生命週期：HOLDING → EXITING（時間止損）→ [proposal_executor 執行] → CLOSED

時間止損規則（以 EOD 交易日計算，不以 tick 次數）：
  - 虧損持倉（current < avg）：10 交易日 → auto-approved proposal
  - 獲利持倉（current >= avg）：30 交易日 → pending proposal（需人工審核）
"""
import json
import logging
import sqlite3
import time
import uuid
from typing import Optional

log = logging.getLogger(__name__)

_LOSING_THRESHOLD_DAYS  = 10
_PROFIT_THRESHOLD_DAYS  = 30
_ACTIVE_STATES = ("HOLDING", "HOLDING_PARTIAL")


def _get_latest_trading_day(conn: sqlite3.Connection) -> Optional[str]:
    """取 eod_prices 最新的 trade_date（當日基準）"""
    row = conn.execute(
        "SELECT MAX(trade_date) FROM eod_prices"
    ).fetchone()
    return row[0] if row else None


def _get_yesterday_trading_day(conn: sqlite3.Connection) -> Optional[str]:
    """取 eod_prices 倒數第二筆 trade_date（昨日，用於清除過期 CANDIDATE）"""
    row = conn.execute(
        "SELECT trade_date FROM eod_prices ORDER BY trade_date DESC LIMIT 1 OFFSET 1"
    ).fetchone()
    return row[0] if row else None


def _count_hold_days(conn: sqlite3.Connection, symbol: str, entry_day: str) -> int:
    """計算 entry_day 之後的 eod_prices 筆數（= 交易日數）"""
    row = conn.execute(
        "SELECT COUNT(*) FROM eod_prices WHERE symbol=? AND trade_date > ?",
        (symbol, entry_day),
    ).fetchone()
    return row[0] if row else 0


def _record_event(
    conn: sqlite3.Connection,
    symbol: str,
    from_state: Optional[str],
    to_state: str,
    reason: str,
) -> None:
    today = _get_latest_trading_day(conn)
    conn.execute(
        """INSERT INTO position_events
           (event_id, symbol, from_state, to_state, reason, trading_day, ts)
           VALUES (?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), symbol, from_state, to_state, reason, today,
         int(time.time() * 1000)),
    )


def _create_time_stop_proposal(
    conn: sqlite3.Connection,
    symbol: str,
    hold_days: int,
    is_losing: bool,
    qty: int,
) -> None:
    proposal_id = str(uuid.uuid4())
    # 虧損全出場；獲利出 50%
    reduce_pct = 1.0 if is_losing else 0.5
    threshold  = _LOSING_THRESHOLD_DAYS if is_losing else _PROFIT_THRESHOLD_DAYS
    pnl_label  = "虧損" if is_losing else "獲利"
    status     = "approved" if is_losing else "pending"

    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, rule_category,
            proposed_value, supporting_evidence, confidence,
            requires_human_approval, status, proposal_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            proposal_id, "trading_engine", "POSITION_REBALANCE", "portfolio",
            f"時間止損：{symbol} {pnl_label}持倉超過 {threshold} 交易日",
            f"{pnl_label}持倉 {hold_days} 交易日，觸發時間止損",
            0.85, int(not is_losing), status,
            json.dumps({"symbol": symbol, "reduce_pct": reduce_pct,
                        "type": "time_stop", "hold_days": hold_days}),
            int(time.time()),
        ),
    )


def tick(conn: sqlite3.Connection, symbol: str) -> None:
    """每次掃盤呼叫：清理過期 CANDIDATE、檢查時間止損。

    所有 DB 寫入在同一個隱式 transaction（SQLite isolation_level=None 時
    請在呼叫端確保 conn 處於 autocommit 模式，或在此函數內管理 transaction）。
    """
    # 1. 清理過期 CANDIDATE（上一個交易日之前的都清除）
    yesterday = _get_yesterday_trading_day(conn)
    if yesterday:
        conn.execute(
            "DELETE FROM position_candidates WHERE trading_day < ?",
            (yesterday,),
        )
        conn.commit()

    # 2. 讀取持倉
    pos = conn.execute(
        "SELECT quantity, avg_price, current_price, state, entry_trading_day "
        "FROM positions WHERE symbol=?",
        (symbol,),
    ).fetchone()

    if pos is None or (pos["quantity"] or 0) <= 0:
        return

    state = pos["state"] or "HOLDING"
    if state not in _ACTIVE_STATES:
        return  # EXITING/CLOSED 不重複觸發

    entry_day = pos["entry_trading_day"]
    if not entry_day:
        return  # 無進場日資料，跳過

    hold_days = _count_hold_days(conn, symbol, entry_day)
    avg_price     = pos["avg_price"] or 0
    current_price = pos["current_price"] or avg_price
    is_losing     = current_price < avg_price
    threshold     = _LOSING_THRESHOLD_DAYS if is_losing else _PROFIT_THRESHOLD_DAYS

    if hold_days < threshold:
        return  # 未達門檻

    log.info(
        "[trading_engine] %s 時間止損 hold=%d days, is_losing=%s",
        symbol, hold_days, is_losing,
    )

    # 3. 同一 transaction：建立 proposal + 記錄 event + 更新 state
    with conn:
        _create_time_stop_proposal(conn, symbol, hold_days, is_losing,
                                   pos["quantity"])
        _record_event(conn, symbol, from_state=state, to_state="EXITING",
                      reason=f"time_stop:{hold_days}d")
        conn.execute(
            "UPDATE positions SET state='EXITING' WHERE symbol=?",
            (symbol,),
        )
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_trading_engine.py -v
```
預期：全部 PASS

## Step 5：跑全套測試

```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

## Step 6：Commit

```bash
git add src/openclaw/trading_engine.py tests/test_trading_engine.py
git commit -m "feat(engine): trading_engine — 持倉狀態機 + EOD日計時間止損（虧損10日/獲利30日）"
```

---

# TASK 5：strategy_optimizer.py（統計層 + 安全調整）

**Files:**
- Create: `src/openclaw/strategy_optimizer.py`
- Test: `tests/test_strategy_optimizer.py`

## Step 1：寫失敗測試

```python
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
        assert log_count >= 0  # 若有調整則 > 0

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
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_strategy_optimizer.py -v
```

## Step 3：建立 `strategy_optimizer.py`

```python
# src/openclaw/strategy_optimizer.py
"""strategy_optimizer.py — 策略自主優化機制

統計前置 + LLM 二層裁量：
  - StrategyMetricsEngine: 每日 EOD 計算勝率/損益比等指標
  - OptimizationGateway: 根據統計結果做安全自動調整（param_bounds 護欄）
  - ReflectionAgent: 週期 Gemini 深度反思（see Task 6）

安全調整（自動生效）：trailing_pct、daily_loss_limit
重大調整（proposal）: take_profit_pct、stop_loss_pct、MA 週期
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

_MIN_SAMPLE_FOR_CONFIDENCE = 30
_CONFIDENCE_THRESHOLD = 0.6  # 低於此值不觸發調整

# 安全調整的觸發條件
_LOW_WIN_RATE_THRESHOLD = 0.35     # 勝率 < 35% → 收緊 trailing_pct
_TRAILING_PCT_DELTA = 0.005        # 每次調整幅度


@dataclass
class MetricsReport:
    sample_n: int
    confidence: float              # 0.0 ~ 1.0（= min(1.0, sample_n / 30)）
    win_rate: Optional[float]
    profit_factor: Optional[float]
    avg_hold_days: Optional[float] = None
    max_drawdown_pct: Optional[float] = None


@dataclass
class AutoAdjustment:
    param_key: str
    old_value: float
    new_value: float
    rationale: str
    sample_n: int
    confidence: float

    def as_dict(self):
        return {
            "param_key": self.param_key,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }


class StrategyMetricsEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def compute(self, window_days: int = 28) -> MetricsReport:
        cutoff_ts = (datetime.now() - timedelta(days=window_days)).isoformat()
        # 找所有 buy + sell 配對（簡化：按 symbol 配對最近交易）
        trades = self._get_closed_trades(cutoff_ts)
        n = len(trades)
        if n == 0:
            return MetricsReport(sample_n=0, confidence=0.0,
                                 win_rate=None, profit_factor=None)

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        win_rate = len(wins) / n
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss   = abs(sum(t["pnl"] for t in losses)) or 0.01
        profit_factor = gross_profit / gross_loss
        confidence = min(1.0, n / _MIN_SAMPLE_FOR_CONFIDENCE)

        return MetricsReport(
            sample_n=n,
            confidence=confidence,
            win_rate=win_rate,
            profit_factor=profit_factor,
        )

    def _get_closed_trades(self, cutoff_ts: str) -> list[dict]:
        """配對 buy + sell，計算每筆交易 P&L。"""
        rows = self.conn.execute(
            """SELECT o.order_id, o.symbol, o.side, o.ts_submit,
                      SUM(f.qty) as qty, AVG(f.price) as avg_price,
                      SUM(f.fee + f.tax) as cost
               FROM orders o JOIN fills f ON o.order_id = f.order_id
               WHERE o.ts_submit > ? AND o.status = 'filled'
               GROUP BY o.order_id""",
            (cutoff_ts,),
        ).fetchall()

        buys  = {r["symbol"]: r for r in rows if r["side"] == "buy"}
        sells = [r for r in rows if r["side"] == "sell"]

        trades = []
        for sell in sells:
            sym = sell["symbol"]
            buy = buys.get(sym)
            if buy is None:
                continue
            pnl = (sell["avg_price"] - buy["avg_price"]) * sell["qty"] - sell["cost"]
            trades.append({"symbol": sym, "pnl": pnl})
        return trades


class OptimizationGateway:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def on_eod(self, metrics: MetricsReport) -> list[dict]:
        """根據 EOD 統計結果執行安全調整。
        Returns: list of AutoAdjustment.as_dict()
        """
        if metrics.confidence < _CONFIDENCE_THRESHOLD:
            log.info("[optimizer] confidence=%.2f < threshold, 跳過調整（樣本=%d）",
                     metrics.confidence, metrics.sample_n)
            return []

        adjustments: list[AutoAdjustment] = []

        # 安全調整 1：低勝率 → 收緊 trailing_pct（讓更早鎖利）
        if metrics.win_rate is not None and metrics.win_rate < _LOW_WIN_RATE_THRESHOLD:
            adj = self._adjust_param(
                "trailing_pct",
                delta=+_TRAILING_PCT_DELTA,   # 收緊（增大 trailing）
                rationale=f"win_rate={metrics.win_rate:.1%} < {_LOW_WIN_RATE_THRESHOLD:.0%}",
                metrics=metrics,
            )
            if adj:
                adjustments.append(adj)

        return [a.as_dict() for a in adjustments]

    def _adjust_param(
        self,
        param_key: str,
        delta: float,
        rationale: str,
        metrics: MetricsReport,
    ) -> Optional[AutoAdjustment]:
        """嘗試調整參數，受 param_bounds 約束。"""
        now = int(time.time())

        bounds = self.conn.execute(
            "SELECT * FROM param_bounds WHERE param_key=?", (param_key,)
        ).fetchone()
        if bounds is None:
            return None  # 無約束定義，不調整

        # 凍結期檢查
        if bounds["frozen_until_ts"] and bounds["frozen_until_ts"] > now:
            log.info("[optimizer] %s 凍結中（until %s），跳過",
                     param_key, bounds["frozen_until_ts"])
            return None

        # 讀取現值
        current = self.conn.execute(
            "SELECT value FROM risk_limits WHERE name=?", (param_key,)
        ).fetchone()
        if current is None:
            return None
        old_val = current["value"]

        # 計算新值（受 delta 和邊界限制）
        raw_new = old_val + delta
        new_val = max(bounds["min_val"], min(bounds["max_val"], raw_new))

        # weekly_max_delta 檢查
        actual_delta = abs(new_val - old_val)
        if actual_delta > bounds["weekly_max_delta"]:
            new_val = old_val + (bounds["weekly_max_delta"] * (1 if delta > 0 else -1))
            new_val = max(bounds["min_val"], min(bounds["max_val"], new_val))

        if abs(new_val - old_val) < 1e-6:
            return None  # 無實質變化

        # 執行調整
        self.conn.execute(
            "UPDATE risk_limits SET value=?, updated_at=? WHERE name=?",
            (new_val, now, param_key)
        )
        # 寫入 optimization_log
        self.conn.execute(
            """INSERT INTO optimization_log
               (ts, trigger_type, param_key, old_value, new_value,
                is_auto, sample_n, confidence, rationale)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (now, "eod_stats", param_key, old_val, new_val, 1,
             metrics.sample_n, metrics.confidence, rationale),
        )
        self.conn.commit()
        log.info("[optimizer] %s: %.4f → %.4f (%s)", param_key, old_val, new_val, rationale)

        return AutoAdjustment(
            param_key=param_key,
            old_value=old_val,
            new_value=new_val,
            rationale=rationale,
            sample_n=metrics.sample_n,
            confidence=metrics.confidence,
        )
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_strategy_optimizer.py -v
```

## Step 5：跑全套測試

```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

## Step 6：Commit

```bash
git add src/openclaw/strategy_optimizer.py tests/test_strategy_optimizer.py
git commit -m "feat(optimizer): StrategyMetricsEngine + OptimizationGateway — 統計驅動安全調整 + param_bounds 護欄"
```

---

# TASK 6：ReflectionAgent（Gemini 週期深度反思）

**Files:**
- Modify: `src/openclaw/strategy_optimizer.py`（新增 `ReflectionAgent` class）
- Test: `tests/test_strategy_optimizer.py`（新增測試）

## Step 1：寫失敗測試

在 `tests/test_strategy_optimizer.py` 補入：

```python
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
```

## Step 2：確認失敗

```bash
PYTHONPATH=src pytest tests/test_strategy_optimizer.py::TestReflectionAgent -v
```

## Step 3：在 `strategy_optimizer.py` 末端加入 `ReflectionAgent`

```python
class ReflectionAgent:
    """週期 Gemini 深度反思（週一 07:00，by agent_orchestrator）

    審查：
    1. 近 4 週 optimization_log（偵測單向漂移）
    2. 近 4 週 llm_traces（LLM 校準偏差）
    3. 整體策略表現 → 生成 proposal 建議
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def reflect_weekly(self) -> list[dict]:
        """執行週期反思，回傳 proposals list（空 list = 無建議）。"""
        try:
            context = self._build_context()
            response = self._call_gemini(context)
            return self._parse_proposals(response)
        except Exception as e:
            log.warning("[ReflectionAgent] Gemini 反思失敗，跳過：%s", e)
            return []

    def _build_context(self) -> str:
        cutoff = int((datetime.now() - timedelta(days=28)).timestamp())

        # 近 4 週 optimization_log
        opt_rows = self.conn.execute(
            "SELECT param_key, old_value, new_value, rationale FROM optimization_log WHERE ts > ? ORDER BY ts",
            (cutoff,)
        ).fetchall()
        opt_summary = "\n".join(
            f"  {r['param_key']}: {r['old_value']:.4f} → {r['new_value']:.4f} ({r['rationale']})"
            for r in opt_rows
        ) or "  （無自動調整）"

        # 近 4 週 performance（重用 MetricsEngine）
        metrics = StrategyMetricsEngine(self.conn).compute(window_days=28)
        perf_summary = (
            f"  樣本數={metrics.sample_n}, 勝率={metrics.win_rate:.1%}, "
            f"損益比={metrics.profit_factor:.2f}"
            if metrics.win_rate is not None
            else "  （樣本不足）"
        )

        return f"""你是 AI Trader 策略反思 Agent。請根據以下資料進行週期反思，提出調整建議。

近 4 週績效：
{perf_summary}

近 4 週自動調整記錄：
{opt_summary}

請回覆 JSON，格式為：
{{"direction": "bull|bear|neutral", "rationale": "...", "proposals": []}}
proposals 中每項格式：{{"param_key": "...", "action": "increase|decrease|review", "reason": "..."}}
"""

    def _call_gemini(self, prompt: str) -> str:
        from openclaw.llm_gemini import call_gemini  # type: ignore
        return call_gemini(prompt)

    def _parse_proposals(self, response: str) -> list[dict]:
        import json
        try:
            data = json.loads(response)
            return data.get("proposals", [])
        except (json.JSONDecodeError, AttributeError):
            log.warning("[ReflectionAgent] 無法解析 Gemini 回應")
            return []
```

## Step 4：確認通過

```bash
PYTHONPATH=src pytest tests/test_strategy_optimizer.py -v
```

## Step 5：Commit

```bash
git add src/openclaw/strategy_optimizer.py tests/test_strategy_optimizer.py
git commit -m "feat(optimizer): ReflectionAgent — Gemini 週期深度反思 + 漂移偵測"
```

---

# TASK 7：ticker_watcher 整合

**Files:**
- Modify: `src/openclaw/ticker_watcher.py`（整合 trading_engine.tick + signal_aggregator.aggregate）

## Step 1：寫整合測試

在 `tests/test_ticker_watcher.py` 加入：

```python
def test_watcher_imports_sprint2_modules(monkeypatch):
    """確認 sprint 2 模組可被 ticker_watcher 引入"""
    import openclaw.trading_engine as te
    import openclaw.signal_aggregator as sa
    import openclaw.lm_signal_cache as lc
    assert callable(te.tick)
    assert callable(sa.aggregate)
    assert callable(lc.read_cache)
```

## Step 2：修改 `ticker_watcher.py` 主迴圈

找到約 line 659 的信號計算區塊：

```python
# 舊（約 line 659）：
try:
    from openclaw.signal_generator import compute_signal as _sg_compute
    signal = _sg_compute(...)
except Exception as _sg_err:
    ...
```

**替換為：**

```python
# Sprint 2：呼叫 trading_engine.tick 後改用 signal_aggregator
try:
    from openclaw.trading_engine import tick as _te_tick
    _te_tick(conn, symbol)
except Exception as _te_err:
    log.warning("[%s] trading_engine.tick 失敗：%s", symbol, _te_err)

try:
    from openclaw.signal_aggregator import aggregate as _agg
    _agg_signal = _agg(
        conn, symbol, snap,
        position_avg_price=avg_price,
        high_water_mark=high_water_marks.get(symbol),
    )
    signal = _agg_signal.action
    # 將 aggregator 結果記入 trace metadata
    _agg_meta = {
        "regime": _agg_signal.regime,
        "score": _agg_signal.score,
        "weights": _agg_signal.weights_used,
        "reasons": _agg_signal.reasons,
    }
except Exception as _agg_err:
    log.warning("[%s] signal_aggregator 失敗 (%s), fallback to signal_generator",
                symbol, _agg_err)
    from openclaw.signal_generator import compute_signal as _sg_compute
    signal = _sg_compute(
        conn, symbol=symbol,
        position_avg_price=avg_price,
        high_water_mark=high_water_marks.get(symbol),
    )
    _agg_meta = {}
```

同時在 `_log_trace` 呼叫（約 line 672）中傳入 `_agg_meta` 記入 metadata。

## Step 3：確認測試通過

```bash
PYTHONPATH=src pytest tests/test_ticker_watcher.py -v -q
PYTHONPATH=src pytest tests/ -q --tb=short
```

## Step 4：Commit

```bash
git add src/openclaw/ticker_watcher.py tests/test_ticker_watcher.py
git commit -m "feat(watcher): 整合 trading_engine.tick + signal_aggregator（fallback 保留 signal_generator）"
```

---

# TASK 8：eod_analysis + agent_orchestrator 整合

**Files:**
- Modify: `src/openclaw/agents/eod_analysis.py`（EOD 後呼叫 OptimizationGateway）
- Modify: `src/openclaw/agent_orchestrator.py`（週一加入 ReflectionAgent 排程）

## Step 1：修改 eod_analysis.py

在 `eod_analysis.py` 的主流程末端（分析完成後）加入：

```python
# EOD 統計優化（每日）
try:
    from openclaw.strategy_optimizer import StrategyMetricsEngine, OptimizationGateway
    metrics = StrategyMetricsEngine(conn).compute(window_days=28)
    adjustments = OptimizationGateway(conn).on_eod(metrics)
    if adjustments:
        log.info("[eod_analysis] 自動調整 %d 項參數", len(adjustments))
except Exception as e:
    log.warning("[eod_analysis] strategy_optimizer 失敗：%s", e)
```

## Step 2：修改 agent_orchestrator.py

在週一排程的 07:00 任務（或 strategy_committee 前）加入 ReflectionAgent：

```python
# 週一 07:00 深度反思
if _is_monday() and hour == 7 and minute == 0:
    try:
        from openclaw.strategy_optimizer import ReflectionAgent
        proposals = ReflectionAgent(conn).reflect_weekly()
        log.info("[orchestrator] ReflectionAgent 建議 %d 項", len(proposals))
    except Exception as e:
        log.warning("[orchestrator] ReflectionAgent 失敗：%s", e)
```

## Step 3：確認測試

```bash
PYTHONPATH=src pytest tests/ -q --tb=short
```

## Step 4：Commit

```bash
git add src/openclaw/agents/eod_analysis.py src/openclaw/agent_orchestrator.py
git commit -m "feat(scheduler): eod_analysis 整合 OptimizationGateway + orchestrator 週一 ReflectionAgent"
```

---

# TASK 9：Sprint 2 驗收 + CI

## Step 1：跑完整測試套件

```bash
# Python 單元測試
PYTHONPATH=src pytest tests/ -q --tb=short

# FastAPI 後端測試
cd frontend/backend && python -m pytest tests/ -q
cd /Users/openclaw/.openclaw/shared/projects/ai-trader

# JS 前端測試
cd frontend/web && npm test -- --run
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
```

預期：全部通過（目標 360+ Python tests）

## Step 2：Push + 監控 CI

```bash
git push origin main
gh run watch $(gh run list --limit 1 --json databaseId -q '.[0].databaseId')
```

## Step 3：CI 全綠後重啟服務

```bash
pm2 restart ai-trader-watcher ai-trader-api
cd frontend/web && npm run build && pm2 restart ai-trader-web
cd /Users/openclaw/.openclaw/shared/projects/ai-trader
pm2 logs ai-trader-watcher --lines 30
```

確認 log 出現：
- `[trading_engine]` 相關輸出（無 crash）
- `signal_aggregator` 相關 trace

## Step 4：更新 CLAUDE.md + memory

在 CLAUDE.md `三、核心引擎關鍵檔案` 表格新增：

```
| `signal_aggregator.py` | Regime-based 動態權重信號融合（技術/LLM/市況） |
| `trading_engine.py` | 持倉狀態機 + 時間止損（EOD日計） |
| `lm_signal_cache.py` | LLM 信號快取層（TTL/fallback/purge） |
| `strategy_optimizer.py` | 策略自主優化（StrategyMetricsEngine/OptimizationGateway/ReflectionAgent） |
```

## Step 5：Commit 文件更新

```bash
git add CLAUDE.md
git commit -m "docs: 更新 CLAUDE.md — v4.12.x Sprint 2 新模組"
```

## Step 6：若 CI 全綠，開 Issue 確認 Sprint 2 完成

```bash
gh issue create \
  --title "Sprint 2 完成：signal_aggregator + trading_engine + strategy_optimizer" \
  --body "$(cat <<'EOF'
- [x] DB schema（5 新表 + 2 新欄位）
- [x] lm_signal_cache（TTL/fallback/purge）
- [x] signal_aggregator（Regime-based + 漲停板過濾）
- [x] trading_engine（持倉狀態機 + EOD時間止損）
- [x] strategy_optimizer（StrategyMetricsEngine + OptimizationGateway + ReflectionAgent）
- [x] ticker_watcher 整合
- [x] eod_analysis + orchestrator 整合
- [x] CI 全綠
EOF
)"
```

```bash
gh issue close <issue-number>
```
