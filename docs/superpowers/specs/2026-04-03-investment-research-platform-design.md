# AI Investment Research Platform — Design Spec

**Date:** 2026-04-03
**Author:** Zug (Claude Code)
**Status:** v3 — Final (Approved with Conditions Incorporated)
**Issue:** #549 (extended scope), #556 (v2 review), #557 (v3 conditions + plan)

---

## 1. Product Definition

### What
個人投資作戰中心 — 統一入口取代 Yahoo 股市、Goodinfo、TradingView、Bloomberg 新聞、CCT 晨報。

### Who
Jun（單一用戶），CISSP 持證，管理銀行資安，持有台股高股息 ETF + 科技股 + 記憶體股 + 美債。

### Core Value
- 全球多市場覆蓋（台/美/日/韓/港 + 商品 + 債券 + 匯率 + 加密貨幣）
- 8 個 AI Agent 即時研究（stock_research、debate_loop、competitor_monitor 等）
- 混合決策支援（由上而下 + 由下而上 + 事件驅動）
- 風險管理儀表板（集中度、相關性、最大回撤、壓力測試）
- 直接連動 ai-trader 交易系統

### Non-Goals (Phase 1)
- 多用戶/帳號系統
- SaaS/付費功能
- 盤中秒級即時報價
- 付費數據 API

---

## 2. Architecture

### System Architecture
```
                    ┌──────────────────────────────────────┐
                    │         React Frontend (Vite)         │
                    │                                      │
                    │  ┌─────────┐ ┌──────────┐ ┌───────┐ │
                    │  │戰情總覽 │ │Investment│ │ Risk  │ │
                    │  │Dashboard│ │ Center   │ │ Mgmt  │ │
                    │  └────┬────┘ └────┬─────┘ └───┬───┘ │
                    │       │          │            │      │
                    │  ┌────▼──────────▼────────────▼───┐  │
                    │  │     Shared Components          │  │
                    │  │  DataCard, MetricBadge,        │  │
                    │  │  SentimentIndicator, Ticker    │  │
                    │  └────────────┬───────────────────┘  │
                    │               │ TanStack Query (v5)  │
                    └──────────────┼───────────────────────┘
                                   │ HTTP + SSE
                    ┌──────────────▼───────────────────────┐
                    │       FastAPI Backend                 │
                    │       (Cache Layer + Circuit Breaker) │
                    │                                      │
                    │  /api/dashboard/*      (Phase 1A)     │
                    │  /api/indices/*        (Phase 1A)     │
                    │  /api/research/*       (Phase 1B)     │
                    │  /api/screener/*       (Phase 1B)     │
                    │  /api/risk/*           (Phase 1C)     │
                    │  /api/geopolitical/*   (Phase 1D)     │
                    │  /api/reports/*        (Phase 1D)     │
                    │  /api/macro/*          (Phase 2)      │
                    │  /api/sector/*         (Phase 2)      │
                    │  /api/stream/*         (SSE)          │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │     Data Layer                        │
                    │     research.db (研究專用，與 trades.db 分離) │
                    │                                      │
                    │  Existing (from trades.db, read-only):│
                    │  - stock_research_reports             │
                    │  - system_candidates                  │
                    │  - competitor_intel                   │
                    │  - debate_records                     │
                    │  - eod_prices / eod_institution_flows │
                    │                                      │
                    │  New (research.db):                   │
                    │  - market_indices                     │
                    │  - geopolitical_events                │
                    │  - research_reports                   │
                    │  - risk_snapshots                     │
                    │  - data_source_health                 │
                    │  - macro_indicators    (Phase 2)      │
                    │  - sector_data         (Phase 2)      │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │     External Data Sources (Free)      │
                    │                                      │
                    │  - TWSE OpenAPI (台股)                 │
                    │  - Yahoo Finance (全球指數/個股)        │
                    │  - FRED API (宏觀, Phase 2)            │
                    │  - GNews (新聞, 100 req/day)           │
                    │  - Exa AI Search MCP (新聞補充)         │
                    │  - RSS Feeds (CNA/Reuters)            │
                    └──────────────────────────────────────┘
```

