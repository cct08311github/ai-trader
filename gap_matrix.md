# Gap Matrix (v4 #1~#29)

本文件將 v4 需求逐條對照目前代碼狀態，並給出 gap、風險等級、目標模組、重構動作與驗收/測試對應。



欄位定義：

- current_state：目前已落地的實作狀態

- gap：尚未完成或需要補強之處

- risk_level：對實盤/系統風險的影響程度

- target_modules：涉及的檔案/模組

- refactor_action：建議的修正/新增方向

- acceptance_criteria：可驗收的完成條件

- test_case_id：對應測試用例（無則標 N/A）



| v4_id | requirement | current_state | gap | risk_level | target_modules | refactor_action | acceptance_criteria | test_case_id |
|---:|---|---|---|---|---|---|---|---|
| #1 | PM 否決延遲矛盾；即時阻斷歸還 Sentinel、PM 改事後稽核 | 已實作 | 無 | 高 | sentinel.py, risk_engine.py, decision_pipeline.py | 維護 | `sentinel_pre_trade_check()` 對 trading_locked/broker_disconnected/db_latency/drawdown/budget_halt 皆回傳 `hard_blocked=True` | tests/test_v4_01_sentinel.py::TestSentinelPreTradeCheck::test_trading_locked_hard_block |
| #2 | 月預算嚴重低估；token 消耗模擬 + 配額監控 + 自動降頻 | 已實作 | 無 | 高 | token_budget.py, sentinel.py | 維護 | `evaluate_budget()` 在 used_pct>=100 回傳 status=`halt`；status=`warn` 不觸發硬阻斷 | tests/test_v4_02_token_budget_fixed.py::test_evaluate_budget |
| #3 | 熱部署無緩衝期；Shadow Mode 10%→30%→100% + 自動回滾 | 已實作 | 無 | 高 | shadow_mode.py, decision_pipeline.py | 維護 | ShadowMode 在 phase transition 後路由比例正確；回滾條件可觸發 | tests/test_v4_03_shadow_mode.py::test_shadow_mode_phase_transition |
| #4 | 缺少 LLM 可觀測性；llm_traces 推理鏈追蹤 + 低置信度降倉 | 已實作 | 無 | 高 | llm_observability.py, risk_engine.py | 維護 | llm_trace 可寫入 SQLite 並符合 v4 schema；trace completeness 檢查通過 | tests/test_v4_04_llm_traces_fixed.py::test_trace_completeness |
| #5 | 缺少倉位規模公式；固定比例風險模型（帳戶淨值 × 1–2%） | 已實作 | 無 | 高 | position_sizing.py, authority.py | 維護 | `atr_position_sizing_with_level_caps` 依 level caps 限制下單 qty；level0 阻擋 | tests/test_v4_05_position_sizing.py::test_atr_position_sizing_with_level_caps |
| #6 | 無重啟恢復機制；持倉快照每 5 分鐘 + 開機自檢 + /RESUME | 未實作 | 缺少「持倉快照」資料結構/表、開機自檢流程、/RESUME 協議與 CLI/API 入口 | 中 | main.py, system_switch.py | 新增 `resume_protocol.py` + `position_snapshot` 表；啟動時自檢並提供 /RESUME 執行恢復流程 | 重啟後可從 DB 還原最後快照並產生 `SystemState`；/RESUME 觸發恢復且回傳成功 | N/A |
| #7 | SQLite 鎖定風險；WAL 模式 + ticks.db / trades.db 分庫 | 部分實作 | 目前僅有 execution tables 建表腳本/測試，缺少：WAL 強制、分庫路徑管理、連線池/重試策略與 openclaw runtime 整合 | 中 | memory_store.py, risk_engine.py | 增加 `db_router.py`（或在 store 層）統一建立連線：預設 WAL + busy_timeout；依用途分到 ticks/trades DB | 任何寫入路徑使用的 sqlite connection 皆設定 `PRAGMA journal_mode=WAL` 且分庫路徑可配置 | tests/test_v4_07_execution_tables.py::test_execution_orders_table |
| #8 | 雙源驗證時效性低；新聞 + 30 秒量能放大 3 倍交叉驗證 | 已實作 | 無 | 中 | news_guard.py | 維護 | `cross_verify_news()` 在有多來源證據時通過；缺 URL 時拒絕 | tests/test_v4_08_news_guard.py::test_cross_verify_news_passes_with_brave_and_twitter_evidence |
| #9 | 缺少多空辯論機制；Devil's Advocate + 三欄位因果日誌 | 已實作 | 無 | 中 | pm_debate.py | 維護 | PM debate prompt 含 required fields（pro/contra/causal log） | tests/test_v4_09_pm_debate.py::test_pm_debate_prompt_contains_required_fields |
| #10 | 提示詞注入風險；角色隔離標記 + 過濾層 + JSON 輸出限制 | 已實作 | 無 | 中 | prompt_security.py, decision_pipeline_v4.py | 維護 | `sanitize_external_text()` 能攔截 jailbreak/惡意指令；tool whitelist 生效 | tests/test_v4_10_prompt_security_fixed.py::test_enforce_tool_whitelist |
| #11 | 缺少累計回撤閾值；月回撤 15% 暫停 + 連虧 5 日降倉 | 部分實作 | 回撤 guard 邏輯已在 `drawdown_guard.py`，但缺少：完整測試覆蓋、與 pipeline 的持久化/告警整合驗證 | 中 | drawdown_guard.py, sentinel.py, risk_engine.py | 補齊 `test_v4_11_drawdown_guard.py`；在 decision pipeline 每日更新 drawdown 並觸發 Sentinel hard block | drawdown>=0.15 回傳 suspended；streak>=5 回傳 reduce_only；並能寫入 incidents/trading_locks（若表存在） | N/A |
| #12 | API 金鑰安全管理；Keychain + IP 白名單 + 季度輪換 | 已實作 | 無 | 低 | secrets.py, network_allowlist.py | 維護 | `get_secret()` 優先 env，其次 dotenv/keychain；IP whitelist 能擋下未授權 | tests/test_v4_12_security.py::test_enforce_network_security_raises_when_denied |
| #13 | 無模型版本鎖定；每日冒煙測試 + 失敗進入人工確認模式 | 已實作 | 無 | 低 | model_registry.py, decision_pipeline.py | 維護 | 未授權 model 會被 pipeline 阻擋；resolve model 版本可預期 | tests/test_model_registry.py::test_pipeline_blocks_unauthorized_model |
| #14 | 回測前視偏差；訓練/驗證集分離 + 市場環境分類器 | 已實作 | 無 | 低 | market_regime.py, risk_engine.py | 維護 | market regime 可分類 bull/bear/range；risk adjustments 能寫入 metadata 並縮放 qty | tests/test_v4_14_market_regime.py::test_market_regime_classify_bull_bear_range |
| #15 | 法規合規確認；實盤前向永豐金確認程式交易規範 | 未實作 | 缺少合規檢核清單/證據留存（文件/簽核/審計紀錄）流程；屬治理流程非純程式碼 | 低 | authority.py | 建立 `compliance_checklist.md` + DB/檔案審計紀錄欄位（可選）；將「未完成合規」設為 Level 限制條件 | 合規未完成時 authority level 不得提升至允許實盤；審計紀錄可追溯 | N/A |
| #16 | 未定義邊際優勢（Edge）；策略規格書第一頁寫明 Edge + 每月驗證 | 已實作 | 無 | 高 | edge_metrics.py, strategy_registry.py | 維護 | `compute_edge_metrics()` 產出 edge score 且範圍受限；可持久化到 strategy_version | tests/test_v4_16_edge_metrics.py::test_compute_edge_metrics_basic |
| #17 | 缺少盤中時段差異化；三時段門檻：開盤×2 / 標準 / 收倉模式 | 已實作 | 無 | 高 | tw_session_rules.py, risk_engine.py | 維護 | `get_tw_trading_phase_boundaries()` 取得三時段；preopen 調整風險參數生效 | tests/test_v4_17_tw_session_rules.py::test_get_tw_trading_phase_boundaries |
| #18 | 未整合三大法人籌碼；籌碼健康度評分（-10~+10）+ 每日自動匯入 | 已實作 | 無 | 高 | institution_ingest.py | 維護 | 籌碼分數方向/一致性正確；SQLite upsert roundtrip 正常 | tests/test_v4_18_institution_ingest.py::test_parse_and_upsert_institution_flows_sqlite_roundtrip |
| #19 | 缺少 VWAP / 分批進場；三階段建倉 + 盤口厚度檢查 | 已實作 | 無 | 中 | order_slicing.py | 維護 | depth check 能判定可下單；TWAP/VWAP slices 數量與總量正確 | tests/test_v4_19_order_slicing.py::test_plan_vwap_slices_allocates_by_profile |
| #20 | 缺少主動空手機制；市場評級 A/B/C + 低勝率環境觀察模式 | 已實作 | 無 | 中 | cash_mode.py, market_regime.py | 維護 | bear regime 進入 cash_mode；hysteresis 退出條件正確 | tests/test_v4_20_cash_mode.py::test_cash_mode_enters_on_bear_regime |
| #21 | 止盈策略完全缺失；四類止盈類型 + 三位一體交易規格強制 | 已實作 | 無 | 中 | take_profit.py | 維護 | partial + trailing stop 可觸發；time decay exit 能在條件達成時退出 | tests/test_v4_21_take_profit.py::test_target_price_partial_then_trailing_stop_exit |
| #22 | 缺少持倉相關性管理；同板塊上限 40% + 有效部位數計算 | 已實作 | 無 | 中 | correlation_guard.py, risk_engine.py | 維護 | correlation matrix 計算正確；breach pair 能被檢出並縮放 limits | tests/test_v4_22_correlation_guard.py::test_evaluate_correlation_risk_breach_pair |
| #23 | 未考慮季節性效應；交易日曆 + 財報季 / 除息季自動降倉 | 已實作 | 無 | 低 | trading_calendar.py | 維護 | 季底/window dressing 規則生效；節慶事件可寫入 DB 並讀回 | tests/test_v4_23_trading_calendar.py::test_trading_calendar_rules_quarter_end_and_window_dressing |
| #24 | 缺少分層記憶系統；三層 SQLite 記憶表 + 情節記憶衰減機制 | 已實作 | 無 | 高 | memory_store.py | 維護 | working/episodic/semantic 操作正常；episodic decay 與 hygiene 任務通過 | tests/test_v4_24_layered_memory.py::test_run_memory_hygiene |
| #25 | 反思機制過於淺層；診斷→歸納→修正三段式反思循環 | 已實作 | 無 | 高 | reflection_loop.py, proposal_engine.py | 維護 | reflection output 結構含三段；daily reflection integration 可跑通 | tests/test_v4_25_reflection.py::test_run_daily_reflection_integration |
| #26 | 策略提案格式不結構化；Strategy Proposal JSON Schema + 版本追蹤 | 已實作 | 無 | 高 | proposal_engine.py, authority.py, strategy_registry.py | 維護 | proposal 可 create/approve/reject；Level3 forbidden categories 會被擋 | tests/test_v4_26_proposal_system.py::test_approve_proposal |
| #27 | 缺少 LLM+RL 混合架構；PM 定方向，Trader-RL 優化執行參數 | 已實作 | 無 | 中 | decision_pipeline_v4.py, proposal_engine.py, reflection_loop.py | 維護 | hybrid coordinator 能整合（建 proposal/version/reflection）；authority 太低會阻擋 | tests/test_v4_27_llm_rl_hybrid.py::test_hybrid_coordinator_integration_creates_proposal_version_and_reflection |
| #28 | 缺少策略版本控制；strategy_versions 表 + 自動回滾機制 | 已實作 | 無 | 中 | strategy_registry.py | 維護 | create/activate/rollback/history/report 皆可運作；不存在版本會回報錯誤 | tests/test_v4_28_strategy_version.py::test_rollback_to_version |
| #29 | 未定義自主授權邊界；Level 0–3 授權框架 + Level 3 永久禁區 | 已實作 | 無 | 低 | authority.py, proposal_engine.py | 維護 | authority level enum/審計 log 正常；Level3 forbidden categories 被阻擋 | tests/test_v4_29_authority_boundary.py::test_check_proposal_authorization |
