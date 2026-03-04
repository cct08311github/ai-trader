# 智能 AI 交易系統設計方案
**日期**：2026-03-04
**版本**：v2.0（已整合 Opus 第三方評審）
**狀態**：已核准，進入實作計劃

---

## 一、現況診斷

### 系統已具備
- `ticker_watcher.py`：每 3 分鐘掃盤，輸出 buy/flat 信號
- `risk_engine.py`：計算止損/止盈價格
- `decision_pipeline_v4.py`：主決策管線
- `strategy_committee` agent：Bull/Bear/Arbiter 三方辯論
- `portfolio_review` agent：持倉分析
- `eod_ingest.py`：每日 OHLCV 寫入 `eod_prices` 表（已有但 watcher **未使用**）
- `technical_indicators.py`：技術指標純函數（缺 ATR）
- FastAPI + React 前端：即時監控

### 核心缺口（P0~P2）

| 優先級 | 問題 | 後果 |
|--------|------|------|
| P0 | **無 Sell 決策**：watcher 只輸出 buy/flat | 利潤永遠無法實現 |
| P0 | **止損止盈無觸發**：risk_engine 計算了但無執行鏈 | 設了等於沒設 |
| P0 | **跌停板下止損被風控攔截**（Opus 新增）| 最需止損時反而被擋掉 |
| P0 | **Trailing Stop 缺失**（Opus 新增）| 3008 +545% 無鎖利機制 |
| P0.5 | **ATR 欄位永遠 None**（Opus 新增）| position_sizing ATR 路徑從未觸發 |
| P0.5 | **EOD 日線數據棄置不用**（Opus 新增）| watcher 只用 3 分鐘記憶體 close |
| P1 | **strategy_proposals 執行鏈斷開** | 策略建議石沉大海 |
| P1 | **集中度風險失控**：3008 佔組合 70% | 單點爆倉風險 |
| P1 | **T+2 交割資金未追蹤**（Opus 新增）| 切實盤會出現違約交割風險 |
| P1 | **交易成本未計入**（Opus 新增）| 績效數字全被高估（0.3% 證交稅 + 手續費） |
| P2 | **portfolio_review 用舊數據** | 分析結論失準 |
| P2 | **策略委員會固定信心分 0.65** | 提案同質化 |

### 今日數據快照（2026-03-04）
- 持倉 10 檔，總未實現獲利 **+$1,448,399**
- 3008 單檔 +545%，佔組合市值 **70%**（定時炸彈）
- 今日 buy 信號：2 筆；sell 信號：**0 筆**
- 策略提案：4 份均「保守減碼」，均未執行

---

## 二、目標定義

### 「真正的智能 AI 交易系統」

1. **閉環執行**：買入 → 持倉追蹤 → 條件觸發 → 賣出（止損/止盈/Trailing/獲利了結） → 績效回饋 → 策略調整
2. **自主優化**：系統根據歷史績效自動調整閾值（需足夠樣本 + 人工審核重大調整）
3. **多信號融合（Regime-based）**：技術指標 + LLM 辯論（快取） + 籌碼面 + 風控（一票否決）→ 動態權重評分
4. **PM 水準操盤**：分批出場、Trailing Stop、集中度控制、T+2 資金管理
5. **真實數據驅動**：技術指標改由 `eod_prices` 日線驅動，廢棄 mock 隨機漫步用於策略決策

---

## 三、採用方案：C（漸進式）+ Sprint 0.5 緊急止血

**Opus 評審推薦理由**：方案 A 技術債太重（ticker_watcher 已 716 行），方案 B 重構期間 live system 盲飛風險過高。方案 C 採用 **Strangler Fig Pattern**，新模組並行存在、逐步取代，每步可快速回滾。

---

## 四、Sprint 規劃

### Sprint 0.5（2-3 天）— 緊急止血

**目標**：最危急的風險立刻消除，不動架構。

1. **Trailing Stop 上線**
   - `ticker_watcher._generate_signal` 加入 trailing stop 邏輯
   - 追蹤 `highest_price_since_entry`（寫入 `positions` 表新欄位）
   - Trailing stop = `highest_price × (1 - trailing_pct)`，`trailing_pct` 隨獲利幅度遞減
   - 觸發即輸出 sell 信號（score=-1.0）

2. **止損單跳過風控 slippage 檢查**
   - `risk_engine.evaluate_and_build_order`：平倉 sell 單（`opens_new_position=False`）跳過 `RISK_SLIPPAGE_ESTIMATE_LIMIT` 和 `RISK_PRICE_DEVIATION_LIMIT`
   - 解決跌停板無法止損的致命問題

3. **分批出場基礎**
   - sell 信號支援 `partial_qty`（預設：trailing stop 觸發先出 50%）

---

### Sprint 1（1 週）— 模組拆分 + 執行鏈

**目標**：閉環跑通，signal/execute 職責分離。

1. **抽出 `signal_generator.py`**（Strangler Fig）
   - `_generate_signal` 邏輯遷移至獨立模組
   - 輸入：持倉、EOD 日線數據、技術指標結果
   - 輸出：`Signal(symbol, action, score, reason)`
   - ticker_watcher 改調用此模組

2. **抽出 `order_executor.py`**
   - `_execute_sim_order` / `_execute_live_order` 遷移
   - 支援：market order、limit order、partial qty
   - 計入交易成本（手續費 + 稅）

