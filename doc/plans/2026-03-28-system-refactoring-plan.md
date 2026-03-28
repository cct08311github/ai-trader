# AI Trader 系統重構計劃

## Context

AI Trader 是一個台股自動交易系統，目前處於模擬盤優化期。核心引擎 (`src/openclaw/`) 約 22,000 行、86 個 Python 模組，FastAPI 後端約 5,000 行，前端 React+Vite。

**為什麼需要重構**：系統經過快速迭代累積了顯著的技術債：
- 1,699 行的 God Class (`ticker_watcher.py`) 承擔了過多職責
- 239 處直接使用 `sqlite3.Connection`，無 Repository 抽象
- 設定散落在 15+ 個模組中各自載入
- 決策管線硬耦合 8 個 guard 模組
- 全域可變狀態存在執行緒安全隱患

**重構目標**：提升可維護性、可測試性、可擴展性，同時保持零停機與 100% 向後相容。

---

## 1. 現況分析

### 1.1 架構問題清單

| # | 問題 | 根本原因 | 後果 |
|---|------|---------|------|
| P1 | **God Class: ticker_watcher.py** (1,699 行) | 快速迭代將所有功能堆疊在同一檔案 | 無法單獨測試、修改風險高、新人難以理解 |
| P2 | **無 Repository Pattern** (239 處直接 SQL) | 初期沒有資料存取層設計 | Schema 變更需改動大量檔案、無法 mock DB |
| P3 | **設定管理散亂** (15+ 模組各自載入 JSON) | 缺少集中設定管理器 | 設定驗證不一致、無法熱更新、重複程式碼 |
| P4 | **決策管線硬耦合** | `decision_pipeline_v4.py` 直接 import 8 個 guard | 無法動態增減 guard、測試需 mock 大量依賴 |
| P5 | **全域可變狀態** | `_shutdown_requested`, `_BASE_PRICE` 無鎖 | 多執行緒環境下潛在競態條件 |
| P6 | **Logger 不一致** | 有些用 `log`、有些用 `logger` | 難以統一管理日誌格式與級別 |
| P7 | **錯誤處理靜默** | 多處 `return None/False` 不記錄原因 | 問題排查困難、根因被隱藏 |

### 1.2 現有優勢（保留不動）

- **無循環依賴** — 模組 import 圖是 DAG
- **FastAPI 後端架構良好** — api/services/middleware/core 分層清晰
- **Proposal 系統設計完善** — ProposalEngine → Executor → Journal 流程完整
- **signal_logic.py 是純函數** — 已具備良好可測試性
- **Agent Orchestrator 模式合理** — asyncio scheduler 清晰
- **db_utils.py 已有基礎** — readonly/readwrite/watcher 三種連線模式

---

## 2. 目標架構

### 2.1 設計原則

- **Strangler Fig Pattern**：漸進式替換，每個 Phase 獨立可上線
- **Dependency Inversion**：高層模組不依賴低層模組，兩者都依賴抽象
- **Single Responsibility**：每個類別/模組只有一個變更原因
- **Interface Segregation**：Repository 按領域劃分，不做巨型介面

### 2.2 目標架構圖

```
┌─────────────────────────────────────────────────────┐
│                  FastAPI Backend                      │
│  (保持現有 api/services/middleware 結構不變)           │
└───────────────┬─────────────────────────────────────┘
                │ imports openclaw.*
┌───────────────▼─────────────────────────────────────┐
│              Application Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ WatcherApp   │  │ AgentRunner  │  │ EODRunner  │ │
│  │ (orchestrate)│  │ (orchestrate)│  │(orchestrate)│ │
│  └──────┬───────┘  └──────────────┘  └────────────┘ │
│         │                                             │
│  ┌──────▼──────────────────────────────────────────┐ │
│  │            Domain Services                       │ │
│  │  ┌──────────────┐  ┌──────────────────────────┐ │ │
│  │  │SignalService  │  │ DecisionPipeline         │ │ │
│  │  │(aggregate)    │  │ (guard chain pattern)    │ │ │
│  │  └──────────────┘  └──────────────────────────┘ │ │
│  │  ┌──────────────┐  ┌──────────────────────────┐ │ │
│  │  │OrderService   │  │ RiskService              │ │ │
│  │  │(execute+persist│ │ (evaluate + sizing)      │ │ │
│  │  └──────────────┘  └──────────────────────────┘ │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │          Infrastructure Layer                    │ │
│  │  ┌──────────┐ ┌──────────────┐ ┌─────────────┐ │ │
│  │  │ConfigMgr │ │ Repositories │ │ LLMClient   │ │ │
│  │  │(central) │ │ (per-domain) │ │ (unified)   │ │ │
│  │  └──────────┘ └──────────────┘ └─────────────┘ │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

## 3. 重構路線圖（5 Phases）

### Phase 1: 集中設定管理 (ConfigManager)

**目標**：消除 15+ 模組各自載入 JSON 的反模式，建立單一設定入口。

**新建檔案**：
- `src/openclaw/config_manager.py` — 集中設定管理器

**設計**：
```python
# src/openclaw/config_manager.py
from dataclasses import dataclass, field
from pathlib import Path
import json, os, logging
from typing import Any, Dict, List, Optional
from openclaw.path_utils import get_repo_root

