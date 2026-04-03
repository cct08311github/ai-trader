# AI Investment Research Platform — Phase 1 Implementation Plan

**Date:** 2026-04-03
**Author:** Zug (Claude Code)
**Design Spec:** `docs/superpowers/specs/2026-04-03-investment-research-platform-design.md` (v3)
**Issue:** #557

---

## Overview

Phase 1 為期 4 週，拆分為 11 個 GitHub Issue，按依賴關係分四個子階段推進。
每個 Issue 對應一個 branch、一個 PR，遵循 `Closes #N` 規範。

### Dependency Graph

```
Issue 1 (Backend Infra) ──┬──→ Issue 3 (Market Index) ──→ Issue 4 (Dashboard)
                          │                                     │
Issue 2 (Frontend Infra) ─┤──→ Issue 5 (Research API) ──→ Issue 6 (Stock Analysis)
                          │                              │
                          ├──→ Issue 7 (Screener)        │
                          │                              │
                          ├──→ Issue 8 (Risk Dashboard) ←┘
                          │
                          ├──→ Issue 9 (Geopolitical Agent)──→ Issue 10 (Geo Page)
                          │
                          └──→ Issue 11 (Report Center)
```

---

## Phase 1A — Week 1: Infrastructure + Dashboard

### Issue 1: Backend Infrastructure

**Title:** `feat(backend): research platform backend infrastructure — cache, circuit breaker, DB init`

**Labels:** `enhancement`, `backend`, `infrastructure`

**Dependencies:** None (first issue)

**Estimated Effort:** 1.5 days