### Data Update Frequency
| 數據類型 | 更新頻率 | 來源 |
|---------|---------|------|
| 全球指數 | 每 5 分鐘（盤中）| Yahoo Finance |
| 台股個股 | 盤後（daily_nav 22:00）| TWSE OpenAPI |
| 基本面數據 | 每日盤後 | TWSE + Yahoo Finance |
| 地緣政治新聞 | 每 4 小時 | GNews + Exa + RSS |
| 個股研究報告 | 每日 18:00 | stock_research agent |
| 辯論紀錄 | 每日 17:30 | debate_loop agent |
| 風險快照 | 每日 22:30 | risk module |
| 宏觀指標 | 每週（Phase 2）| FRED API |
| 賽道數據 | 每日盤後（Phase 2）| TWSE |

### Market Coverage — Global Indices
| 指數 | Ticker | 說明 |
|------|--------|------|
| 加權指數 | ^TWII | 台股大盤 |
| S&P 500 | ^GSPC | 美股大盤 |
| NASDAQ | ^IXIC | 科技股 |
| 費半 | ^SOX | 半導體（記憶體股關鍵） |
| 日經 225 | ^N225 | 日股 |
| 恒生指數 | ^HSI | 港股 |
| KOSPI | ^KS11 | 韓股（記憶體股對標） |
| VIX | ^VIX | 恐慌指數 |
| 美元指數 | DX-Y.NYB | 美元強弱 |
| 黃金 | GC=F | 避險資產 |
| 原油 | CL=F | 能源 |
| 10Y 美債 | ^TNX | 債券殖利率 |
| USD/TWD | USDTWD=X | 匯率 |
| Bitcoin | BTC-USD | 加密貨幣 |

> Ticker 列表可自訂：用戶可透過 `/settings` 新增或移除追蹤指數。

### Fundamental Data Coverage
| 數據項 | 來源 | 說明 |
|--------|------|------|
| P/E Ratio | Yahoo Finance | 本益比 |
| P/B Ratio | Yahoo Finance | 股價淨值比 |
| EPS | Yahoo Finance + TWSE | 每股盈餘 |
| 殖利率 | TWSE | 高股息 ETF 投資者關鍵指標 |
| 月營收 YoY/MoM | TWSE OpenAPI | 台股特色數據 |
| 法說會日期 | TWSE 公告 | Earnings calendar |
| 除息日 + 填息率 | TWSE | 填息天數追蹤 |

---

## 3. Phase 1A: 戰情總覽 Dashboard + GlobalTicker + Infrastructure (Week 1)

### Goal
Single pane of glass：一頁掌握 Portfolio P&L、異常個股、風險警報、關鍵新聞。同時建立共享元件庫和前端基礎設施。

### Three-Tier Alert System
| 等級 | 意義 | 範例 |
|------|------|------|
| RED | 需立即行動 | 持股跌停、停損觸發、重大利空 |
| YELLOW | 持續關注 | 外資連賣 3 日、接近停損價、VIX > 25 |
| GREEN | 正常 | 市場穩定、持股在預期範圍內 |

**資訊優先序：** Red alerts > Portfolio 異動 > 市場總覽 > 地緣政治事件

### New DB Tables
```sql
-- research.db
CREATE TABLE IF NOT EXISTS market_indices (
    trade_date TEXT NOT NULL,
    index_code TEXT NOT NULL,
    name TEXT,
    close REAL,
    change REAL,
    change_pct REAL,
    volume REAL,
    source TEXT DEFAULT 'yahoo',
    created_at INTEGER NOT NULL,
    PRIMARY KEY (trade_date, index_code)
);

CREATE TABLE IF NOT EXISTS data_source_health (
    source_name TEXT NOT NULL,
    last_success_at INTEGER,
    last_failure_at INTEGER,
    consecutive_failures INTEGER DEFAULT 0,
    avg_latency_ms REAL,
    status TEXT DEFAULT 'healthy',  -- healthy, degraded, down
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (source_name)
);
```

