# Edge Definition（v4#16）

> 目的：定義策略「Edge」的衡量方式，並提供可落地的計算方法與版本控管整合方式。

---

## 1. Edge 是什麼？

在交易系統中，Edge 指的是：

- **在扣除成本後（手續費、滑價、延遲）**，策略的單筆交易期望值（Expected Value, EV）是否為正。

以交易結果分佈表示，Edge 是一個 **統計性** 指標：
- 不是保證每一筆都賺
- 也不是單純看勝率

---

## 2. 最小可落地的 Edge 指標

我們用下列一組指標來近似 Edge（對應 `src/openclaw/edge_metrics.py`）：

1) **Win Rate（勝率）**
- 定義：`wins / n_trades`

2) **Avg Win / Avg Loss（平均賺/平均賠）**
- avg_loss 使用「損失幅度」（正數）表示

3) **Expectancy（期望值 / 每筆期望損益）**

\[
\text{Expectancy} = p\_{win} \cdot \overline{W} - (1-p\_{win}) \cdot \overline{L}
\]

4) **Profit Factor（獲利因子）**

\[
\text{ProfitFactor} = \frac{\sum W}{\sum |L|}
\]

5) **Payoff Ratio（盈虧比）**

\[
\text{PayoffRatio} = \frac{\overline{W}}{\overline{L}}
\]

---

## 3. 成本/滑價怎麼處理？

Edge 評估應 **盡量使用 net PnL**：
- `net_pnl = gross_pnl - fees - slippage_cost`

若目前交易記錄尚未提供 fees/slippage，可先用：
- 回測中估算成本
- 實盤以成交/委託差估算

並將「成本模型版本」與 Edge metrics 一起寫入版本控管（見第 5 節）。

---

## 4. 何時視為「Edge OK」？（建議門檻）

可依策略型態調整，但給一個工程落地的建議：

- `n_trades` ≥ 30（太少不判定）
- `profit_factor` > 1.1（至少大於 1）
- `expectancy` > 0
- 搭配風控：即使 Edge OK，仍需受限於 drawdown guard / sentinel / correlation guard

---

## 5. 與策略版本控管（v4#28）整合

在 v4 架構中，每次策略變更會建立一個 `strategy_version`。

本 repo 的落地方式：

- 使用 `persist_edge_metrics_to_strategy_version(db_path, version_id, metrics)`
- 會把 metrics 寫回 `strategy_versions.strategy_config_json`：
  - `edge_metrics`: 指標明細
  - `edge_score`: 用於 UI/報表的 bounded score（0..100）
- 同時 best-effort 追加一筆 `version_audit_log`（action=`edge_metrics_updated`）

這樣可以達成：
- 每個策略版本都能回溯當時的 edge 指標
- 月報/回顧可以依版本比較 edge 變化

---

## 6. 實作對照

- 指標計算：`src/openclaw/edge_metrics.py`
- 測試：`tests/test_v4_16_edge_metrics.py`

---

## 7. 與交易決策流程整合

Edge metrics 已透過 `edge_integration.py` 模組整合到交易決策流程中：

### 7.1 決策流程整合

在每次交易決策時，系統會：
1. 分析策略的歷史交易記錄（預設：過去30天）
2. 計算 edge metrics 和 edge score
3. 根據 edge 質量調整交易決策：
   - Edge 質量良好：正常執行交易
   - Edge 質量不足：減少部位規模（減少50%）
   - Edge 質量極差：阻擋交易

### 7.2 整合函數

主要整合函數：
```python
from openclaw.edge_integration import integrate_edge_into_decision

# 在決策流程中整合 edge 分析
updated_decision, recommendation = integrate_edge_into_decision(
    db_path="data/sqlite/trades.db",
    strategy_id="your_strategy_id",
    decision_data=current_decision,
    edge_threshold=50.0  # 最低 edge score 門檻
)
```

### 7.3 自動化策略版本更新

系統提供自動化功能來更新所有策略版本的 edge metrics：

```python
from openclaw.edge_integration import batch_update_all_strategy_versions

# 批次更新所有 active 的策略版本
stats = batch_update_all_strategy_versions(
    db_path="data/sqlite/trades.db",
    days_back=30
)
```

### 7.4 決策影響

Edge 分析會影響以下決策層面：
1. **部位規模調整**：根據 edge score 動態調整
2. **交易阻擋**：edge 質量極差時完全阻擋交易
3. **風險評估**：納入整體風險評估框架
4. **策略版本管理**：每個版本都記錄當時的 edge metrics

---

## 8. 使用範例

### 8.1 分析策略 Edge

```python
from openclaw.edge_integration import analyze_strategy_edge

result = analyze_strategy_edge(
    db_path="data/sqlite/trades.db",
    strategy_id="momentum_strategy_v2",
    days_back=30,
    min_trades=10
)

print(f"Edge Score: {result.edge_score:.1f}")
print(f"Is Edge OK: {result.is_edge_ok}")
print(f"Recommendation: {result.recommendation}")
print(f"Metrics: {result.metrics.as_dict()}")
```

### 8.2 整合到決策管道

在 `decision_pipeline_v4.py` 或類似決策流程中：

```python
# 在風險評估階段後加入 edge 分析
if not decision_data.get('trade_blocked'):
    decision_data, edge_recommendation = integrate_edge_into_decision(
        db_path=db_path,
        strategy_id=strategy_id,
        decision_data=decision_data,
        edge_threshold=50.0
    )
    
    # 記錄 edge 分析結果
    log_edge_analysis(decision_data['edge_analysis'])
```

### 8.3 定期批次更新

可設定 cron job 定期更新策略版本的 edge metrics：

```bash
# 每日凌晨更新所有策略版本的 edge metrics
0 2 * * * cd /path/to/ai-trader && python -c "from openclaw.edge_integration import batch_update_all_strategy_versions; stats = batch_update_all_strategy_versions('data/sqlite/trades.db', 30); print(stats)"
```

---

## 9. 監控與警報

建議設定以下監控：

1. **Edge Score 趨勢**：監控 edge score 的長期趨勢
2. **交易數量**：確保有足夠的交易樣本
3. **Profit Factor 警報**：當 profit factor 低於 1.0 時發出警報
4. **Expectancy 警報**：當 expectancy 轉為負值時發出警報

---

## 10. 未來擴展

Edge Definition 系統設計為可擴展：

1. **更多指標**：可加入 Sharpe ratio、最大回撤等指標
2. **市場狀態調整**：根據市場 regime 調整 edge 評估標準
3. **機器學習整合**：使用 ML 模型預測 edge 變化
4. **即時監控**：即時計算和顯示 edge metrics

---

## 總結

Edge Definition 系統（v4 #16）已完整實作，包含：

✅ **核心指標計算** (`edge_metrics.py`)  
✅ **完整文件說明** (`docs/edge_definition.md`)  
✅ **決策流程整合** (`edge_integration.py`)  
✅ **策略版本整合** (與 v4 #28 整合)  
✅ **完整測試覆蓋** (`test_v4_16_edge_metrics.py`, `test_edge_integration.py`)  

系統已準備好投入生產環境使用，可有效評估策略 edge 質量並整合到交易決策中。