**Description:**
建立後端基礎設施：cache layer、circuit breaker、research.db 初始化（含 WAL mode）、統一 API response envelope、data_source_health 表。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/backend/app/core/cache.py` | TTL cache decorator + HTTP Cache-Control helpers |
| Create | `frontend/backend/app/core/circuit_breaker.py` | Circuit Breaker pattern for external API calls |
| Create | `frontend/backend/app/core/response.py` | Unified response envelope with pagination + freshness metadata |
| Create | `frontend/backend/app/core/database.py` | research.db init with `PRAGMA journal_mode=WAL`, connection factory |
| Modify | `frontend/backend/app/main.py` | Register CORS (localhost + Tailscale), lifespan events for DB init |
| Create | `tests/test_cache.py` | Cache decorator unit tests |
| Create | `tests/test_circuit_breaker.py` | Circuit breaker state transition tests |
| Create | `tests/test_response.py` | Response envelope format tests |

**DB Schema (research.db init):**
- `market_indices` table
- `data_source_health` table
- `PRAGMA journal_mode=WAL`

**Acceptance Criteria:**
- [ ] `research.db` 自動建立，WAL mode 已啟用
- [ ] `cache.py` TTL decorator 可用於任何 async function
- [ ] `circuit_breaker.py` 支援 open/half-open/closed 三狀態
- [ ] `response.py` 產生統一 JSON envelope（含 data, meta.total, meta.data_freshness, meta.cache_hit）
- [ ] CORS 僅允許 localhost:5173 + Tailscale IP
- [ ] 所有 unit tests 通過

---

### Issue 2: Frontend Infrastructure

**Title:** `feat(frontend): research platform frontend infrastructure — TanStack Query, design tokens, shared components`

**Labels:** `enhancement`, `frontend`, `infrastructure`

**Dependencies:** None (can parallel with Issue 1)

**Estimated Effort:** 1.5 days

**Description:**
建立前端基礎設施：TanStack Query provider、design tokens（tailwind.config.js）、共享元件庫、ResearchLayout、測試框架設定。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Modify | `frontend/tailwind.config.js` | Design tokens: spacing (4px base), borderRadius, fontSize, boxShadow |
| Modify | `frontend/src/App.jsx` or router | TanStack Query `QueryClientProvider` wrap |
| Create | `frontend/src/lib/queryClient.js` | QueryClient config (staleTime, gcTime, retry) |
| Create | `frontend/src/lib/api.js` | Fetch wrapper with base URL, error handling |
| Create | `frontend/src/components/ui/DataCard.jsx` | 通用數據卡片 |
| Create | `frontend/src/components/ui/MetricBadge.jsx` | 指標徽章（箭頭 + 符號輔助色盲） |
| Create | `frontend/src/components/ui/SentimentIndicator.jsx` | 情緒指標 |
| Create | `frontend/src/components/ui/AlertBadge.jsx` | R/Y/G 三色警報徽章 |
| Create | `frontend/src/layouts/ResearchLayout.jsx` | 投資中心共用 layout（sidebar + content） |
| Modify | `frontend/package.json` | Add @tanstack/react-query, vitest, @testing-library/react, msw |
| Create | `frontend/src/test/setup.js` | Vitest + RTL setup |
| Create | `frontend/vitest.config.js` | Vitest configuration |
| Create | `frontend/src/mocks/handlers.js` | MSW mock handlers for /api/* |
| Create | `frontend/src/mocks/server.js` | MSW server setup |
| Create | `frontend/src/components/ui/__tests__/DataCard.test.jsx` | DataCard component tests |
| Create | `frontend/src/components/ui/__tests__/MetricBadge.test.jsx` | MetricBadge component tests |

**npm Dependencies (new):**
- `@tanstack/react-query` (v5)
- `vitest` (devDep)
- `@testing-library/react` (devDep)
- `@testing-library/jest-dom` (devDep)
- `jsdom` (devDep)
- `msw` (devDep)

**Acceptance Criteria:**
- [ ] TanStack Query provider 正確包裹 app
- [ ] tailwind.config.js 包含完整 design tokens
- [ ] 4 個共享元件均有 Storybook-style 測試
- [ ] MSW mock server 可攔截 `/api/*`
- [ ] `npm run test` 執行 vitest 通過
- [ ] ResearchLayout 支援 nested routes

---

### Issue 3: Market Index Fetcher + API

**Title:** `feat(data): market index fetcher + /api/indices/* endpoints + GlobalTicker`

**Labels:** `enhancement`, `backend`, `data-pipeline`

**Dependencies:** Issue 1 (需要 cache, circuit_breaker, response envelope, research.db)

**Estimated Effort:** 1 day

**Description:**
建立全球指數抓取 pipeline（Yahoo Finance）、API endpoints、GlobalTicker 前端元件。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/openclaw/market_index_fetcher.py` | Fetch 14+ indices from Yahoo Finance, write to research.db |
| Create | `frontend/backend/app/api/market_indices.py` | GET /api/indices/latest, /api/indices/history?days=30 |
| Create | `frontend/src/components/GlobalTicker.jsx` | 頂部 ticker bar (aria-live="polite", < 640px 改 swipe) |
| Create | `frontend/src/hooks/useIndices.js` | TanStack Query hook for indices |
| Modify | `ecosystem.config.js` | Add market-index-fetcher PM2 process (cron_restart: */5) |
| Create | `tests/test_market_index_fetcher.py` | Fetcher unit tests |

**Acceptance Criteria:**
- [ ] `market_index_fetcher.py` 可抓取 14 個指數並寫入 research.db
- [ ] Circuit breaker 保護 Yahoo Finance 呼叫
- [ ] `/api/indices/latest` 回傳所有指數最新數據（含 freshness metadata）
- [ ] GlobalTicker 元件顯示指數 + 漲跌（箭頭符號輔助）
- [ ] PM2 排程每 5 分鐘執行（盤中）
- [ ] Mobile (< 640px) 改為橫向滑動

---

### Issue 4: Dashboard Page

**Title:** `feat(frontend): 戰情總覽 Dashboard — alerts, portfolio summary, market pulse`

**Labels:** `enhancement`, `frontend`

**Dependencies:** Issue 1 (API envelope), Issue 2 (shared components), Issue 3 (GlobalTicker, indices)

**Estimated Effort:** 2 days