@dataclass(frozen=True)
class CapitalConfig:
    total_capital_twd: float = 1_000_000
    max_single_position_pct: float = 0.20

@dataclass(frozen=True)
class WatchlistConfig:
    manual_watchlist: List[str] = field(default_factory=list)

@dataclass(frozen=True)
class SentinelConfig:
    max_daily_loss_pct: float = 0.02
    max_open_positions: int = 10

class ConfigManager:
    """Centralized config loading with caching and validation."""

    def __init__(self, config_dir: Optional[Path] = None):
        self._config_dir = config_dir or (get_repo_root() / "config")
        self._cache: Dict[str, Any] = {}

    def get_capital(self) -> CapitalConfig: ...
    def get_watchlist(self) -> WatchlistConfig: ...
    def get_sentinel_policy(self) -> SentinelConfig: ...
    def get_locked_symbols(self) -> set[str]: ...
    def get_drawdown_policy(self) -> dict: ...
    def invalidate(self, key: Optional[str] = None): ...

    def _load_json(self, filename: str) -> dict:
        """Load JSON with caching + FileNotFoundError fallback to defaults."""
        ...
```

**修改檔案**（Phase 1 只做 adapter 橋接，不破壞現有 API）：
- `src/openclaw/risk_engine.py` — `_is_symbol_locked()` 和 `_get_daily_pm_approval()` 改用 ConfigManager
- `src/openclaw/ticker_watcher.py` — `_load_manual_watchlist()` 改用 ConfigManager
- `src/openclaw/decision_pipeline_v4.py` — `load_budget_policy()` 改用 ConfigManager
- `src/openclaw/drawdown_guard.py` — policy 載入改用 ConfigManager
- `src/openclaw/sentinel.py` — policy 載入改用 ConfigManager

**策略**：每個模組保留原有函數簽名，內部改為從 ConfigManager 讀取。提供模組級 `_config = ConfigManager()` 實例（後續 Phase 4 改為注入）。

**風險緩解**：
- 每個模組改完立即跑對應測試
- ConfigManager 載入失敗回退到原有邏輯（fail-safe）

**測試**：
- 新增 `tests/test_config_manager.py`
- 驗證：JSON 載入、快取、驗證、FileNotFoundError fallback

---

### Phase 2: Repository Pattern 抽象 DB 存取

**目標**：將散落在各模組的直接 SQL 操作封裝到 Repository 類別中。

**新建檔案**：
- `src/openclaw/repositories/__init__.py`
- `src/openclaw/repositories/order_repository.py` — 訂單 CRUD
- `src/openclaw/repositories/position_repository.py` — 持倉 CRUD
- `src/openclaw/repositories/decision_repository.py` — 決策紀錄
- `src/openclaw/repositories/signal_repository.py` — 信號快取 + eod_prices
- `src/openclaw/repositories/trace_repository.py` — LLM traces + incidents

**設計**（以 OrderRepository 為例）：
```python
# src/openclaw/repositories/order_repository.py
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class OrderRecord:
    order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    ts_submit: str
    settlement_date: Optional[str] = None

class OrderRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def insert_order(self, order: OrderRecord) -> None: ...
    def update_status(self, order_id: str, status: str) -> None: ...
    def get_today_orders(self, date_str: str) -> List[OrderRecord]: ...
    def get_pending_orders(self) -> List[OrderRecord]: ...
    def cancel_unfilled(self, order_id: str) -> None: ...