3. **接通 strategy_proposals 執行鏈**
   - approved proposal → `order_executor.execute_proposal()`
   - 新增 `proposal_executor.py`

4. **EOD 日線驅動技術指標**
   - `signal_generator` 從 `eod_prices` 取 60 日 OHLCV
   - 廢棄 `ticker_watcher.price_history` 作為技術指標來源

5. **新增 ATR 計算至 `technical_indicators.py`**
   - ATR(14) 實作
   - `Decision.atr` 開始填入真實值

---

### Sprint 2（1-2 週）— TradingEngine + 信號融合

**目標**：持倉生命週期統一管理，多信號動態融合。

1. **`trading_engine.py`（持倉狀態機）**
   ```
   CANDIDATE → ENTRY → HOLDING → EXITING → CLOSED
   ```
   - 每個持倉有明確狀態，轉換有 audit log
   - 追蹤持倉天數（支援時間止損）

2. **`signal_aggregator.py`（Regime-based 動態權重）**
   - 呼叫現有 `market_regime.classify_market_regime`
   - Regime → Weight mapping：
     ```
     Bull:    技術 50% + LLM 20% + 籌碼 20% + 風控 10%
     Bear:    技術 20% + LLM 20% + 籌碼 20% + 風控 40%
     Sideways:技術 30% + LLM 30% + 籌碼 30% + 風控 10%
     Crisis:  技術 10% + LLM 10% + 籌碼 10% + 風控 70%
     ```
   - 風控改為「第一層門檻（一票否決）」，不參與加權

3. **LLM 信號快取**
   - strategy_committee 結果寫入 `lm_signal_cache` 表，有效期 1 小時
   - signal_aggregator 讀快取，不即時呼叫 LLM

4. **集中度自動再平衡**
   - 每輪掃盤後計算各檔佔比
   - 超過 40% 自動生成減倉 proposal（需人工 approve）
   - 超過 60% 自動觸發部分減倉（不需 approve）

5. **T+2 交割資金追蹤**
   - `PortfolioState` 區分 `available_cash` 與 `pending_settlement`
   - `orders` 表新增 `settlement_date` 欄位

---

### Sprint 3（1 週）— 績效追蹤 + 優化閉環

**目標**：系統能自我評估、提出優化建議。

1. **`performance_tracker.py`**
   - 實時計算：勝率、損益比、夏普比率、最大回撤、持倉天數
   - Benchmark 對比：vs 加權指數（TWSE）/ 0050 ETF
   - 每日績效快照寫入 DB

2. **`strategy_optimizer.py`**（人工審核模式）
   - 至少 **30 筆**交易才觸發閾值評估（Opus：10 筆統計無意義）
   - 閾值調整分兩類：
     - 「安全調整」（如止損微調 ±1%）：自動生效 + audit trail
     - 「重大調整」（策略權重、入場門檻）：生成 proposal，需人工 approve
   - 加入衰減機制：每週向預設值回歸 10%（防止閾值單向漂移）

3. **A/B 策略對比框架**
   - 同時跑兩組參數，用小比例資金分別驗證

4. **Shioaji 斷線重連**
   - 連線狀態監控，斷線自動重連，超過 3 次失敗則觸發告警

---

## 五、技術指標數據需求

| 指標 | 最少數據量 | 數據來源 | 現況 |
|------|-----------|---------|------|
| MA(5/10/20/60) | 60 日 OHLCV | `eod_prices` | 有資料，未用 |
| RSI(14) | 15 日 close | `eod_prices` | 有資料，未用 |
| MACD(12,26,9) | 35 日 close | `eod_prices` | 有資料，未用 |
| ATR(14) | 15 日 HLC | `eod_prices` | 缺實作 |
| 支撐壓力 | 20 日 HLC | `eod_prices` | 有資料，未用 |
| 籌碼面（法人） | T+1 公告 | institution_ingest | 待確認 |
| 成交量分析 | 20 日 volume | `eod_prices` | 有資料，未用 |

---

## 六、台股市場特殊性處理（Opus 補充）

| 特性 | 處理方式 |
|------|---------|
| 漲跌停板 | 平倉 sell 單跳過 slippage 風控；跌停時仍掛單等待撮合 |
| T+2 交割 | PortfolioState 區分可用餘額/交割中 |
| 整張限制 | `calculate_position_qty` 結果取整為 1000 的倍數（切實盤前必做） |
| 交易成本 | 賣出 0.3% 證交稅 + 買賣各 0.1425% 手續費，計入 `fills` |
| Shioaji rate limit | snapshot 改批次呼叫（一次傳入所有 contracts） |

---

## 七、切換實盤的三道驗證門檻（Opus 建議）

1. **紙上交易對帳**（≥1 個月）：simulation 成交 vs 真實成交價 diff < 0.5%
2. **Walk-forward backtest**：6 個月 out-of-sample，Sharpe ≥ 0.5
3. **小資金試水**：5% 資金切實盤 2 週，確認滑價、成交率、交易成本

---

## 八、成功標準

| 指標 | 目標 |
|------|------|
| 每筆交易有完整決策鏈 | 100% |
| 止損/止盈/Trailing 觸發率 | >95% 應觸發的都觸發 |
| 集中度超標 | 單檔 < 40%（自動控制） |
| 勝率（30 筆統計） | > 50% |
| 損益比 | > 1.5:1 |
| 最大回撤 | < 15% |
| 策略優化閉環延遲 | 每日收盤後 30 分鐘內生成優化報告 |
