---
globs: ["frontend/web/**"]
---

# 前端結構（Vite + React 18 + Tailwind CSS）

## 頁面
| 頁面 | 路徑 | 說明 |
|------|------|------|
| Dashboard | `/` | 總覽 |
| Portfolio | `/portfolio` | 持倉、KPI、損益曲線 |
| Inventory | `/inventory` | 庫存總覽 |
| Strategy | `/strategy` | 提案、LLM trace、duplicate suppression feed |
| Trades | `/trades` | 訂單 / 成交紀錄 |
| System | `/system` | 主開關、設定 |
| Analysis | `/analysis` | 盤後分析（3 Tab：市場概覽/個股技術/AI 策略） |

## 版本號
- `frontend/web/package.json` → `"version"` → Vite 注入 `__APP_VERSION__` → `System.jsx`
- 版本更新只改 `package.json`

## UI 約束
- `FloatingLogout`：`fixed bottom:24px right:24px z-index:99999`（不可覆蓋）
- `ChatButton`：`fixed bottom-6 right-20`（偏移 80px，避免 FloatingLogout 遮蓋）
- Chat 視窗：`360×480px` 浮動，不用 backdrop

## PositionDetailDrawer
- **QuotePanel**：開盤 → Shioaji SSE 五檔；休市 → `eod_prices` 最後收盤（標籤「最後收盤資料 YYYY-MM-DD」）
- **KlineChart**：純 SVG，查 `/api/portfolio/kline/{symbol}`，60 日日線蠟燭 + 成交量
- 持倉摘要、決策鏈、止損/止盈、籌碼趨勢
