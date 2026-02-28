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
