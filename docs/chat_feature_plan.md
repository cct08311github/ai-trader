# 盤中 AI 對話功能 — 設計與實作計劃

**文件版本**：v1.0
**建立日期**：2026-03-02
**優先級**：P2（盤後功能完整後實施）

---

## 一、目標

在盤中提供一個可與 AI 即時對話的介面，讓使用者可以：
- 詢問特定股票是否值得買賣
- 討論投資組合配置與風險
- 請 AI 分析當前策略執行狀況
- 將對話結果轉換為「策略提案」，走既有審核流程後才下單

---

## 二、設計原則

| 原則 | 說明 |
|------|------|
| **不直接下單** | Chat 僅為決策輔助，下單必須經由 `Strategy Proposals → 人工審核 → risk_engine` |
| **上下文感知** | AI 自動取得當前持倉、最新訊號、近期損益，無需用戶手動貼資料 |
| **串流輸出** | 使用 SSE 逐字顯示，與現有 LogTerminal 架構一致 |
| **可稽核** | 對話紀錄寫入 `llm_traces`（agent='chat'），與其他 LLM 呼叫統一管理 |
| **費用可控** | 每次呼叫限制上下文長度；月度費用計入 `monthly_api_budget_twd` |

---

## 三、系統架構

```
Frontend                     Backend                        External
─────────────────────────────────────────────────────────────────────
ChatPanel.jsx (浮動面板)
├── 輸入框 + 送出
│                            POST /api/chat/message
│                            ├── build_chat_context()         Claude
│                            │   ├── positions (DB)       ──► Sonnet 4.6
│                            │   ├── decisions 24h (DB)       (stream)
│                            │   ├── fills 50筆 (DB)     ◄──  SSE chunks
│                            │   └── watcher traces (DB)
│   ◄── SSE streaming ───── └── StreamingResponse
│
├── [生成提案] 按鈕
│                            POST /api/chat/create-proposal
│                            └── 寫入 proposals table → Strategy 頁審核
│
└── 歷史記錄
                             GET /api/chat/history
                             └── llm_traces WHERE agent='chat'
```

---

## 四、上下文組裝規格

每次呼叫 LLM 的系統提示包含以下動態資料：

```
[系統角色]
你是 OpenClaw AI 交易助手。以下是目前帳戶狀態（僅供參考，不構成交易指令）。

[持倉摘要]
- 2330 台積電：151 股，均價 898.6，未實現損益 +X%
- 3008 大立光：591 股，均價 379.6，未實現損益 -X%
...

[今日損益]
已實現：+0 | 未實現：-XXXX

[最近 watcher 訊號 (最新3筆)]
- 2330: signal=flat, close=899, ref=900 (10:26 TWN)
- 2886: signal=flat, close=37.8, ref=38 (10:29 TWN)

[風控狀態]
gross_exposure: 26.6% | daily_loss_limit: 5000 TWD | 今日已虧損: 0

[使用者問題]
{user_message}
```

**上下文 Token 預算**：約 1500 input tokens/次，回應上限 1000 tokens

---

## 五、`@股票代碼` 語法

輸入框支援 `@2330` 觸發該股票的詳細查詢，自動附加：
- 最近 5 筆 watcher 訊號
- 目前持倉（如有）
- 近期成交記錄

---

## 六、提案生成流程

AI 回應中若包含明確買賣建議，前端顯示「生成策略提案」按鈕：

```
用戶：「2330 跌了0.3% 要加碼嗎？」
AI：「根據目前持倉比例（6.8%）和 gross_exposure（26.6%），
     在 max_symbol_weight=20% 限制下還有空間加碼約 270 股。
     建議以 897 掛限價買入。」

[按鈕: 生成提案 → buy 2330 270股 @897]
     ↓
POST /api/strategy/proposals   ← 建立 pending 提案
     ↓
Strategy 頁顯示，等待人工 Approve
     ↓
risk_engine 風控審核 → 下單
```

---

## 七、後端實作細節

### 7.1 新增路由 `frontend/backend/app/api/chat.py`

```python
GET  /api/chat/history              # 最近 50 條對話（llm_traces agent='chat'）
POST /api/chat/message              # 送訊息，回傳 SSE 串流
POST /api/chat/create-proposal      # 從對話內容建立策略提案
```

