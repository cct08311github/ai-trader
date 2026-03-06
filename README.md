# AI Trader

台股 AI 自動交易系統，整合 LLM 決策、風控引擎、Portfolio 管理與即時監控前端。

## 系統架構

```
Telegram / 前端 → FastAPI (port 8000) → SQLite (trades.db)
                                      ↑
ticker_watcher (每 3 分鐘掃盤)        │
agent_orchestrator (Gemini agents)   ─┘
```

| 層級 | 路徑 | 說明 |
|------|------|------|
| 核心引擎 | `src/openclaw/` | Python 決策管線、PM 辯論、風控、選股 |
| FastAPI 後端 | `frontend/backend/` | REST API + SSE |
| React 前端 | `frontend/web/` | Vite + Tailwind，即時儀表板 |
| 設定 | `config/` | system_state.json、watchlist.json |
| 資料庫 | `data/sqlite/trades.db` | 唯一共用 SQLite |

## 主要功能

- **Portfolio 管理**：持倉追蹤、未實現損益即時回寫、損益曲線
- **AI 決策管線**：PM 辯論（Bull/Bear/Arbiter）、每日審核、風控引擎
- **全自動策略審查**：Gemini 每日盤前 PM review + 盤中 pending proposals 自動核准/拒絕，Telegram 雙向通知
- **EOD 驅動信號**：MA5/MA20 黃金交叉 + RSI 確認；Trailing Stop 動態收緊（獲利 >50% 時 5%→3%）
- **集中度守衛**：單檔 >60% 自動減倉提案；40-60% Gemini 審查後核准
- **盤後分析**：每日 16:35 自動計算 MA/RSI/MACD + Gemini 策略建議 → `/analysis` 頁面
- **K 線圖**：點擊持倉顯示 60 日日線蠟燭圖（純 SVG）+ 成交量
- **即時報價**：Shioaji BidAsk SSE → 五檔行情；休市時自動 fallback 至最後 EOD 收盤資料
- **多 Agent 排程**：市場研究/Portfolio 審核/策略委員會/系統優化/健康監控
- **Chat 助手**：浮動視窗，SSE 串流回應

## 快速啟動

```bash
# 查看服務狀態
pm2 status

# 重啟所有 AI Trader 服務
pm2 restart ai-trader-api ai-trader-web ai-trader-watcher ai-trader-agents

# 啟用/重載排程運維工作
pm2 start ecosystem.config.js --only ai-trader-ops-summary,ai-trader-reconciliation,ai-trader-incident-hygiene
pm2 reload ecosystem.config.js --only ai-trader-ops-summary,ai-trader-reconciliation,ai-trader-incident-hygiene

# 查看 log
pm2 logs ai-trader-api --lines 50
tail -f logs/gateway.err.log
```

## API 路由

| 前綴 | 說明 |
|------|------|
| `/api/auth` | Bearer token 登入 |
| `/api/portfolio` | 持倉、交易紀錄 |
| `/api/portfolio/quote/{symbol}` | 即時快照（休市時 fallback EOD） |
| `/api/portfolio/kline/{symbol}?days=60` | K 線 OHLCV（查 eod_prices） |
| `/api/portfolio/quote-stream/{symbol}` | BidAsk SSE 五檔即時推送 |
| `/api/strategy` | 提案、LLM traces |
| `/api/analysis` | 盤後分析快照（latest / dates / {date}） |
| `/api/pm` | PM review 觸發 |
| `/api/system` | 系統狀態開關 |
| `/api/chat` | AI 助手 SSE |
| `/api/stream` | Log SSE |
| `/api/control` | 緊急停止、模式切換 |
| `/api/settings` | 系統設定 |

## 前端頁面

| 路徑 | 說明 |
|------|------|
| `/portfolio` | 持倉、KPI、損益曲線 |
| `/trades` | 訂單 / 成交紀錄 |
| `/strategy` | 提案、LLM trace 透明化 |
| `/analysis` | 盤後分析（市場概覽 / 個股技術 / AI 策略） |
| `/agents` | Agent 執行狀態 |
| `/system` | 主開關、設定 |

## 安全模型

```
trading_enabled = true  AND  .EMERGENCY_STOP 不存在  →  自動交易啟動
simulation_mode = true  →  模擬盤（預設，不影響真實部位）
```

切換至實際盤前，務必確認 `simulation_mode: false` + `trading_enabled: true`。

## 測試

```bash
# 核心引擎（Python）
PYTHONPATH=src python -m pytest src/tests/ -q

# FastAPI 後端
python -m pytest frontend/backend/tests/ -q

# 前端（vitest）
cd frontend/web && npm test -- --run
```

覆蓋率目標：**100%**（`src/openclaw/` + `frontend/backend/app/`）

## PM2 服務

| 服務 | 說明 |
|------|------|
| `ai-trader-api` | FastAPI 後端 |
| `ai-trader-web` | React Vite Dev Server（port 3000） |
| `ai-trader-watcher` | 每 3 分鐘掃盤，Shioaji 真實行情 |
| `ai-trader-agents` | 5 個 Gemini agent 角色排程 |
| `ai-trader-ops-summary` | 每 15 分鐘輸出運維健康快照至 `data/ops/ops_summary/` |
| `ai-trader-reconciliation` | 每交易日 16:45 執行 broker/local reconciliation，輸出至 `data/ops/reconciliation/` |
| `ai-trader-incident-hygiene` | 每交易日 16:55 清理由重複 payload 造成的 unresolved incident 噪音，輸出至 `data/ops/incident_hygiene/` |

## 版本歷史

| 版本 | 重點 |
|------|------|
| v4.6.x | PM review、LLM trace 透明化 |
| v4.7.x | ticker_watcher；orders/fills 遷移 |
| v4.8.x | Chat 浮動視窗；CI 全面修復 |
| v4.9.x | 盤後分析（/analysis）；eod_analysis agent；technical_indicators；100% 覆蓋率 |
| v4.10.x | 持倉 Drawer K 線圖；quote EOD fallback；設定頁 dirty 修正 |
| v4.11.x | EOD 信號重構（signal_generator）；Trailing Stop；T+2 追蹤；實際費率；全自動策略審查；Telegram 通知 |