```

**修改檔案**（漸進式替換）：
- `src/openclaw/ticker_watcher.py` — `_persist_order()`, `_persist_fill()`, `_persist_decision()` 改用 Repository
- `src/openclaw/pnl_engine.py` — position 查詢/更新改用 PositionRepository
- `src/openclaw/llm_observability.py` — `insert_llm_trace()` 改用 TraceRepository
- `src/openclaw/decision_pipeline_v4.py` — `_insert_decision_record()` 改用 DecisionRepository
- `src/openclaw/lm_signal_cache.py` — 信號快取改用 SignalRepository

**策略**：
1. 先建立 Repository 類別，將現有 SQL 搬入
2. 在呼叫端建立 wrapper 函數（保留原有函數簽名，內部委託給 Repository）
3. 逐步把 caller 改為直接使用 Repository
4. 原有函數標記 `@deprecated`（但不刪除，直到所有 caller 遷移完畢）

**風險緩解**：
- Repository 內部 SQL 完全複製自原有模組（不做 SQL 改寫）
- 每個 Repository 獨立測試，用 in-memory SQLite

**測試**：
- 新增 `tests/test_repositories/` 目錄
- 每個 Repository 獨立 unit test
- 跑全量回歸 `pytest -q`

---

### Phase 3: 拆分 ticker_watcher.py God Class

**目標**：將 1,699 行的 God Class 拆成 4 個職責明確的模組。

**新建檔案**：
- `src/openclaw/market_data_service.py` — 行情快照取得
- `src/openclaw/order_executor.py` — 下單執行 + 回報追蹤
- `src/openclaw/watcher_lifecycle.py` — 生命週期管理（啟動/關閉/EOD）
- `src/openclaw/scan_engine.py` — 主掃描迴圈邏輯

**拆分對照表**：

| 原始位置 (ticker_watcher.py) | 目標模組 | 行數（約） |
|-----|------|------|
| `_get_snapshot()`, mock random walk | `market_data_service.py` | ~150 |
| `_execute_sim_order()`, `_persist_order/fill()`, broker polling | `order_executor.py` | ~300 |
| `run_watcher()`, signal handler, EOD cleanup, watchlist merge | `watcher_lifecycle.py` | ~200 |
| `_generate_signal()`, per-symbol scan loop, decision flow | `scan_engine.py` | ~400 |
| 其餘常數/設定 | `config_manager.py` (Phase 1) | ~100 |

**ticker_watcher.py 保留為薄入口**：
```python
# src/openclaw/ticker_watcher.py (refactored — ~100 lines)
"""Thin entry point. Delegates to scan_engine + watcher_lifecycle."""
from openclaw.watcher_lifecycle import WatcherApp

def run_watcher():
    app = WatcherApp()
    app.run()

if __name__ == "__main__":
    run_watcher()
```

**WatcherApp 組合模式**：
```python
# src/openclaw/watcher_lifecycle.py
class WatcherApp:
    def __init__(self, config: ConfigManager = None, db_path: str = None):
        self.config = config or ConfigManager()
        self._conn = open_watcher_conn(db_path)
        self.scanner = ScanEngine(self._conn, self.config)
        self.executor = OrderExecutor(self._conn)
        self.market_data = MarketDataService()
        self._shutdown = threading.Event()  # 取代全域 _shutdown_requested

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown.set())
        signal.signal(signal.SIGINT, lambda *_: self._shutdown.set())
        while not self._shutdown.is_set():
            self.scanner.scan_once(self.market_data, self.executor)
            self._shutdown.wait(timeout=POLL_INTERVAL_SEC)
```

**關鍵改善**：
- `_shutdown_requested` 全域變數 → `threading.Event()`（執行緒安全）
- `_BASE_PRICE` 全域 dict → `ScanEngine` 實例變數
- `_eod_cleanup_done_date` → `WatcherApp` 實例變數

**風險緩解**：
- 保留原有 `run_watcher()` 函數簽名作為入口
- PM2 ecosystem.config.js 不需修改
- 先在平行分支測試完整掃描迴圈

**測試**：
- 修改 `tests/test_ticker_watcher_integration.py` 使用新模組
- 新增各子模組 unit test
- 端到端：`pm2 restart ai-trader-watcher` 驗證

---

### Phase 4: 決策管線解耦（Guard Chain Pattern）

**目標**：將 `decision_pipeline_v4.py` 的 8 個硬耦合 guard 改為可插拔的 Chain of Responsibility。

**新建檔案**：
- `src/openclaw/guards/__init__.py`
- `src/openclaw/guards/base.py` — Guard 抽象基底

**設計**：
```python
# src/openclaw/guards/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class GuardContext:
    """Immutable context passed through the guard chain."""
    conn: object  # sqlite3.Connection
    system_state: object
    order_candidate: object
    pm_context: dict
    pm_approved: bool
    budget_policy_path: str
    drawdown_policy: object
    llm_call: object

@dataclass
class GuardResult:
    passed: bool
    reject_code: Optional[str] = None
    reason: str = ""
    metadata: dict = None

class Guard(ABC):
    @abstractmethod
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        """Return GuardResult. If passed=False, pipeline stops."""
        ...
```

**現有 guard 包裝**（不改內部邏輯，只加 adapter）：
```python
# src/openclaw/guards/system_switch_guard.py
from openclaw.guards.base import Guard, GuardContext, GuardResult
from openclaw.system_switch import check_system_switch

class SystemSwitchGuard(Guard):
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        allowed, reason = check_system_switch(ctx.system_state)
        return GuardResult(passed=allowed, reject_code="SYSTEM_SWITCH" if not allowed else None, reason=reason)
