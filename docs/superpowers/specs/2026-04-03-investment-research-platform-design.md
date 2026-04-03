# AI Investment Research Platform — Design Spec

**Date:** 2026-04-03
**Author:** Zug (Claude Code)
**Status:** Draft — Pending Review
**Issue:** #549 (extended scope)

---

## 1. Product Definition

### What
個人投資作戰中心 — 統一入口取代 Yahoo 股市、Goodinfo、TradingView、Bloomberg 新聞、CCT 晨報。

### Who
Jun（單一用戶），CISSP 持證，管理銀行資安，持有台股高股息 ETF + 科技股 + 記憶體股 + 美債。

### Core Value
- 全球多市場覆蓋（台/美/日/韓/港 + 商品 + 債券 + 匯率）
- 8 個 AI Agent 即時研究（stock_research、debate_loop、competitor_monitor 等）
- 混合決策支援（由上而下 + 由下而上 + 事件驅動）
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
                    │  │Geopolit.│ │Investment│ │Report │ │
                    │  │Dashboard│ │ Center   │ │Center │ │
                    │  └────┬────┘ └────┬─────┘ └───┬───┘ │
                    │       │          │            │      │
                    │  ┌────▼──────────▼────────────▼───┐  │
                    │  │     Shared Components          │  │
                    │  │  (Map, Charts, Ticker, Cards)  │  │
                    │  └────────────┬───────────────────┘  │
                    └──────────────┼───────────────────────┘
                                   │ HTTP + SSE
                    ┌──────────────▼───────────────────────┐
                    │       FastAPI Backend                 │
                    │                                      │
                    │  /api/geopolitical/*                  │
                    │  /api/research/*                      │
                    │  /api/screener/*                      │
                    │  /api/indices/*                       │
                    │  /api/macro/*          (Phase 2)      │
                    │  /api/sector/*         (Phase 2)      │
                    │  /api/reports/*                       │
                    │  /api/stream/*         (SSE)          │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │     Data Layer (SQLite + Agents)      │
                    │                                      │
                    │  Existing:                            │
                    │  - stock_research_reports             │
                    │  - system_candidates                  │
                    │  - competitor_intel                   │
                    │  - debate_records                     │
                    │  - eod_prices / eod_institution_flows │
                    │                                      │
                    │  New:                                 │
                    │  - market_indices                     │
                    │  - geopolitical_events                │
                    │  - research_reports                   │
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
| 地緣政治新聞 | 每 4 小時 | GNews + Exa + RSS |
| 個股研究報告 | 每日 18:00 | stock_research agent |
| 辯論紀錄 | 每日 17:30 | debate_loop agent |
| 宏觀指標 | 每週（Phase 2）| FRED API |
| 賽道數據 | 每日盤後（Phase 2）| TWSE |

---

## 3. Phase 1A: Geopolitical Dashboard + Global Ticker (1 week)

### Goal
最先交付用戶最想要的功能：全球地緣政治事件地圖 + 全球市場指數 ticker。

### New DB Tables
```sql
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
```

### New Backend Files
| File | Purpose |
|------|---------|
| `src/openclaw/market_index_fetcher.py` | Fetch global indices from Yahoo Finance (TAIEX, ^GSPC, ^IXIC, ^DJI, ^N225, ^HSI, GC=F, CL=F, ^TNX, USDTWD=X) |
| `src/openclaw/agents/geopolitical_agent.py` | Expand competitor_monitor pattern for general geopolitical events |
| `frontend/backend/app/api/market_indices.py` | GET /api/indices/latest, /api/indices/history |
| `frontend/backend/app/api/geopolitical.py` | GET /api/geopolitical/events, /api/geopolitical/latest |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/Geopolitical.jsx` | Main geopolitical dashboard page |
| `src/components/WorldMap.jsx` | 2D world map with event markers (react-simple-maps) |
| `src/components/NewsFeed.jsx` | Scrollable news feed with sentiment badges |
| `src/components/GlobalTicker.jsx` | Top bar with global indices (scrolling ticker) |

### Page Layout — Geopolitical Dashboard
```
┌─────────────────────────────────────────────────────┐
│  GlobalTicker: TAIEX ▲0.5%  S&P500 ▼0.2%  ...      │
├─────────────────────────────────────────────────────┤
│                    │                                 │
│                    │   NewsFeed                      │
│    WorldMap        │   ┌──────────────────────┐     │
│    (60% width)     │   │ [🔴] Iran attacks... │     │
│                    │   │ [🟡] Fed hints...    │     │
│    • = event       │   │ [🟢] TSMC earnings.. │     │
│    size = impact   │   │ ...                  │     │
│    color = type    │   └──────────────────────┘     │
│                    │                                 │
│                    │   Market Impact Summary         │
│                    │   最受影響: 能源 ▲3.2%          │
│                    │   避險升溫: 黃金 ▲1.5%          │
│                    │                                 │
└─────────────────────────────────────────────────────┘
```

### npm Dependencies (Phase 1A only)
- `react-simple-maps` (40KB gzipped) — 2D world map
- `topojson-client` (2KB) — map data parser

---

## 4. Phase 1B: Stock Research + Market Screener (1-2 weeks)

### Goal
用現有 agent 輸出建出個股研究和選股工具。零新後端邏輯。

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
| `src/components/AIRatingBadge.jsx` | AI score display (confidence → 0-10 scale) |
| `src/components/RadarChart.jsx` | Technical/fundamental radar chart |

### Page Layout — Stock Analysis
```
┌─────────────────────────────────────────────────────┐
│  Stock: 2382 廣達    AI Score: 7.8 [A]     ▲ 271.5  │
├──────────────────────┬──────────────────────────────┤
│ Technical Layer      │ Institutional Layer           │
│ ┌──────────────────┐ │ 外資: 連買 5 日               │
│ │  Radar Chart     │ │ 投信: 連買 3 日               │
│ │ RSI/MACD/MA/Vol  │ │ 自營: 賣超                    │
│ └──────────────────┘ │ 融資: ▼                       │
├──────────────────────┴──────────────────────────────┤
│ AI Synthesis                                         │
│ 進場價: 265  停損: 250  目標價: 310                   │
│ 理由: AI 伺服器需求持續增長...                        │
├─────────────────────────────────────────────────────┤
│ Bull vs Bear Debate                                  │
│ [Bull 🟢] 題材強勁...  │  [Bear 🔴] 估值偏高...      │
│           [Arbiter] BUY (confidence: 78%)             │
└─────────────────────────────────────────────────────┘
```

### Page Layout — Market Screener
```
┌─────────────────────────────────────────────────────┐
│ Filters: [RSI < 30] [外資連買] [量能突破]  [篩選]    │
├─────────────────────────────────────────────────────┤
│                                                      │
│    ScatterChart                                      │
│    X: RSI14    Y: 量比    Size: 法人買超             │
│                                                      │
│         ●(2382)                                      │
│              ●(2330)                                 │
│    ●(2344)        ●(2408)                            │
│                                                      │
├─────────────────────────────────────────────────────┤
│ Ranked List (by AI score)                            │
│ 1. 2382 廣達  A  7.8  RSI:45  外資+5日              │
│ 2. 2344 華邦電 B  6.5  RSI:38  投信+3日              │
└─────────────────────────────────────────────────────┘
```

---

## 5. Phase 1C: Report Center (1 week)

### Goal
統一所有 AI 產出的報告到一個可閱讀的中心。

### New Backend Files
| File | Purpose |
|------|---------|
| `frontend/backend/app/api/research_reports.py` | GET /api/reports/list, /api/reports/{id}, POST /api/reports/generate |

### New Frontend Files
| File | Purpose |
|------|---------|
| `src/pages/ReportCenter.jsx` | Report listing + Markdown viewer |

### Report Types
| Type | Source | 頻率 |
|------|--------|------|
| 地緣政治 | geopolitical_agent | 每 4 小時 |
| 金融市場 | eod_analysis + market_research | 每日盤後 |
| 投資中心 | stock_research + debate_loop | 每日 18:00 |
| 資安快報 | CCT tech-risk-weekly | 每日 |

### npm Dependencies (Phase 1C)
- `react-markdown` (14KB) + `remark-gfm` (5KB) — Markdown rendering

---

## 6. Phase 2: Deep Data Integration (4-6 weeks)

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

### New npm Dependencies (Phase 2)
- `react-globe.gl` (300KB) — 3D globe
- New pip: `fredapi`, `feedparser`

---

## 7. Navigation Structure

```
├── 地緣政治          /geopolitical        (Phase 1A)
├── 金融市場          /market-tracker      (Phase 1A)
├── 投資中心          /research            
│   ├── 儀表板        /research            (Phase 1B)
│   ├── 個股分析      /research/stock      (Phase 1B)
│   ├── 全市場篩選    /research/screener   (Phase 1B)
│   ├── 宏觀分析      /research/macro      (Phase 2)
│   ├── 賽道分析      /research/sector     (Phase 2)
│   └── 資產宇宙      /research/universe   (Phase 2)
├── 報告中心          /reports             (Phase 1C)
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

## 8. Differentiation vs Reference Platform

| 他們 | 我們 |
|------|------|
| 靜態 AI 報告 | 8 個 Agent 即時辯論+研究+風控 |
| 單向分析 | Bull/Bear/Arbiter 多方觀點 |
| 通用推薦 | 針對你持倉組合客製化 |
| 付費訂閱 | 自建免費 |
| 無交易系統 | 直接連動 ai-trader 下單 |
| 無資安情報 | 整合 Security Red Team + 資安快報 |

---

## 9. Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Yahoo Finance API 不穩定 | 指數無法更新 | 多來源 fallback + cache 24hr |
| GNews 免費 100 req/day 不夠 | 新聞不足 | Exa AI search MCP 補充 + RSS |
| LLM 成本（地緣政治分析） | 月費增加 | 每日上限 50 LLM calls |
| react-simple-maps 功能有限 | 地圖不夠炫 | Phase 2 升級 3D globe |
| 免費數據延遲 | 資訊不即時 | 明確標示數據時效性 |

---

## 10. Success Criteria

Phase 1 完成後，你應該能夠：
- [ ] 開啟地緣政治頁面，看到 2D 世界地圖 + 即時新聞 feed + 影響評分
- [ ] 頂部 ticker bar 顯示全球 10+ 個指數/商品/債券
- [ ] 點擊任何 watchlist 股票，看到完整 AI 研究報告 + Bull/Bear 辯論
- [ ] 用散佈圖視覺化篩選候選股
- [ ] 在報告中心閱讀所有 AI 產出的報告
- [ ] 說出：「不用再開 Yahoo 股市了」