### 7.2 新增輔助模組 `frontend/backend/app/services/chat_context.py`

- `build_chat_context(db_conn) -> str`：組裝系統提示
- `parse_proposal_intent(ai_response) -> Optional[ProposalIntent]`：解析 AI 回應是否含提案意圖

### 7.3 LLM 設定

- **模型**：`claude-sonnet-4-6`（已是系統預設）
- **串流**：`anthropic.messages.stream()` → FastAPI `StreamingResponse`
- **SSE 格式**：`data: {"type":"chunk","text":"..."}\n\n`，與現有 `/api/stream/logs` 相容
- **Token 限制**：`max_tokens=1000`

### 7.4 對話紀錄持久化

每次對話（問＋答）寫入 `llm_traces`：
```
agent = 'chat'
model = 'claude-sonnet-4-6'
prompt = 組裝後的完整 system+user prompt
response = 完整回應文字
metadata = { "user_message": ..., "created_at_ms": ... }
```

---

## 八、前端實作細節

### 8.1 元件結構

```
src/components/chat/
├── ChatButton.jsx          浮動按鈕（右下角，所有頁面顯示）
├── ChatPanel.jsx           側滑面板（w-96，覆蓋在內容上方）
├── ChatMessage.jsx         單條訊息泡泡（支援 markdown）
├── ChatInput.jsx           輸入框（支援 @symbol 觸發）
└── ProposalChip.jsx        生成提案按鈕（AI 建議時出現）
```

### 8.2 掛載位置

在 `App.jsx` 最外層加入 `<ChatButton />`，確保所有路由頁面皆可使用。

### 8.3 SSE 串流接收

```javascript
const es = new EventSource('/api/chat/message/stream?...')
es.onmessage = (e) => {
  const { type, text } = JSON.parse(e.data)
  if (type === 'chunk') appendToLastMessage(text)
  if (type === 'done')  es.close()
}
```

### 8.4 狀態管理

對話歷史存在 React state（本地），頁面刷新後從 `/api/chat/history` 重新載入最近 20 條。

---

## 九、工作項目（待辦清單）

| # | 類別 | 工作項目 | 預估 |
|---|------|---------|------|
| T1 | 後端 | 建立 `chat_context.py`：組裝持倉/訊號/損益上下文 | 0.5天 |
| T2 | 後端 | 建立 `chat.py` router：`/history`、`/message` SSE、`/create-proposal` | 1天 |
| T3 | 後端 | 串接 Claude Sonnet 4.6 streaming，寫入 llm_traces | 0.5天 |
| T4 | 後端 | 在 `main.py` 註冊 chat router | 0.25天 |
| T5 | 前端 | `ChatMessage.jsx` + `ChatInput.jsx`（含 @symbol 解析） | 0.5天 |
| T6 | 前端 | `ChatPanel.jsx`：側滑面板 + SSE 串流打字機效果 | 0.5天 |
| T7 | 前端 | `ChatButton.jsx`：浮動按鈕 + 未讀徽章 | 0.25天 |
| T8 | 前端 | `ProposalChip.jsx`：提案生成按鈕 + 串接 Strategy API | 0.5天 |
| T9 | 前端 | 在 `App.jsx` 掛載 ChatButton | 0.25天 |
| T10 | 測試 | 上下文品質驗證：確認 AI 能正確解讀持倉與訊號 | 0.5天 |

**合計預估**：約 4.75 天

---

## 十、依賴與前置條件

- [ ] `anthropic` Python package 已安裝（`pip install anthropic`）
- [ ] `ANTHROPIC_API_KEY` 環境變數已設定（`run.sh` 或 `.env`）
- [ ] `llm_traces` 表已存在（已確認，v4 schema）
- [ ] Strategy Proposals 表已存在（已確認）

---

## 十一、未來擴充（不在本次範圍）

- **語音輸入**：Web Speech API → 轉文字送出
- **多輪記憶**：將前 N 輪對話納入 context window（目前每次獨立呼叫）
- **主動推播**：watcher 偵測到異常訊號時主動推送通知（SSE push to chat）
- **回測問答**：「過去30天這個策略表現如何？」接 backtest engine

---

*本文件由 Claude Code 生成，請在實作前確認架構決策仍符合當前系統狀態。*
