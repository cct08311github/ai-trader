# PM2 服務與運維

## PM2 服務清單

| 服務名 | 說明 |
|--------|------|
| `ai-trader-api` | FastAPI 後端 |
| `ai-trader-web` | React Vite Dev Server（port 3000） |
| `ai-trader-watcher` | ticker_watcher（每 3 分鐘，真實 Shioaji 行情） |
| `ai-trader-agents` | agent_orchestrator（5 Gemini agent） |
| `ai-trader-ops-summary` | 每 15 分鐘 ops summary |
| `ai-trader-reconciliation` | 每交易日 16:45 reconciliation |
| `ai-trader-incident-hygiene` | 每交易日 16:55 incident 去重 |

## Portable Path Convention

Production 代碼**禁止硬編碼** `/Users/openclaw`：
- Shell: `SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"`
- Python: `Path(__file__).resolve().parents...` 或 `OPENCLAW_ROOT_ENV`