**Description:**
建立戰情總覽頁面，含三色警報系統（Red Alert 附行動按鈕）、Portfolio P&L、異常個股、Market Overview、Key News。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/backend/app/api/dashboard.py` | GET /api/dashboard/overview (alerts, P&L, market summary) |
| Create | `frontend/src/pages/Dashboard.jsx` | 戰情總覽主頁（default home） |
| Create | `frontend/src/components/AlertPanel.jsx` | 三色警報面板 + Action Queue 按鈕（停損/加碼/忽略） |
| Create | `frontend/src/components/PortfolioSummary.jsx` | Portfolio P&L 摘要 |
| Create | `frontend/src/components/AnomalyList.jsx` | 異常個股列表 |
| Create | `frontend/src/hooks/useDashboard.js` | TanStack Query hook for dashboard |
| Modify | `frontend/src/App.jsx` or router | Set Dashboard as default home route |

**Mobile Responsive:**
- < 768px: 單欄堆疊（alerts → portfolio → anomaly → market → news）

**Acceptance Criteria:**
- [ ] Dashboard 為預設首頁 (`/dashboard`)
- [ ] Red/Yellow/Green 三色警報正確分類並按優先序排列
- [ ] Red Alert 旁有行動按鈕（execute stop-loss, add position, dismiss）
- [ ] Portfolio P&L 顯示總資產、今日損益、持股數
- [ ] 異常個股列表可點擊導航至 Stock Analysis
- [ ] < 768px 改為單欄堆疊
- [ ] Playwright E2E: Dashboard 載入 + 數據顯示

---

## Phase 1B — Week 1-2: Stock Research + Screener

### Issue 5: Stock Research API

**Title:** `feat(backend): stock research API — /api/research/stocks, /api/research/debate`

**Labels:** `enhancement`, `backend`, `api`

**Dependencies:** Issue 1 (cache, circuit_breaker, response envelope)

**Estimated Effort:** 1 day

**Description:**
建立個股研究 API，從 trades.db (read-only) 讀取 stock_research_reports + debate_records + system_candidates，整合為統一 API。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/backend/app/api/research.py` | GET /api/research/stocks (list), GET /api/research/stocks/{symbol} (detail), GET /api/research/debate/{symbol} |
| Create | `tests/test_research_api.py` | API endpoint tests |

**API Endpoints:**
- `GET /api/research/stocks` — 所有研究報告列表（pagination, sort by AI score）
- `GET /api/research/stocks/{symbol}` — 單一個股詳細報告（含 AI scoring breakdown）
- `GET /api/research/debate/{symbol}` — Bull/Bear/Arbiter 辯論紀錄
- 每個 endpoint 均有 portfolio cross-reference 欄位（若為持倉股）

**Acceptance Criteria:**
- [ ] trades.db 以 read-only + `PRAGMA query_only=ON` 連線
- [ ] 回傳統一 envelope 格式
- [ ] 持倉股票回傳 portfolio_position 欄位（cost, unrealized_pnl, weight）
- [ ] 分頁正確（default 20 per page）
- [ ] Unit tests 通過

---

### Issue 6: Stock Analysis Page

**Title:** `feat(frontend): Stock Analysis page — AI scoring, fundamentals, debate, K-line chart, portfolio cross-ref`

**Labels:** `enhancement`, `frontend`

**Dependencies:** Issue 2 (shared components, TanStack Query), Issue 5 (research API)

**Estimated Effort:** 2 days

