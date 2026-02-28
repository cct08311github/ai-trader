# 法規合規檢查清單（v4#15）

> 目的：建立「可執行」的合規檢查項目，用於 AI/量化交易系統（含回測、模擬、實盤）之治理、稽核、風險控管與資料安全。
>
> 重要提醒：本文件為工程/產品落地用的 **Checklist**，不構成法律意見。實際上線前需由法遵/內控/稽核覆核。

---

## 0. 適用範圍與責任分工

- [ ] 系統適用範圍定義：回測 / paper / live（實盤）分級，哪些功能只允許在特定模式啟用。
- [ ] 角色與權限：PM/交易員/工程/法遵/稽核的權限矩陣（讀取、修改策略、切換模式、下單、停機）。
- [ ] 交易委託與責任：人機協作與最終核准人（含緊急停止權）。
- [ ] 供應商與外包：券商 API、行情源、雲服務供應商的責任邊界。

## 1. 金管會（FSC）/內控/風險管理要求（通用）

### 1.1 治理與內控
- [ ] 重大系統變更（策略、風控參數、下單邏輯）有變更單、審核、回溯紀錄。
- [ ] 風險控管機制具備「三道防線」概念：
  - (1) 事前：風控限額、白名單、權限
  - (2) 事中：即時監控、熔斷
  - (3) 事後：稽核、報表、追溯
- [ ] 人工覆核流程：高風險操作（切換實盤、提高限額、關閉風控）必須多因子或雙人覆核。

### 1.2 模型風險/自動化決策（Model Risk）
- [ ] 模型/策略輸出可解釋：保留決策理由、特徵摘要、信心度。
- [ ] 設定「降級模式」：LLM 不可用、行情延遲、DB 延遲時自動降級（例如 reduce-only / trading_locked）。
- [ ] 反操縱與輸入安全：外部新聞/文字輸入要做 prompt injection 防護與 allowlist（見 `news_guard`/`prompt_security`）。

### 1.3 稽核軌跡與紀錄保存
- [ ] 所有交易決策（含被拒絕）要可追溯：decision_id、參數快照、風控原因碼。
- [ ] LLM 調用留存：prompt / response / tokens / latency（不得包含機敏個資）。
- [ ] 日誌保存與防竄改：Write-once 或至少具備 hash/簽章（可先從 DB audit table 開始）。

## 2. 證交所/櫃買中心（交易秩序/公平性）— 通用檢核

- [ ] 下單頻率/撤單率控制：有 rate-limit、冷卻時間、異常偵測。
- [ ] 防止異常價格委託：偏離 mid/last 超過閾值即拒絕（如 `max_price_deviation_pct`）。
- [ ] 防止異常滑價：估計滑價超過 bps 閾值即拒絕（如 `max_slippage_bps`）。
- [ ] 防止單一標的過度集中：max_symbol_weight、max_gross_exposure 限制。
- [ ] 避免市場操縱型行為：不得透過策略形成虛假交易量、拉抬/打壓價格（需人工覆核策略目的與行為特徵）。

## 3. 券商規範/券商 API 合約（Trading API Compliance）

- [ ] API Key/Token 管理：
  - 密鑰不落盤（或至少加密/使用 secret manager）
  - 權限最小化（只允許必要交易權限）
- [ ] 下單/成交回報一致性：對帳流程（成交回報 vs 內部紀錄）每日校驗。
- [ ] 錯單/重複下單防護：idempotency key、重送策略、重試退避。
- [ ] 斷線處理：broker disconnected 時禁止新倉；恢復後需重新同步持倉與委託。

## 4. 資料保護與隱私（個資/機敏資料）

- [ ] 資料分類分級：個資、交易紀錄、策略參數、金鑰等分級與處理規範。
- [ ] 最小化收集：不必要的個資不進系統；LLM prompt 不夾帶個資。
- [ ] 存取控管：DB/日誌/備份皆需權限控管與審計。
- [ ] 備份/留存/刪除政策：保留期限、刪除流程與稽核。

## 5. 資安要求（系統安全）

- [ ] 網路出站 allowlist（如 `network_allowlist`），避免任意外連。
- [ ] 供應鏈安全：依賴套件鎖版（requirements/lockfile），SCA 掃描（可列入 CI）。
- [ ] 憑證/金鑰輪替：定期輪替，異常即撤銷。
- [ ] 權限與審計：操作記錄、告警通知、異常封鎖。

## 6. 風控必備清單（對應本 repo v4 架構）

- [ ] Sentinel（硬熔斷）：交易鎖、資料延遲、DB 延遲、預算 breaker。
- [ ] Drawdown Guard：超限轉入 suspended / reduce-only。
- [ ] Market Regime 調整：熊市/盤整時降低風險倍數（`market_regime.py`）。
- [ ] 主動空手機制：市場評級過低 → reduce-only（`cash_mode.py`）。
- [ ] 持倉相關性：高相關曝險 → 降低 gross/symbol limits（`correlation_guard.py`）。

## 7. 上線前 Gate（Go/No-Go）

- [ ] 回測與驗證：
  - 回測資料來源與完整性
  - out-of-sample / walk-forward
  - 交易成本、滑價、延遲模型
- [ ] 模擬與演練：
  - Paper trading ≥ N 週
  - 斷線/行情異常/DB 延遲/券商拒單演練
- [ ] 稽核與簽核：法遵/內控/稽核簽核紀錄完整

---

## 附錄：建議的「合規稽核輸出」欄位

- decision_id / ts / symbol / strategy_id
- mode: backtest|paper|live
- authority_level / approved_by
- market_regime / rating / cash_mode
- risk_checks: sentinel / drawdown / correlation / liquidity
- order_candidate snapshot
- reason_code（拒絕/允許）