### New Backend Files
| File | Purpose |
|------|---------|
| `src/openclaw/market_index_fetcher.py` | Fetch global indices from Yahoo Finance (customizable ticker list) |
| `frontend/backend/app/api/dashboard.py` | GET /api/dashboard/overview (alerts, P&L, market summary) |
| `frontend/backend/app/api/market_indices.py` | GET /api/indices/latest, /api/indices/history |
| `frontend/backend/app/core/cache.py` | TTL cache decorator + HTTP Cache-Control headers |
| `frontend/backend/app/core/circuit_breaker.py` | Circuit Breaker for external API calls |
| `frontend/backend/app/core/response.py` | Unified response envelope with pagination + data freshness metadata |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/Dashboard.jsx` | 戰情總覽主頁（default home） |
| `src/components/ui/DataCard.jsx` | 通用數據卡片 |
| `src/components/ui/MetricBadge.jsx` | 指標徽章（含漲跌色彩 + 箭頭符號） |
| `src/components/ui/SentimentIndicator.jsx` | 情緒指標 |
| `src/components/GlobalTicker.jsx` | 頂部全球指數 ticker（aria-live="polite"） |
| `src/components/AlertPanel.jsx` | 三色警報面板 |

### Page Layout — 戰情總覽 Dashboard
```
┌─────────────────────────────────────────────────────┐
│  GlobalTicker: TAIEX ▲0.5%  S&P500 ▼0.2%  VIX 18   │
│  (aria-live="polite", scrolling, customizable)       │
├─────────────────────────────────────────────────────┤
│ [RED ALERTS]  停損觸發: 2344 華邦電 跌破 25.0        │
├──────────────────────┬──────────────────────────────┤
│ Portfolio P&L        │ 異常個股                      │
│ 總資產: $2.5M        │ ▲ 2382 廣達 +4.2% (量能突破)  │
│ 今日損益: +$12,500   │ ▼ 2344 華邦電 -3.1% (破月線)  │
│ 持股: 15 檔          │ ▲ 00878 國泰永續高股息 +0.8%  │
├──────────────────────┼──────────────────────────────┤
│ Market Overview      │ Key News                      │
│ 台股 ▲ 18,523       │ [Y] Fed 暗示暫停升息...        │
│ 費半 ▼ 4,521        │ [G] TSMC 法說會優於預期...     │
│ VIX  18.2 (normal)  │ [G] 台積電擴廠越南...          │
└──────────────────────┴──────────────────────────────┘
```

### npm Dependencies (Phase 1A)
- `@tanstack/react-query` (v5) — data fetching + caching
- `react-simple-maps` (40KB gzipped) — 2D world map (Phase 1D 使用)
- `topojson-client` (2KB) — map data parser

---

## 4. Phase 1B: 個股分析 + 篩選器 (Week 1-2)

### Goal
用現有 agent 輸出建出個股研究和選股工具。最快交付價值 — 數據已存在。

### New Backend Files
| File | Purpose |
|------|---------|
| `frontend/backend/app/api/research.py` | GET /api/research/stocks, /api/research/stocks/{symbol}, /api/research/debate/{symbol} |
| `frontend/backend/app/api/screener.py` | GET /api/screener/candidates, /api/screener/scatter |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/Research/StockAnalysis.jsx` | Individual stock AI report page |
| `src/pages/Research/MarketScreener.jsx` | Scatter plot multi-factor screener |
| `src/pages/Research/ResearchDashboard.jsx` | Investment center home |
| `src/components/AIRatingBadge.jsx` | AI Score + Confidence 分離顯示 |
| `src/components/RadarChart.jsx` | Technical/fundamental radar chart |
| `src/components/ScoreHistory.jsx` | 分數變化追蹤（前次 vs 當前 + 原因） |

### AI Scoring System
| 維度 | 權重 | 說明 |
|------|------|------|
| Technical | 25% | RSI, MACD, MA, 量能 |
| Institutional | 25% | 三大法人動向、融資券 |
| Fundamental | 25% | P/E, EPS, 月營收 YoY, 殖利率 |
| Event | 25% | 地緣政治、法說會、除息 |

- **AI Score** (0-10): 四維度加權複合分數
- **Confidence** (0-100%): 模型確定性（與 AI Score 分離）
- **Score Change**: 前次分數 vs 當前分數 + 變動原因
- **Historical Accuracy**: 回測準確率（Phase 2 建立基準線）

### Page Layout — Stock Analysis
```
┌─────────────────────────────────────────────────────┐
│  Stock: 2382 廣達                                    │
│  AI Score: 7.8 [A]  Confidence: 82%  Prev: 7.2 [+0.6]│
│  Price: ▲ 271.5  P/E: 18.2  殖利率: 2.1%            │
├──────────────────────┬──────────────────────────────┤
│ Scoring Breakdown    │ Institutional Layer           │
│ ┌──────────────────┐ │ 外資: 連買 5 日               │
│ │  Radar Chart     │ │ 投信: 連買 3 日               │
│ │ Tech:7 Inst:8    │ │ 自營: 賣超                    │
│ │ Fund:7 Evnt:9    │ │ 融資: ▼                       │
│ └──────────────────┘ │ 月營收 YoY: +15.2%            │
├──────────────────────┴──────────────────────────────┤
│ AI Synthesis                                         │
│ 進場價: 265  停損: 250  目標價: 310                   │
│ 理由: AI 伺服器需求持續增長...                        │
│ Score 變動: +0.6 (法說會優於預期 + 外資轉買)          │
├─────────────────────────────────────────────────────┤
│ Fundamentals                                         │
│ P/E: 18.2  P/B: 3.1  EPS: 14.9  殖利率: 2.1%       │
│ 月營收: $152B (+15.2% YoY, +3.1% MoM)               │
│ 下次法說會: 2026-05-15  除息日: 2026-07-20           │
├─────────────────────────────────────────────────────┤
│ Bull vs Bear Debate                                  │
│ [Bull] 題材強勁...   │  [Bear] 估值偏高...            │
│           [Arbiter] BUY (confidence: 78%)             │
└─────────────────────────────────────────────────────┘
```