**Description:**
建立個股分析頁面，含四維度 AI 評分雷達圖、基本面數據、Bull/Bear 辯論面板、K 線圖（lightweight-charts）、持倉交叉參考。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/src/pages/Research/StockAnalysis.jsx` | 個股分析主頁 |
| Create | `frontend/src/components/AIRatingBadge.jsx` | AI Score + Confidence 分離顯示 |
| Create | `frontend/src/components/RadarChart.jsx` | 四維度雷達圖 (Tech/Inst/Fund/Event) |
| Create | `frontend/src/components/ScoreHistory.jsx` | 分數變化追蹤 |
| Create | `frontend/src/components/KLineChart.jsx` | K 線圖 + MA overlay (lightweight-charts) |
| Create | `frontend/src/components/DebatePanel.jsx` | Bull/Bear/Arbiter 辯論面板 |
| Create | `frontend/src/components/PortfolioCrossRef.jsx` | 持倉交叉參考 bar（cost, P&L, weight） |
| Create | `frontend/src/hooks/useStockResearch.js` | TanStack Query hooks |
| Modify | `frontend/package.json` | Add lightweight-charts |

**npm Dependencies (new):**
- `lightweight-charts` (TradingView, 40KB gzipped)

**Acceptance Criteria:**
- [ ] 四維度 AI 評分雷達圖正確渲染
- [ ] K 線圖顯示 candlestick + MA 5/10/20/60 overlay
- [ ] 持倉股票頂部顯示 portfolio cross-reference bar（cost, unrealized P&L, weight）
- [ ] Bull/Bear/Arbiter 辯論面板完整呈現
- [ ] 基本面數據：P/E, P/B, EPS, 殖利率, 月營收 YoY/MoM
- [ ] Playwright E2E: Stock Analysis 導航 + 報告渲染

---

### Issue 7: Market Screener API + Page

**Title:** `feat(fullstack): Market Screener — scatter chart, filters, canvas rendering for 500+ points`

**Labels:** `enhancement`, `frontend`, `backend`

**Dependencies:** Issue 1 (backend infra), Issue 2 (frontend infra), Issue 5 (research API for stock data)

**Estimated Effort:** 1.5 days

**Description:**
建立全市場篩選器 — ScatterChart 視覺化 + 多條件篩選。超過 300 點使用 canvas rendering。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/backend/app/api/screener.py` | GET /api/screener/candidates, /api/screener/scatter |
| Create | `frontend/src/pages/Research/MarketScreener.jsx` | 篩選器主頁 |
| Create | `frontend/src/components/ScatterChart.jsx` | Canvas scatter chart (@visx/visx for >300 points) |
| Create | `frontend/src/components/FilterBar.jsx` | RSI, 外資連買, 量能突破, 殖利率 篩選 |
| Create | `frontend/src/hooks/useScreener.js` | TanStack Query hooks |
| Modify | `frontend/package.json` | Add @visx/visx (or specific @visx packages) |

**npm Dependencies (new):**
- `@visx/xychart`, `@visx/scale`, `@visx/tooltip` (canvas scatter)

**Performance Target:**
- 500 data points render < 200ms
- > 300 points: 自動切換 canvas rendering
- Fallback: `isAnimationActive={false}` + 分頁 (100 per page)

**Acceptance Criteria:**
- [ ] ScatterChart 可視化：X=RSI14, Y=量比, Size=法人買超
- [ ] 篩選器支援多條件組合
- [ ] 500+ 點 render < 200ms（canvas mode）
- [ ] < 768px: ScatterChart 替換為排序列表
- [ ] 點擊散佈點導航至 Stock Analysis
- [ ] Playwright E2E: 篩選 + 散佈圖渲染

---

## Phase 1C — Week 2-3: Risk Dashboard

### Issue 8: Risk Dashboard Page

**Title:** `feat(fullstack): Risk Dashboard — concentration treemap, correlation heatmap, drawdown, stop-loss, stress tests`

**Labels:** `enhancement`, `frontend`, `backend`, `risk`

**Dependencies:** Issue 1 (backend infra), Issue 2 (frontend infra)

**Estimated Effort:** 2.5 days