```

**重構後的 Pipeline**：
```python
# src/openclaw/decision_pipeline_v4.py (refactored)
class DecisionPipeline:
    def __init__(self, guards: list[Guard] = None):
        self.guards = guards or self._default_guards()

    def _default_guards(self) -> list[Guard]:
        return [
            SystemSwitchGuard(),
            BudgetGuard(),
            DrawdownGuard(),
            DeepSuspendGuard(),
            SentinelGuard(),
            HardBlockGuard(),
            NewsGuard(),
            PMDebateGuard(),
        ]

    def evaluate(self, ctx: GuardContext) -> Tuple[bool, str, Optional[dict]]:
        for guard in self.guards:
            result = guard.evaluate(ctx)
            if not result.passed:
                return False, result.reject_code, {"reason": result.reason}
        return True, "APPROVED", {...}
```

**保留向後相容**：
```python
# 保留原有函數簽名
def run_decision_with_sentinel(conn, system_state, order_candidate, ...):
    pipeline = DecisionPipeline()
    ctx = GuardContext(conn=conn, system_state=system_state, ...)
    return pipeline.evaluate(ctx)
```

**修改檔案**：
- `src/openclaw/decision_pipeline_v4.py` — 重構為 class-based pipeline
- 不修改任何 guard 模組的內部邏輯

**測試**：
- 新增 `tests/test_guard_chain.py` — 測試 guard 組合、順序、短路行為
- 可在測試中注入 mock guard，驗證特定 guard 被跳過

---

### Phase 5: 錯誤處理與日誌標準化

**目標**：統一 logger 命名、引入結構化日誌、改善錯誤處理。

**修改範圍**：

1. **Logger 統一**：所有模組使用 `logger = logging.getLogger(__name__)`
   - 需修改：`ticker_watcher.py` (`log` → `logger`), 其他使用 `log` 的模組
   - 全域搜尋 `log = logging.getLogger` 並替換

2. **結構化日誌 adapter**（輕量）：
```python
# src/openclaw/log_utils.py
import logging, json

class StructuredAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = {**self.extra, **kwargs.pop("extra", {})}
        return f"{msg} | {json.dumps(extra, default=str)}", kwargs
```

3. **錯誤處理改善**：
   - 將 `return None` 改為 `raise` + 在呼叫端 catch
   - 對於 fail-safe 場景保留 `try/except` 但加入 `logger.warning`
   - 不做大規模異常類別層級（overkill for this scale）

**測試**：
- 跑全量測試確認 logger 改名不影響功能
- 檢查日誌輸出格式

---

## 4. Phase 依賴關係與執行順序

```
Phase 1 (ConfigManager) ──→ Phase 3 (拆分 ticker_watcher)
                        ├──→ Phase 4 (Guard Chain)
Phase 2 (Repository)   ──→ Phase 3 (拆分 ticker_watcher)
Phase 5 (日誌) ← 可獨立執行，建議穿插在各 Phase 之間
```

**建議執行順序**：Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5

---

## 5. 驗證策略

### 每個 Phase 完成後
1. `pytest -q` — 根目錄核心引擎測試全過
2. `cd frontend/backend && python -m pytest tests/ -q` — FastAPI 測試全過
3. `cd frontend/web && npm test -- --run` — 前端測試全過（Phase 3/4 不應影響前端）

### 端到端驗證
- `pm2 restart ai-trader-watcher` — watcher 正常啟動、掃描、執行
- `curl -sk https://127.0.0.1:8080/api/health` — API 正常回應
- 檢查 `~/.pm2/logs/ai-trader-watcher-out.log` 確認無異常

### 回歸重點
- 交易決策流程：信號 → 風控 → 下單（Phase 3, 4 的核心）
- 設定載入：watchlist、capital、sentinel policy（Phase 1 核心）
- DB 讀寫：orders、fills、positions、decisions（Phase 2 核心）

---

## 6. 檔案變更摘要

| Phase | 新增檔案 | 修改檔案 | 估計行數 |
|-------|---------|---------|---------|
| 1 | 1 (config_manager.py) | 5 | ~300 新 + ~100 改 |
| 2 | 6 (repositories/) | 5 | ~600 新 + ~200 改 |
| 3 | 4 (market_data_service, order_executor, watcher_lifecycle, scan_engine) | 1 (ticker_watcher.py 瘦身) | ~900 新 + ~1600 搬移 |
| 4 | 2 (guards/base.py, guards/__init__.py) + 8 guard adapters | 1 (decision_pipeline_v4.py) | ~400 新 + ~200 改 |
| 5 | 1 (log_utils.py) | ~10 | ~50 新 + ~100 改 |

**Total**: ~14 新檔案, ~22 修改檔案, ~2,250 行新增, ~2,200 行搬移/修改
