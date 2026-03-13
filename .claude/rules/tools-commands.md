# 常用指令與 Debug 技巧

```bash
# CI
gh run list --limit 5
gh run view <run-id> --log-failed

# 測試
cd frontend/backend && python -m pytest tests/ -q   # FastAPI
pytest -q                                            # 核心引擎
cd frontend/web && npm test -- --run                 # 前端

# 復盤
sqlite3 data/sqlite/trades.db "SELECT * FROM orders WHERE date(ts_submit)='YYYY-MM-DD';"

# API 測試
curl -sk -X POST https://127.0.0.1:8080/api/pm/review \
  -H "Authorization: Bearer $(grep AUTH_TOKEN frontend/backend/.env | cut -d= -f2 | tr -d ' ')"

# PM2
pm2 status && pm2 logs ai-trader-watcher
tail -80 ~/.pm2/logs/ai-trader-api-error-1.log
```
