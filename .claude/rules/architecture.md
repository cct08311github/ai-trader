# 核心引擎關鍵檔案

| 檔案 | 功能 |
|------|------|
| `decision_pipeline_v4.py` | 主決策管線 |
| `risk_engine.py` | 風控計算（7 層） |
| `ticker_watcher.py` | 每 3 分鐘掃盤 + 自動選股 |
| `signal_generator.py` | EOD 信號（MA + RSI + Trailing Stop） |
| `signal_aggregator.py` | Regime-based 動態權重融合 |
| `trading_engine.py` | 持倉狀態機 + 時間止損 |
| `concentration_guard.py` | 集中度守衛（>60% 自動減倉） |
| `proposal_executor.py` | SellIntent 執行 |
| `proposal_reviewer.py` | Gemini 審查 + Telegram |
| `agents/strategy_committee.py` | Bull/Bear/Arbiter 辯論 + 12h 去重 |
| `agent_orchestrator.py` | Agent 排程 Orchestrator |
| `eod_ingest.py` | 盤後 OHLCV + 法人籌碼 |
| `strategy_optimizer.py` | 自主優化三層架構 |