**Description:**
建立風險管理儀表板，含集中度 Treemap、相關性熱力圖、最大回撤、停損追蹤、壓力測試。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/openclaw/risk_calculator.py` | 每日計算風險指標，寫入 risk_snapshots |
| Create | `frontend/backend/app/api/risk.py` | GET /api/risk/overview, /concentration, /correlation, /stress-test |
| Create | `frontend/src/pages/RiskDashboard.jsx` | 風險儀表板主頁 |
| Create | `frontend/src/components/ConcentrationTreemap.jsx` | Treemap by 個股/產業/國家 |
| Create | `frontend/src/components/CorrelationHeatmap.jsx` | 持股相關性矩陣熱力圖 |
| Create | `frontend/src/components/DrawdownChart.jsx` | 最大回撤追蹤圖 |
| Create | `frontend/src/components/StopLossTracker.jsx` | 停損執行追蹤 + Action 按鈕 |
| Create | `frontend/src/hooks/useRisk.js` | TanStack Query hooks |
| Modify | `ecosystem.config.js` | Add risk-calculator PM2 process (cron: 30 22 * * 1-5) |
| Create | `tests/test_risk_calculator.py` | Risk calculator unit tests |

**DB Schema:**
- `risk_snapshots` table (已定義於 design spec)

**Acceptance Criteria:**
- [ ] 集中度 Treemap 可按個股/產業/國家切換
- [ ] 相關性矩陣顯示持股間 correlation coefficients
- [ ] 最大回撤追蹤含歷史趨勢圖
- [ ] 停損追蹤顯示各持股距停損距離 + 顏色警示
- [ ] 5 個壓力測試情境均可模擬（TWD+5%, 10Y+100bp, DRAM-30%, VIX>35, SOX-15%）
- [ ] PM2 每日 22:30 自動計算風險快照
- [ ] risk_calculator unit tests 通過

---

## Phase 1D — Week 3-4: Geopolitical + Reports

### Issue 9: Geopolitical Agent + API

**Title:** `feat(backend): geopolitical agent — expand competitor_monitor pattern + /api/geopolitical/* endpoints`

**Labels:** `enhancement`, `backend`, `agent`

**Dependencies:** Issue 1 (backend infra, circuit_breaker for GNews/Exa)

**Estimated Effort:** 1.5 days

**Description:**
擴展 competitor_monitor pattern，建立通用地緣政治事件抓取 agent + API。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/openclaw/agents/geopolitical_agent.py` | GNews + Exa + RSS 抓取，LLM 評估 impact_score |
| Create | `frontend/backend/app/api/geopolitical.py` | GET /api/geopolitical/events, /api/geopolitical/latest, /api/geopolitical/by-region |
| Modify | `ecosystem.config.js` | Add geopolitical-agent PM2 process (cron: 0 */4 * * *) |
| Create | `tests/test_geopolitical_agent.py` | Agent unit tests |

**DB Schema:**
- `geopolitical_events` table (已定義於 design spec)

**Acceptance Criteria:**
- [ ] Agent 從 GNews + Exa + RSS 抓取事件
- [ ] LLM 評估每個事件的 impact_score (0-10) 和 market_impact
- [ ] 每日 LLM 呼叫上限 50 次
- [ ] API 支援按 region/category/impact_score 篩選
- [ ] Circuit breaker 保護所有外部 API 呼叫
- [ ] PM2 每 4 小時執行
- [ ] Unit tests 通過

---

### Issue 10: Geopolitical Dashboard Page

**Title:** `feat(frontend): Geopolitical Dashboard — WorldMap, NewsFeed, impact analysis`

**Labels:** `enhancement`, `frontend`

**Dependencies:** Issue 2 (frontend infra), Issue 9 (geopolitical API)

**Estimated Effort:** 1.5 days

