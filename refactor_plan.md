# OpenClaw v4 差異驅動重構 — Refactor Plan（Phase 1/2/3）

> 依據：`gap_matrix.md`（v4 #1~#29） + `ref_doc/OpenClaw_優化審查報告_v4.docx` + `ref_doc/OpenClaw_v4_package/openclaw/`

## 0. 排程原則（為什麼這樣排）
1. **Gate 1/2/3/4 驗收導向**：先讓「可查詢、可驗證、可回滾、可測」成立，再補策略能力。
2. **deterministic 先於 LLM**：風控/授權/狀態機先做硬規則，LLM 只能當建議或產生結構化草案。
3. **資料模型先於 UI**：先把 DB schema、狀態機與 API/函式界面穩定，再做 Telegram 審核 UI。

---

## Phase 1（已完成 / 已合併）— 交易主鏈最小安全閉環
> 對應已完成項（PR #6 / #7）：#1 #2 #4 #6 #7 #10 #11

### 已完成（以 Step 1 gap_matrix + PR 為準）
- #1 Sentinel 即時阻斷責任切割
- #2 token 消耗模擬 + 配額監控
- #4 LLM 可觀測性層（llm_traces）
- #6 重啟恢復協議
- #7 SQLite 初始化（WAL + 分庫 + v4 基礎表）
- #10 Prompt injection guard
- #11 累計回撤閾值

### Phase 1 殘留風險（必須在 Phase 2/3 消化）
- Phase 1 的「已實作」多為可用骨架，需補齊 v4 Gate 2 的 db 可查詢性（execution domain tables 與關聯一致性）。

---

## Phase 2（優先）— v4 自主優化核心 + 變更治理（高風險必先做）
> **目標**：完成 v4 的「反思→提案→授權→版本」閉環，並讓其可被稽核/回滾。

### Phase 2.1 P0（必做，高風險 / Gate 1 指名 #24/#25/#26）
1. **#26 結構化策略提案系統（proposal JSON + Telegram 審核 UI）**
   - 理由：它是所有自主優化輸出的唯一入口；沒有它就沒有可控的演進。
   - 影響模組（預期）：`src/openclaw/proposal_engine.py`、Telegram handlers（若存在）、DB `strategy_proposals`。
   - 主要風險：狀態機不完整導致「未審核就套用」→ 必須由 #29 Gate。

2. **#29 自主授權邊界（Level 0/1/2/3 + Level 3 禁區）**
   - 理由：屬於 hard safety gate；避免任何 LLM/反思輸出直接影響 live。
   - 影響模組（預期）：新增 `src/openclaw/authority.py`（或併入 proposal_engine）、decision_pipeline/risk_engine hook、audit trail。

3. **#28 策略版本控制（strategy_versions + 對比 + 回滾）**
   - 理由：沒有版本控制，無法滿足 Gate 3「可回滾性」。
   - 影響模組（預期）：新增 `src/openclaw/strategy_registry.py`、DB `strategy_versions`、proposal approve 流程。

4. **#25 三段式反思機制（Diagnosis → Abstraction → Refinement）**
   - 理由：反思是提案的 upstream，需標準化輸出與門檻；但必須在 #26/#29 框住後才安全。
   - 影響模組（預期）：`src/openclaw/reflection_loop.py`、`reflection_runs`、memory（episode_type='day'）。

5. **#24 分層記憶系統（working/episodic/semantic + decay + retrieval order）**
   - 理由：支撐反思與提案的可檢索依據；同時是 Gate 2 db summary 必備。
   - 影響模組（預期）：`src/openclaw/memory_store.py` + decay job（cron/job runner）。

### Phase 2.2 P1（工程治理 / 安全）
6. **#3 Shadow Mode 熱部署（10%→30%→100% + 2h 回滾）**
   - 理由：策略版本變更不允許 big-bang；配合 #28/#29 是安全上線的必要條件。
   - 影響模組（預期）：新增 `src/openclaw/shadow_mode.py` + strategy registry。

7. **#12 API 金鑰安全儲存（macOS Keychain + IP allowlist）**
   - 理由：屬於 production safety；避免明文 secrets 與外部風險。

8. **#13 模型版本鎖定 + 每日冒煙測試**
   - 理由：LLM 變動會讓系統行為漂移；必須 pin + smoke 才能做可稽核。

### Phase 2 交付驗收（Phase-level）
- db summary 可查到：memory（3層）/ reflection_runs / strategy_proposals / strategy_versions。
- proposal 有完整狀態機：pending → approved/rejected/expired；approved 會建立新 strategy_version。
- authority gate 生效：Level <2 不得自動核准；Level 3 forbidden 永遠人工。

---

## Phase 3 — 策略與資料能力補強（交易 alpha 與資料面）
> **目標**：補齊策略能力與台股特性資料能力，並把它們接到 deterministic gate。

建議順序（以 gap_matrix 高風險項為準）：
1. **#17 台股盤中時段差異化**（先讓 risk_engine 能吃到 session rules）
2. **#18 三大法人籌碼整合（盤後匯入 + health score）**
3. **#19 分批建倉 + 盤口厚度檢查**
4. **#21 三位一體止盈策略**
5. **#22 持倉相關性管理**
6. **#20 主動空手機制 + 市場評級**
7. **#23 季節性交易日曆**

---

## 跨 Phase 共通風險與緩解
- **DB schema 演進造成破壞性變更**：一律採「先新增、再雙寫、最後切換」；並提供 rollback。
- **LLM 不確定性**：所有 LLM 輸出必須 schema validate；可疑輸出不得影響 live。
- **測試不足**：每條 v4_id 都必須能連到 `gap_matrix.md` 的 acceptance_criteria 與 test_case_id；Phase 2/3 必補整合測試（dry-run）。