### Page Layout — Market Screener
```
┌─────────────────────────────────────────────────────┐
│ Filters: [RSI < 30] [外資連買] [量能突破] [殖利率>5%] │
├─────────────────────────────────────────────────────┤
│                                                      │
│    ScatterChart                                      │
│    X: RSI14    Y: 量比    Size: 法人買超             │
│                                                      │
│         *(2382)                                      │
│              *(2330)                                 │
│    *(2344)        *(2408)                            │
│                                                      │
├─────────────────────────────────────────────────────┤
│ Ranked List (by AI score)                            │
│ 1. 2382 廣達  A  7.8 (82%)  RSI:45  外資+5日  殖利率:2.1% │
│ 2. 2344 華邦電 B  6.5 (71%)  RSI:38  投信+3日  殖利率:4.5% │
└─────────────────────────────────────────────────────┘
```

---

## 5. Phase 1C: 風險儀表板 Risk Dashboard (Week 2-3)

### Goal
Portfolio 風險可視化 — 集中度、相關性、最大回撤、停損追蹤、壓力測試。每日風險報告自動推送至 Report Center。

### New DB Tables
```sql
-- research.db
CREATE TABLE IF NOT EXISTS risk_snapshots (
    snapshot_date TEXT NOT NULL,
    portfolio_value REAL,
    max_drawdown REAL,
    concentration_top1_pct REAL,
    concentration_top5_pct REAL,
    correlation_avg REAL,
    var_95 REAL,
    stress_results TEXT,       -- JSON: scenario results
    created_at INTEGER NOT NULL,
    PRIMARY KEY (snapshot_date)
);
```

