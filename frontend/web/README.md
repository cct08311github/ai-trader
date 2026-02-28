# AI Trader — Frontend (Sprint 1)

## Tech
- Vite + React
- Tailwind CSS
- react-router-dom

## Run dev server

```bash
cd /Users/openclaw/.openclaw/shared/projects/ai-trader/frontend/web
npm install
npm run dev
```

Open: http://localhost:5173

## Portfolio API (placeholder)
UI will try API first and fallback to mock data:

```ts
fetch('http://localhost:8080/api/portfolio/positions')
```

Recommended response shape:

```json
[
  {"symbol":"AAPL","qty":40,"lastPrice":182.34,"avgCost":165.1}
]
```

- `avgCost` is optional (used for unrealized P/L)

## Pages
- Portfolio (MVP)
- Trades (placeholder)
- Strategy (placeholder)
- System (placeholder)
