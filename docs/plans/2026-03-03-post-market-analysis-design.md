# 盤後分析頁面設計文件

**日期**：2026-03-03
**狀態**：已核准，等待實作
**方案**：A — 靜態快照（盤後 Cron 生成）

---

## 一、需求摘要

| 面向 | 決定 |
|------|------|
| 使用時機 | 收盤後複盤（16:00–20:00） |
| 預測展示 | 技術面（支撐/壓力）+ 策略建議（多空/選股方向） |
| 資料來源 | 全套：EOD + 三大法人 + 技術指標（MA/RSI/MACD） |
| 頁面形式 | 新增 `/analysis` 專屬頁面 + Dashboard 小卡入口 |

---

## 二、架構概覽

```
Cron 16:30 → institution_ingest（三大法人）
Cron 16:35 → run_eod_analysis()
  ├─ 查 eod_prices（今日 + 歷史 60 天）
  ├─ 查 institution_flows（三大法人當日）
  ├─ 查 positions + config/watchlist.json
  ├─ 計算技術指標（MA5/20/60、RSI14、MACD12/26/9）
  ├─ 組 Prompt → Gemini API
  └─ 寫入 eod_analysis_reports

FastAPI /api/analysis/* → React /analysis 頁面
```

---

## 三、資料層

### 新增表：`eod_analysis_reports`

```sql
CREATE TABLE eod_analysis_reports (
  trade_date      TEXT PRIMARY KEY,  -- YYYY-MM-DD
  generated_at    INTEGER NOT NULL,  -- Unix ms
  market_summary  TEXT NOT NULL,     -- JSON：整體多空氣氛 + 板塊分析
  technical       TEXT NOT NULL,     -- JSON：per-symbol 技術指標
  strategy        TEXT NOT NULL,     -- JSON：明日策略建議（Gemini 生成）
  raw_prompt      TEXT,              -- 除錯用
  model_used      TEXT NOT NULL DEFAULT 'gemini-2.0-flash-preview'
);
```

### JSON Schema（`strategy` 欄位）

```json
{
  "market_outlook": {
    "sentiment": "bullish | neutral | bearish",
    "sector_focus": ["半導體", "金融"],
    "confidence": 0.75
  },
  "position_actions": [
    { "symbol": "2330", "action": "hold | reduce | stop_profit", "reason": "..." }
  ],
  "watchlist_opportunities": [
    { "symbol": "6442", "entry_condition": "...", "stop_loss": 2100 }
  ],
  "risk_notes": ["注意外資連續賣超", "MACD 死亡交叉出現"]
}
```

### JSON Schema（`technical` 欄位）

```json
{
  "2330": {
    "close": 1000.0,
    "ma5": 990.0, "ma20": 975.0, "ma60": 950.0,
    "rsi14": 58.3,
    "macd": { "macd": 12.5, "signal": 10.2, "histogram": 2.3 },
    "support": 960.0, "resistance": 1020.0
  }
}
```

---

## 四、後端元件

### 新增檔案

| 路徑 | 說明 |
|------|------|
| `src/openclaw/technical_indicators.py` | 技術指標純函數：calc_ma / calc_rsi / calc_macd / find_support_resistance |
| `src/openclaw/agents/eod_analysis.py` | EOD 分析 Agent（技術指標 + Gemini 策略） |
| `frontend/backend/app/api/analysis.py` | REST API：/latest / /{date} / /dates |

### Cron 排程（`config/cron_jobs.json` 或 agent_orchestrator.py）

| 時間（UTC） | 工作 |
|------------|------|
| 08:25 (16:25 TWN) | institution_ingest |
| 08:35 (16:35 TWN) | run_eod_analysis |

### API Endpoints

```
GET /api/analysis/latest        → 最新 eod_analysis_reports 一筆
GET /api/analysis/{trade_date}  → 指定日期（YYYY-MM-DD）
GET /api/analysis/dates         → 已有分析的日期陣列
```

全部走現有 `AuthMiddleware`（Bearer token）。

---

## 五、前端設計

### 頁面路由：`/analysis`（`Analysis.jsx`）

```
┌─────────────────────────────────────────────────────┐
│  盤後分析  [日期選擇器]  [最後更新時間]              │
├─────────────────────────────────────────────────────┤
│  Tab: [今日市場概覽] [個股技術分析] [AI 明日策略]    │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Tab 1 — 今日市場概覽                               │
│  ┌────────────────┬────────────────┐                │
│  │ 市場氣氛卡片   │ 主力板塊排行   │                │
│  │ 多空氣氛指標   │ (漲幅 / 成交量)│                │
│  └────────────────┴────────────────┘                │
│  ┌─────────────────────────────────┐                │
│  │ 三大法人流向（外資/投信/自營商）│                │
│  └─────────────────────────────────┘                │
│                                                     │
│  Tab 2 — 個股技術分析                               │
│  ┌─────────────────────────────────┐                │
│  │ 股票選擇器（持倉 + watchlist）  │                │
│  ├─────────────────────────────────┤                │
│  │ MA5/20/60 + 收盤價折線圖        │                │
│  ├──────────┬────────────┬─────────┤                │
│  │ RSI 14   │ MACD 直方  │ 支撐壓力│                │
│  └──────────┴────────────┴─────────┘                │
│                                                     │
│  Tab 3 — AI 明日策略                                │
│  ┌─────────────────────────────────┐                │
│  │ 整體市場展望（Gemini 生成）      │                │
│  ├─────────────────────────────────┤                │
│  │ 持倉建議（續倉/減倉/停利）       │                │
│  ├─────────────────────────────────┤                │
│  │ 觀察名單機會（可買進標的）       │                │
│  └─────────────────────────────────┘                │
└─────────────────────────────────────────────────────┘
```

### Dashboard 入口

在 Dashboard 現有 Panel 區塊新增「盤後市場氣氛」小卡：
- 顯示最新分析日期、多空氣氛、信心度
- 連結至 `/analysis`

### 導覽列

在側邊欄/頂部導覽新增「盤後分析」入口。

---

## 六、測試規範

| 模組 | 測試策略 |
|------|---------|
| `technical_indicators.py` | 100% unit test，純函數，固定輸入驗固定輸出 |
| `eod_analysis.py` | mock Gemini + mock DB，測資料查詢與 DB 寫入路徑 |
| `analysis.py` (API) | auth 401 + latest 200 + 指定日期 200 / 404 |
| `Analysis.jsx` | Tab 切換 + loading state + 無資料空狀態 |

---

## 七、實作順序（建議）

1. **`technical_indicators.py`** — 純函數，先寫測試再實作（TDD）
2. **DB migration** — 新增 `eod_analysis_reports` 表
3. **`eod_analysis.py` agent** — 技術指標 + Gemini 分析
4. **Cron 新增排程**（institution_ingest 16:25 + eod_analysis 16:35）
5. **`analysis.py` API** — 3 個 endpoints
6. **`Analysis.jsx` 前端** — Tab 版面 + 圖表
7. **Dashboard 小卡**
8. **導覽列新增入口**
9. **CI 確認**

---

## 八、相依性

- `institution_ingest.py` 需先完成當日 run（三大法人資料需在 16:25 前 ingest）
- `eod_prices` 需有當日資料（已由現有 Cron `eod-ingest-8888` 16:00 後自動 ingest）
- Gemini API key 已設定於 `frontend/backend/.env`
