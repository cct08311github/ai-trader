# 雙源選股候選池設計（Dual-Source Watchlist）

> 2026-03-06 | 方案 B：規則篩選器 + LLM 精篩

---

## 一、問題

現有 `watchlist.json` 的 `universe` 是唯一股票來源，`ticker_watcher` 只從手動池篩選 top movers。缺少系統主動發現潛力股的機制。

**目標架構**：
```
來源 A：系統每日盤後自動篩選上漲潛力股（規則 + Gemini 精篩）
來源 B：使用者手動維護的長期追蹤股

合流 → 全部納入 active 監控與交易（無上限）
```

---

## 二、資料結構

### 新增 DB 表 `system_candidates`

```sql
CREATE TABLE IF NOT EXISTS system_candidates (
    symbol        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    label         TEXT NOT NULL,       -- 'short_term' | 'long_term'
    score         REAL NOT NULL,       -- 0.0 ~ 1.0
    source        TEXT NOT NULL,       -- 'rule_screener'
    reasons       TEXT,                -- JSON: ["法人連3買","MA5>MA20"]
    llm_filtered  INTEGER NOT NULL DEFAULT 0,  -- 1=經過 Gemini 精篩, 0=僅規則
    expires_at    TEXT NOT NULL,       -- ISO date
    created_at    INTEGER NOT NULL,    -- epoch ms
    PRIMARY KEY (symbol, trade_date, label)
);
```

**過期策略**：
- 短線候選：3 天過期
- 長線候選：5 天過期
- `ticker_watcher` 載入時 `WHERE expires_at >= date('now')` 過濾

### `config/watchlist.json` 新結構

```json
{
  "manual_watchlist": ["2330", "2317", "3008"],
  "max_system_candidates": 10,
  "screener": {
    "enabled": true,
    "short_term": {
      "min_volume_ratio": 1.5,
      "min_foreign_net_days": 2,
      "require_ma_cross": true
    },
    "long_term": {
      "min_foreign_net_days": 5,
      "margin_decrease_days": 3,
      "require_ma_bullish": true
    }
  }
}
```

- `universe` 欄位移除，改為 `manual_watchlist`
- 向後相容：讀到 `universe` 時自動視為 `manual_watchlist`

---

## 三、規則篩選引擎 `stock_screener.py`

### 篩選範圍

從 `eod_prices` 全市場股票篩選，排除：
- 當日成交量 < 500 張
- 已在 `manual_watchlist` 中的股票

### 短線策略規則（`short_term`，符合 >=2 條入選）

| 規則 | 分數 | 資料來源 |
|------|------|---------|
| 量能爆發：當日量 >= 前5日均量 x 1.5 | +0.25 | `eod_prices` |
| 法人急買：外資+投信 net > 0 連續 >= 2 日 | +0.25 | `eod_institution_flows` |
| 技術突破：MA5 上穿 MA20 | +0.25 | `calc_ma()` |
| RSI 回升：RSI14 從 < 30 回升至 30~50 | +0.15 | `calc_rsi()` |
| 股價突破壓力位 | +0.10 | `find_support_resistance()` |

### 長線策略規則（`long_term`，符合 >=2 條入選）

| 規則 | 分數 | 資料來源 |
|------|------|---------|
| 法人穩定佈局：外資 net > 0 連續 >= 5 日 | +0.30 | `eod_institution_flows` |
| 融資減少：融資餘額連續 >= 3 日下降 | +0.20 | `eod_margin_data` |
| 均線多頭排列：MA5 > MA20 > MA60 | +0.25 | `calc_ma()` |
| MACD 翻正：histogram 由負轉正 | +0.15 | `calc_macd()` |
| 股價站穩支撐位上方 | +0.10 | `find_support_resistance()` |

### 評分與截取

- 各類別依 score 降序
- 短線/長線各最多取 `max_system_candidates / 2`（預設各 5 支）
- 避免單邊偏重

### Gemini 精篩

- 規則候選送 Gemini 二次確認，移除明顯不適合的
- 成功：`llm_filtered = 1`
- **失敗 fallback**：直接用規則結果，`llm_filtered = 0`，前端顯示警示

---

## 四、整合流程

```
eod_analysis.py 16:35（擴充現有 cron）
  |-- market_data_fetcher.run_daily_fetch()        # 已有
  |-- stock_screener.screen_candidates(conn)        # 新增
  |   |-- 規則篩選 -> 候選 10~20 支
  |   +-- Gemini 精篩 -> 寫入 system_candidates
  |       +-- 失敗 fallback -> llm_filtered=0
  |-- Gemini 盤後分析（現有）
  +-- 寫 eod_analysis_reports（現有）

ticker_watcher.py 08:50
  |-- manual = load_manual_watchlist()              # config
  |-- system = load_system_candidates(conn)         # DB, 未過期
  +-- active = list(set(manual + system))           # 合流去重，全部監控
```

---

## 五、API 變更

### `GET /api/settings/watchlist`

```json
{
  "manual_watchlist": ["2330", "2317", "3008"],
  "system_candidates": [
    {
      "symbol": "6442", "name": "光聖",
      "label": "short_term", "score": 0.75,
      "reasons": ["量能爆發(2.1x)", "外資連2買"],
      "llm_filtered": true,
      "trade_date": "2026-03-06", "expires_at": "2026-03-09"
    }
  ],
  "active_symbols": ["2330", "2317", "3008", "6442"],
  "screener": { "enabled": true }
}
```

### `PUT /api/settings/watchlist`

```json
{ "manual_watchlist": ["2330", "2317", "3008"] }
```

---

## 六、前端 Settings.jsx

### 區塊 1：我的追蹤清單
- 可增刪股票，紫色標籤
- 存 `config/watchlist.json` → `manual_watchlist`

### 區塊 2：系統推薦候選
- 唯讀卡片，每張顯示：
  - 股票代碼 + 名稱
  - 標籤 badge：短線（橘）/ 長線（藍）
  - 評分進度條
  - 入選理由
  - 過期日
  - `llm_filtered=false` 時顯示黃色警示「僅規則篩選，未經 AI 驗證」
- 「加入追蹤」按鈕 → 加入 manual_watchlist

### 區塊 3：目前監控中（Active）
- 合流後最終清單，唯讀
- 來源標記：手動（紫）/ 短線推薦（橘）/ 長線推薦（藍）

---

## 七、向後相容

- `watchlist.json` 存在 `universe` 時，自動視為 `manual_watchlist`
- `_load_universe()` 改名 `_load_manual_watchlist()`，加 fallback

---

## 八、新增/修改檔案清單

| 操作 | 檔案 | 說明 |
|------|------|------|
| 新增 | `src/openclaw/stock_screener.py` | 規則篩選引擎 + Gemini 精篩 |
| 新增 | `src/tests/test_stock_screener.py` | 篩選引擎測試 |
| 修改 | `src/openclaw/agents/eod_analysis.py` | 整合 stock_screener |
| 修改 | `src/openclaw/ticker_watcher.py` | 雙源合流載入 |
| 修改 | `config/watchlist.json` | 結構遷移 |
| 修改 | `frontend/backend/app/api/settings.py` | API 改回傳雙源 |
| 修改 | `frontend/web/src/pages/Settings.jsx` | UI 雙區塊 |
| 新增 | `frontend/backend/tests/test_settings_watchlist.py` | API 測試 |
| 修改 | 現有 Settings 測試 | 適配新結構 |
