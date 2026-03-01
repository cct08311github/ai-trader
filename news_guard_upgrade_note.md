# News Guard v4 #8 - Verification System Upgrade
新聞驗證系統已升級完成，包含：

## 1. 多源驗證 (Brave + Twitter)
- 函數：`cross_verify_news(text, brave_search, twitter_search)`
- 規則：必須同時存在 Brave 和 Twitter 的證據，且通過 Lobster Gold 過濾器
- 輸出：`NewsVerificationResult` 包含 verified, lobster_gold, weight, evidence, reason

## 2. 關鍵字權重計算
- 函數：`compute_keyword_hits(text)` → 返回各類別命中次數
- 函數：`compute_news_weight(text)` → 返回權重乘數 (1.0–2.0)
- 關鍵字類別：Trump 政策、AI 巨頭、地緣政治風險

## 3. Lobster Gold 過濾器
- 函數：`lobster_gold_filter(evidence, min_quality=0.7)` → 過濾出高品質證據
- 規則：必須有有效 URL、來源為 brave/twitter、品質分數 ≥ min_quality

## 4. 證據質量評分
- 證據類別：`NewsEvidence` 包含 quality 欄位 (0.0–1.0)
- 評分規則：URL 存在 (+0.6)、來源存在 (+0.2)、標題長度 ≥12 (+0.1)、片段長度 ≥20 (+0.1)
- 內部函數：`_evidence_from_result` 自動計算品質分數

## 測試覆蓋
- 所有新增功能均有對應單元測試 (`tests/test_v4_08_news_guard.py`)
- 測試通過率 100%

## 使用範例
```python
from openclaw.news_guard import cross_verify_news

def brave_search(q, n): ...
def twitter_search(q, n): ...

result = cross_verify_news(
    text="川普關稅政策可能衝擊 AI 巨頭供應鏈",
    brave_search=brave_search,
    twitter_search=twitter_search
)
print(result.verified, result.weight, result.evidence)
```

## 備註
- 升級日期：2026-03-01
- 程式碼路徑：`src/openclaw/news_guard.py`
- 測試路徑：`tests/test_v4_08_news_guard.py`