### New Backend Files
| File | Purpose |
|------|---------|
| `frontend/backend/app/api/risk.py` | GET /api/risk/overview, /api/risk/concentration, /api/risk/correlation, /api/risk/stress-test |
| `src/openclaw/risk_calculator.py` | 每日計算風險指標，寫入 risk_snapshots |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/RiskDashboard.jsx` | 風險儀表板主頁 |
| `src/components/ConcentrationTreemap.jsx` | Treemap by 個股/產業/國家 |
| `src/components/CorrelationHeatmap.jsx` | 持股相關性矩陣熱力圖 |
| `src/components/DrawdownChart.jsx` | 最大回撤追蹤圖 |
| `src/components/StopLossTracker.jsx` | 停損執行追蹤表 |

### Risk Metrics
| 指標 | 說明 |
|------|------|
| 集中度 Treemap | 按個股/產業/國家分類的持倉占比 |
| 相關性矩陣 | 持股間的相關係數熱力圖 |
| Max Drawdown | 歷史最大回撤追蹤 |
| 停損追蹤 | 各持股距停損價距離 + 執行紀錄 |
| VaR (95%) | 95% 信賴區間的最大日損失 |

### Stress Test Scenarios
| 情境 | 變動 | 影響估算 |
|------|------|---------|
| 台幣升值 | TWD +5% | 美債 ETF 匯損 |
| 美債殖利率飆升 | 10Y yield +100bp | 債券部位損失 |
| 記憶體價格崩盤 | DRAM/NAND -30% | 記憶體股衝擊 |
| VIX 飆升 | VIX > 35 | 全面風險升溫 |
| 費半重挫 | SOX -15% | 科技股連動 |

### Page Layout — Risk Dashboard
```
┌─────────────────────────────────────────────────────┐
│  Risk Overview    VaR(95%): -$52K   Max DD: -8.2%    │
├──────────────────────┬──────────────────────────────┤
│ Concentration        │ Correlation Matrix            │
│ ┌──────────────────┐ │ ┌──────────────────────────┐ │
│ │  Treemap         │ │ │  Heatmap                 │ │
│ │ [2330 TSMC 25%]  │ │ │  2330  2382  2344  00878 │ │
│ │ [2382 廣達 15%]  │ │ │  1.0   0.7   0.8   0.3  │ │
│ │ [00878  12%]     │ │ │  0.7   1.0   0.6   0.2  │ │
│ └──────────────────┘ │ └──────────────────────────┘ │
├──────────────────────┴──────────────────────────────┤
│ Stop-Loss Tracker                                    │
│ 2382 廣達   現價 271.5  停損 250  距離: -7.9%  [G]   │
│ 2344 華邦電 現價 25.2   停損 25.0 距離: -0.8%  [R]   │
├─────────────────────────────────────────────────────┤
│ Stress Test Results                                  │
│ TWD+5%: -$38K  │  10Y+100bp: -$21K  │  DRAM-30%: -$85K │
└─────────────────────────────────────────────────────┘
```

---

## 6. Phase 1D: 地緣政治 + 報告中心 (Week 3-4)

### Goal
地緣政治事件地圖 + 統一報告中心。此時數據已累積足夠量。

### New DB Tables
```sql
-- research.db
CREATE TABLE IF NOT EXISTS geopolitical_events (
    event_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    category TEXT NOT NULL,       -- trade_war, sanctions, conflict, policy, election
    region TEXT,                   -- asia, europe, americas, middle_east, africa
    country TEXT,
    lat REAL,
    lng REAL,
    impact_score REAL,            -- 0-10 (LLM evaluated)
    market_impact TEXT,           -- JSON: affected sectors/assets
    source_url TEXT,
    source_name TEXT,             -- GNews, CNA, Reuters, Exa
    published_at TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    report_id TEXT PRIMARY KEY,
    report_type TEXT NOT NULL,    -- geopolitical, market, investment, security, risk
    title TEXT NOT NULL,
    content TEXT,
    generated_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
```

### New Backend Files
| File | Purpose |
|------|---------|
| `src/openclaw/agents/geopolitical_agent.py` | Expand competitor_monitor pattern for general geopolitical events |
| `frontend/backend/app/api/geopolitical.py` | GET /api/geopolitical/events, /api/geopolitical/latest |
| `frontend/backend/app/api/research_reports.py` | GET /api/reports/list, /api/reports/{id}, POST /api/reports/generate |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/Geopolitical.jsx` | Main geopolitical dashboard page |
| `src/components/WorldMap.jsx` | 2D world map with event markers (react-simple-maps) |
| `src/components/NewsFeed.jsx` | Scrollable news feed with sentiment badges |
| `src/pages/ReportCenter.jsx` | Report listing + Markdown viewer |

### Page Layout — Geopolitical Dashboard
```
┌─────────────────────────────────────────────────────┐
│  GlobalTicker: TAIEX ▲0.5%  S&P500 ▼0.2%  ...      │
├─────────────────────────────────────────────────────┤
│                    │                                 │
│                    │   NewsFeed                      │
│    WorldMap        │   ┌──────────────────────┐     │
│    (60% width)     │   │ [R] Iran attacks...  │     │
│                    │   │ [Y] Fed hints...     │     │
│    * = event       │   │ [G] TSMC earnings..  │     │
│    size = impact   │   │ ...                  │     │
│    color = type    │   └──────────────────────┘     │
│                    │                                 │
│                    │   Market Impact Summary         │
│                    │   最受影響: 能源 ▲3.2%          │
│                    │   避險升溫: 黃金 ▲1.5%          │
│                    │                                 │
└─────────────────────────────────────────────────────┘
```

### Report Types
| Type | Source | 頻率 |
|------|--------|------|
| 地緣政治 | geopolitical_agent | 每 4 小時 |
| 金融市場 | eod_analysis + market_research | 每日盤後 |
| 投資中心 | stock_research + debate_loop | 每日 18:00 |
| 資安快報 | CCT tech-risk-weekly | 每日 |
| 風險日報 | risk_calculator | 每日 22:30 |

### npm Dependencies (Phase 1D)
- `react-markdown` (14KB) + `remark-gfm` (5KB) — Markdown rendering

---

## 7. Phase 2: Deep Data Integration (Week 5-10)

### Macro Analysis
- FRED API integration (GDP, CPI, Fed Rate, Unemployment, 10Y Treasury)
- Taiwan macro data (主計處 Open Data, 央行利率)
- LineChart trend visualization

### Sector Analysis
- TWSE sector classification + daily data
- PieChart market cap allocation
- BarChart fund flow by sector
- Click-through to sector stock list

### 3D Globe Upgrade
- Replace react-simple-maps with react-globe.gl
- WebGL detection + 2D fallback for low-end devices

### AI Scoring Backtesting
- Historical accuracy tracking per scoring dimension
- Win rate by AI Score bracket (A/B/C/D)
- Confidence calibration curve

### New npm Dependencies (Phase 2)
- `react-globe.gl` (300KB) — 3D globe
- New pip: `fredapi`, `feedparser`

---

## 8. Frontend Infrastructure

### Data Fetching
- **TanStack Query (React Query v5)** for all API calls
  - Automatic caching, background refetching, stale-while-revalidate
  - Shared query keys for cross-component cache sharing
  - Optimistic updates for user actions

### Shared Component Library
| Component | 用途 |
|-----------|------|
| `src/components/ui/DataCard.jsx` | 通用數據卡片容器 |
| `src/components/ui/MetricBadge.jsx` | 數值指標徽章（漲跌用箭頭/符號，不僅靠紅綠色） |
| `src/components/ui/SentimentIndicator.jsx` | 情緒指標（看多/中性/看空） |
| `src/components/ui/AlertBadge.jsx` | R/Y/G 三色警報徽章 |

### Code Splitting
- Route-level code splitting: `React.lazy()` + `<Suspense>`
- Nested routes under `/research/*` with `ResearchLayout`
- Heavy components (WorldMap, charts) lazy-loaded

### Accessibility
- `prefers-reduced-motion` media query for all animations
- Chart elements with `aria-label` descriptions
- Color-blind safe: 使用箭頭 (▲/▼) + 符號 (+/-) 輔助紅綠色
- GlobalTicker: `aria-live="polite"` for screen readers
- Keyboard navigation for all interactive elements

---

## 9. Backend Infrastructure

### Caching Layer
- TTL cache decorator for expensive computations
- HTTP `Cache-Control` headers on API responses
- Different TTL by data type (indices: 5min, reports: 1hr, fundamentals: 24hr)

### Resilience
- **Circuit Breaker** pattern for all external API calls (Yahoo Finance, GNews, TWSE)
- Automatic fallback to cached data when circuit opens
- `data_source_health` table tracks availability metrics

### API Design
- Unified response envelope:
  ```json
  {
    "data": [...],
    "meta": {
      "total": 100,
      "page": 1,
      "per_page": 20,
      "data_freshness": "2026-04-03T22:00:00+08:00",
      "source": "twse",
      "cache_hit": true
    }
  }
  ```
- Pagination on all list endpoints
- Data freshness metadata in every response

### Database
- **Separate `research.db`** from `trades.db` (avoid coupling)
- Read-only access to `trades.db` for portfolio/position data
- **UPSERT** (INSERT OR REPLACE) for all ingest operations
- `data_source_health` table for monitoring external API status

---

## 10. Security

### P0 — Immediate Fix Required
- **ecosystem.config.js 中的 Telegram token 必須移至 .env**
  - 目前硬編碼在 config 中，屬 P0 安全風險
  - 修復方式：改用 `process.env.TELEGRAM_BOT_TOKEN`
  - 加入 `.env.example` 範本

### General
- 無密鑰/API key 進入 git
- 所有外部輸入在邊界驗證
- SQL 使用參數化查詢
- API rate limiting 防止自我 DDoS

---

## 11. Navigation Structure

```
├── 戰情總覽          /dashboard           (Phase 1A, DEFAULT HOME)
├── 金融市場          /market-tracker      (Phase 1A)
├── 投資中心          /research            
│   ├── 儀表板        /research            (Phase 1B)
│   ├── 個股分析      /research/stock      (Phase 1B)
│   ├── 全市場篩選    /research/screener   (Phase 1B)
│   ├── 宏觀分析      /research/macro      (Phase 2)
│   ├── 賽道分析      /research/sector     (Phase 2)
│   └── 資產宇宙      /research/universe   (Phase 2)
├── 風險管理          /risk                (Phase 1C)
├── 地緣政治          /geopolitical        (Phase 1D)
├── 報告中心          /reports             (Phase 1D)
├── 交易系統 (existing)
│   ├── Portfolio      /portfolio
│   ├── Trades         /trades
│   ├── Strategy       /strategy
│   ├── Analysis       /analysis
│   ├── Agents         /agents
│   └── System         /system
└── 設定              /settings
```

---

## 12. Differentiation vs Reference Platform

| 他們 | 我們 |
|------|------|
| 靜態 AI 報告 | 8 個 Agent 即時辯論+研究+風控 |
| 單向分析 | Bull/Bear/Arbiter 多方觀點 |
| 通用推薦 | 針對你持倉組合客製化 |
| 付費訂閱 | 自建免費 |
| 無交易系統 | 直接連動 ai-trader 下單 |
| 無資安情報 | 整合 Security Red Team + 資安快報 |
| 無風險管理 | 集中度/相關性/壓力測試/停損追蹤 |
| AI 黑箱 | 四維度透明評分 + 變動追蹤 |

---

## 13. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Yahoo Finance API 不穩定 | 指數無法更新 | Circuit Breaker + 多來源 fallback + cache 24hr |
| GNews 免費 100 req/day 不夠 | 新聞不足 | Exa AI search MCP 補充 + RSS |
| LLM 成本（地緣政治分析） | 月費增加 | 每日上限 50 LLM calls |
| react-simple-maps 功能有限 | 地圖不夠炫 | Phase 2 升級 3D globe |
| 免費數據延遲 | 資訊不即時 | 明確標示數據時效性 (freshness metadata) |
| ecosystem.config.js token 外洩 | 安全風險 P0 | 立即移至 .env，加入 .gitignore |
| research.db 與 trades.db 耦合 | 升級困難 | 分離 DB，read-only access |
| 外部 API 全部同時故障 | 系統無法運作 | data_source_health 監控 + graceful degradation |
| AI Score 準確度不足 | 用戶失去信心 | Phase 2 回測 + 分數校準 |
| 色盲用戶無法判讀 | 無障礙問題 | 箭頭/符號輔助 + aria-labels |

---

## 14. Expert Review Conditions (Must-Fix Before Implementation)

第二輪專家審查提出 8 項必須在實作前納入的條件，分為三大類：

### Investment Conditions (3)

#### 14.1 K-line Chart Component
- 使用 `lightweight-charts`（TradingView 開源，40KB gzipped）於 Stock Analysis 頁面
- 功能：K 線圖 + MA overlay（5/10/20/60 日均線）
- 整合位置：`src/pages/Research/StockAnalysis.jsx` 的 Fundamentals 區塊下方
- npm dependency: `lightweight-charts` (Phase 1B)

#### 14.2 Action Queue in Dashboard
- Red Alerts 需要行動按鈕（執行停損、加碼、忽略），而非僅顯示資訊
- 兩種方案（擇一）：
  - **方案 A**：Dashboard 內嵌 Action Queue — Red Alert 旁直接附帶按鈕
  - **方案 B**：新增 `/action-queue` 路由 — 獨立的待辦行動頁面
- 推薦方案 A（減少頁面切換，符合「一頁掌握」原則）

#### 14.3 Stock Analysis Portfolio Cross-Reference
- 當分析的個股為持倉股票時，頁面頂部顯示：
  - 持倉成本（avg cost）
  - 未實現損益（unrealized P&L, 金額 + 百分比）
  - 組合權重（portfolio weight %）
- 資料來源：trades.db（read-only）的 positions 表
- 整合位置：StockAnalysis 頁面標題列下方，以 highlight bar 呈現

### System Conditions (3)

#### 14.4 DB Init: WAL Mode
- research.db 初始化時執行 `PRAGMA journal_mode=WAL`
- 目的：防止 cron job 寫入時鎖定 API 讀取（writer lock）
- 實作位置：`frontend/backend/app/core/database.py` 或 DB init script
- 同時對 trades.db 的 read-only connection 設定 `PRAGMA query_only=ON`

#### 14.5 Scheduling Mechanism Definition
- 使用 PM2 `cron_restart` 管理各數據 pipeline 排程
- 排程表：

| Process Name | Schedule | Purpose |
|-------------|----------|---------|
| `market-index-fetcher` | `*/5 * * * *` (盤中每 5 分) | 全球指數更新 |
| `eod-data-pipeline` | `0 22 * * 1-5` (盤後 22:00) | 台股日收盤數據 |
| `stock-research-agent` | `0 18 * * 1-5` (18:00) | 個股研究報告 |
| `debate-loop-agent` | `30 17 * * 1-5` (17:30) | 多方辯論 |
| `geopolitical-agent` | `0 */4 * * *` (每 4 小時) | 地緣政治新聞 |
| `risk-calculator` | `30 22 * * 1-5` (22:30) | 風險快照 |

- 整合至 `ecosystem.config.js`

#### 14.6 API Deployment Boundary
- 確認 API 僅透過 localhost 存取（Tailscale 內網）
- CORS 配置：
  ```python
  origins = ["http://localhost:5173", "http://100.x.x.x:5173"]  # Tailscale IP
  ```
- 不對外暴露，無需 HTTPS 或 OAuth（Phase 1 單一用戶）
- 實作位置：FastAPI `CORSMiddleware` 設定

### Frontend Conditions (4)

#### 14.7 ScatterChart 500+ Data Points Performance
- 超過 300 點時效能劣化，需以下對策：
  - **推薦方案**：使用 `@visx/visx` canvas scatter（>300 點改 canvas rendering）
  - **替代方案**：Recharts + `isAnimationActive={false}` + 數據分頁（每頁 100 點）
- 在 Market Screener 頁面實作
- 加入效能指標：render time < 200ms for 500 points

#### 14.8 Mobile Responsiveness
- 定義斷點：
  - `sm: 640px` — 手機
  - `md: 768px` — 平板
  - `lg: 1024px` — 桌面
- 適配規則：
  - Dashboard：< 768px 時改為單欄堆疊
  - WorldMap / ScatterChart：< 768px 時替換為排序列表（sorted list）
  - GlobalTicker：< 640px 時改為可左右滑動（swipe）
- 使用 Tailwind responsive utilities（`sm:`, `md:`, `lg:`）

#### 14.9 Design Tokens
- 加入 `tailwind.config.js` 設計令牌：
  ```js
  // Spacing scale (4px base)
  spacing: { 0.5: '2px', 1: '4px', 2: '8px', 3: '12px', 4: '16px', 6: '24px', 8: '32px' }
  
  // Border radius tokens
  borderRadius: { sm: '4px', md: '8px', lg: '12px', xl: '16px', full: '9999px' }
  
  // Typography scale
  fontSize: { xs: '0.75rem', sm: '0.875rem', base: '1rem', lg: '1.125rem', xl: '1.25rem', '2xl': '1.5rem' }
  
  // Shadow tokens
  boxShadow: { card: '0 1px 3px rgba(0,0,0,0.3)', elevated: '0 4px 12px rgba(0,0,0,0.4)', modal: '0 8px 24px rgba(0,0,0,0.5)' }
  ```
- 確保所有元件使用 token 而非 hardcoded 值

#### 14.10 Testing Strategy
- **Unit / Component Tests**：Vitest + React Testing Library
  - 所有共享元件（DataCard, MetricBadge 等）
  - API hook 測試（TanStack Query hooks）
- **E2E Tests**：Playwright
  - Critical path 1: Dashboard 載入 + 數據顯示
  - Critical path 2: Stock Analysis 導航 + 報告渲染
  - Critical path 3: Market Screener 篩選 + 散佈圖
- **API Mocking**：MSW (Mock Service Worker)
  - 攔截所有 `/api/*` 請求
  - 提供 fixture data 用於開發和測試
- npm devDependencies: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `@playwright/test`, `msw`

---

## 15. Success Criteria

Phase 1 完成後，你應該能夠：
- [ ] 開啟戰情總覽，一頁看到 Portfolio P&L + 異常個股 + 風險警報 + 關鍵新聞
- [ ] Red/Yellow/Green 三色警報正確分類並按優先序排列
- [ ] 頂部 ticker bar 顯示 14+ 個指數/商品/債券/加密貨幣（可自訂）
- [ ] 點擊任何 watchlist 股票，看到四維度 AI 評分 + 信心度 + 分數變動原因
- [ ] 看到個股基本面：P/E、殖利率、月營收 YoY、法說會日期
- [ ] 用散佈圖視覺化篩選候選股（含殖利率篩選器）
- [ ] 風險儀表板：集中度 Treemap + 相關性矩陣 + 停損追蹤 + 壓力測試
- [ ] 地緣政治頁面：2D 世界地圖 + 即時新聞 feed + 影響評分
- [ ] 在報告中心閱讀所有 AI 產出的報告（含每日風險日報）
- [ ] ecosystem.config.js 中無任何硬編碼 token
- [ ] 色盲用戶可透過箭頭/符號辨識漲跌
- [ ] 說出：「不用再開 Yahoo 股市了」
