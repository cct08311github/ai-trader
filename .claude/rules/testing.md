---
globs: ["tests/**", "**/tests/**", "test_*", "*_test.*"]
---

# 測試規範

## 後端 Python（pytest）
```bash
cd frontend/backend && python -m pytest tests/ -q   # FastAPI
pytest -q                                            # 核心引擎（根目錄 pytest.ini）
```

### 必讀規則
- 所有 FastAPI fixture：`monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")`
- 用 `monkeypatch.setenv`，**禁用** `os.environ =`（不自動清理）
- 測試 DB 建 `orders + fills` 表（非舊版 `trades`）
- 兩個獨立測試目錄：`frontend/backend/tests/` + `tests/frontend_backend/`
- `conn_dep` 500 路徑：patch `db_mod.get_conn` + `monkeypatch.setattr(aa, "db", db_mod)`
- route 覆蓋率：成功路徑 + 錯誤路徑各自獨立測試
- `full_client` 陷阱：`importlib.reload()` 覆蓋 autouse monkeypatch → 在 test method 內 monkeypatch
- `close_position`：`_is_tw_trading_hours()` 非交易時段回 403 → 測試 mock 為 True
- Simulation reconciliation：broker 持倉為空屬預期 → 驗證 `resolved_simulation` + false-positive suppression

## 前端 JavaScript（vitest）
```bash
cd frontend/web && npm test -- --run
```

### 必讀規則
- 多匹配文字：`queryAllByText`（非 `getByText`）
- 繁中 loading：`讀取中…` / `讀取庫存資料中...`（非 `Loading…`）