**Description:**
建立地緣政治儀表板，含 2D 世界地圖 + 新聞 feed + 市場影響分析。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/src/pages/Geopolitical.jsx` | 地緣政治儀表板主頁 |
| Create | `frontend/src/components/WorldMap.jsx` | 2D 地圖 (react-simple-maps) + event markers |
| Create | `frontend/src/components/NewsFeed.jsx` | 可捲動新聞列表 + sentiment badges |
| Create | `frontend/src/components/ImpactSummary.jsx` | 市場影響摘要 |
| Create | `frontend/src/hooks/useGeopolitical.js` | TanStack Query hooks |
| Modify | `frontend/package.json` | Add react-simple-maps, topojson-client |

**npm Dependencies (new):**
- `react-simple-maps` (40KB gzipped)
- `topojson-client` (2KB)

**Acceptance Criteria:**
- [ ] WorldMap 顯示事件標記（size = impact, color = category）
- [ ] 點擊標記顯示事件詳情
- [ ] NewsFeed 含 R/Y/G sentiment badges
- [ ] < 768px: WorldMap 替換為排序列表
- [ ] Market Impact Summary 顯示最受影響的 sectors

---

### Issue 11: Report Center Page

**Title:** `feat(fullstack): Report Center — report listing, Markdown rendering, report generation`

**Labels:** `enhancement`, `frontend`, `backend`

**Dependencies:** Issue 1 (backend infra), Issue 2 (frontend infra)

**Estimated Effort:** 1 day

**Description:**
建立報告中心，統一呈現所有 AI 產出的報告（地緣政治、市場、投資、資安、風險日報）。

**Scope / Files to Create or Modify:**

| Action | File | Purpose |
|--------|------|---------|
| Create | `frontend/backend/app/api/research_reports.py` | GET /api/reports/list, /api/reports/{id}, POST /api/reports/generate |
| Create | `frontend/src/pages/ReportCenter.jsx` | 報告列表 + Markdown viewer |
| Create | `frontend/src/components/ReportCard.jsx` | 報告摘要卡片 |
| Create | `frontend/src/hooks/useReports.js` | TanStack Query hooks |
| Modify | `frontend/package.json` | Add react-markdown, remark-gfm |

**DB Schema:**
- `research_reports` table (已定義於 design spec)

**npm Dependencies (new):**
- `react-markdown` (14KB)
- `remark-gfm` (5KB)

**Acceptance Criteria:**
- [ ] 報告列表可按 type/date 篩選排序
- [ ] Markdown 渲染正確（含 GFM tables, code blocks）
- [ ] 5 種報告類型均可正確顯示
- [ ] POST /api/reports/generate 可手動觸發報告產生
- [ ] 分頁 + 統一 envelope 格式

---

## Summary Table

| Issue | Title | Phase | Effort | Dependencies |
|-------|-------|-------|--------|--------------|
| 1 | Backend Infrastructure | 1A | 1.5d | None |
| 2 | Frontend Infrastructure | 1A | 1.5d | None |
| 3 | Market Index Fetcher + API | 1A | 1d | #1 |
| 4 | Dashboard Page | 1A | 2d | #1, #2, #3 |
| 5 | Stock Research API | 1B | 1d | #1 |
| 6 | Stock Analysis Page | 1B | 2d | #2, #5 |
| 7 | Market Screener | 1B | 1.5d | #1, #2, #5 |
| 8 | Risk Dashboard | 1C | 2.5d | #1, #2 |
| 9 | Geopolitical Agent + API | 1D | 1.5d | #1 |
| 10 | Geopolitical Dashboard | 1D | 1.5d | #2, #9 |
| 11 | Report Center | 1D | 1d | #1, #2 |
| **Total** | | | **17.5d** | |

**Critical Path:** Issue 1 → Issue 3 → Issue 4 (Dashboard, Week 1 deliverable)

**Parallel Tracks (after Issue 1+2):**
- Track A: Issue 5 → Issue 6 (Stock Research)
- Track B: Issue 7 (Screener)
- Track C: Issue 8 (Risk)
- Track D: Issue 9 → Issue 10 (Geopolitical)
- Track E: Issue 11 (Reports)

---

## Execution Notes

1. **Issue 1 + Issue 2 可同時開始**（無依賴關係），最快 Week 1 Day 2 完成
2. **PM2 排程統一在 Issue 1 框架下建立**，各 pipeline Issue 補上具體 process
3. **Testing 框架在 Issue 2 建立**，後續 Issue 增量加入測試
4. **ecosystem.config.js 的 Telegram token 移至 .env** 為 P0 安全修復，應在 Issue 1 前單獨處理（或併入 Issue 1）
5. **每個 Issue 的 PR 必須包含 `Closes #N`**，確保 Issue 自動關閉
