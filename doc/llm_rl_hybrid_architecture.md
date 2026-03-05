# LLM + RL 混合架構（v4 #27）

> TaskHub: `7dab1951-9b0c-496a-a077-accd237d4b4f`

## 目標
在不突破安全邊界（不得直接上線替換策略、必須走提案 + 授權 + 版本控管）的前提下，引入「LLM + RL」混合架構，用於：
- **高層策略推理**（LLM）：市場解讀、風險評估、目標函數與約束設定
- **低層執行優化**（RL）：在受限參數空間內做參數搜索與自適應優化

對外輸出必須：
1. 產生 **策略提案**（Proposal Engine #26）
2. 遵守 **授權邊界**（Authority #29）
3. 建立 **可追蹤版本**（Strategy Registry #28）
4. 將訓練結果納入 **反思迴圈**（Reflection Loop #25）

## 模組位置
- 程式碼：`src/openclaw/rl/hybrid_architecture.py`
- 匯出：`src/openclaw/rl/__init__.py`
- 測試：`tests/test_v4_27_llm_rl_hybrid.py`

## 核心元件

### 1) LLMStrategyPlanner（LLM 模組）
**責任**：產生 `StrategyPlan`
- objective：要最大化什麼（例如 reward / Sharpe / risk-adjusted return）
- constraints：風險限制（max_drawdown / max_leverage / risk_budget…）
- parameter_space：可調參數空間（離散候選集合）

> 實作上支援 `llm_callable` 注入；在 offline / unit test 預設使用**可重現的啟發式**，避免測試依賴外部模型。

### 2) RLParameterOptimizer（RL 模組）
**責任**：在 `StrategyPlan.parameter_space` 內做低層優化，輸出 `OptimizationResult`
- 預設採用 **epsilon-greedy bandit**（輕量 RL），不依賴 stable-baselines3。
- 透過 `seed` 確保可重現。
- 以 `reward_fn(params)->float` 對接離線回測/模擬環境。

> 若未來要換成 stable-baselines3：
> - planner 仍維持輸出「有限/受限的 action-space」
> - optimizer 可改用 SB3 的 PPO/SAC 等，但**仍不得直接部署**

### 3) HybridCoordinator（協同機制）
**責任**：串接 Planner + Optimizer，並與 v4 子系統整合
- (#29) Authority gate：無權限（Level 0/1）直接拒絕產生提案
- (#26) Proposal：把 current/proposed 參數與 evidence 寫入 `strategy_proposals`
- (#28) Version：基於 proposal 生成 `strategy_versions` 的 **draft**（不 activate）
- (#25) Reflection：將訓練輸出寫入 `reflection_runs`（best-effort，缺表則跳過）

## 安全限制（必須遵守）
- RLOptimizer **不能**直接呼叫 `StrategyRegistry.activate_version()`。
- 所有策略變更都必須經過 Proposal Engine 產生提案。
- Authority Level 只影響「是否可提出 / 是否可 auto_approve」，但本模組仍維持 **不自動上線**。

## 資料流（簡化）

1. `LLMStrategyPlanner.plan()` 產生 `StrategyPlan`
2. `RLParameterOptimizer.optimize()` 產生 `OptimizationResult`
3. `HybridCoordinator.run()`：
   - create_proposal (v4 #26)
   - create_version (v4 #28, draft)
   - insert_reflection_run (v4 #25, best-effort)

## 測試策略
- **可重現性**：同 seed + 同 reward_fn -> 產出一致 best_params
- **整合性**：同一個 sqlite db file 中確認
  - proposal 寫入成功
  - version 建立為 draft 且 source_proposal_id 正確
  - reflection_runs 有寫入（若表存在）
- **安全性**：低權限時拒絕提案

