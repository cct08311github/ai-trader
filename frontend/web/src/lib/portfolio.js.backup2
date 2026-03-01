const API_URL = 'http://localhost:8080/api/portfolio/positions'

export const mockPositions = [
  { symbol: 'AAPL', qty: 40, lastPrice: 182.34, avgCost: 165.1 },
  { symbol: 'TSLA', qty: 15, lastPrice: 196.72, avgCost: 210.0 },
  { symbol: 'NVDA', qty: 8, lastPrice: 865.5, avgCost: 740.25 },
  { symbol: 'MSFT', qty: 12, lastPrice: 404.11, avgCost: 372.35 }
]

/**
 * Expected API shape (recommended):
 * [{ symbol: string, qty: number, lastPrice: number, avgCost?: number }]
 */
export async function fetchPortfolioPositions({ signal } = {}) {
  const res = await fetch(API_URL, { signal })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  if (!Array.isArray(data)) throw new Error('Invalid API response: expected array')
  return data
}

export function calcPortfolioKpis(positions, { equitySeries } = {}) {
  const safe = positions ?? []
  const total = safe.reduce((acc, p) => acc + Number(p.qty || 0) * Number(p.lastPrice || 0), 0)
  const unrealized = safe.reduce((acc, p) => {
    const qty = Number(p.qty || 0)
    const last = Number(p.lastPrice || 0)
    const cost = Number(p.avgCost)
    if (!Number.isFinite(cost)) return acc
    return acc + (last - cost) * qty
  }, 0)

  const series = Array.isArray(equitySeries) ? equitySeries : []
  const dailyPnl = series.length >= 2 ? series[series.length - 1].equity - series[series.length - 2].equity : 0
  const cumulativePnl = series.length >= 1 ? series[series.length - 1].equity - series[0].equity : 0
  const sharpe = calcSharpeFromEquity(series)

  return { total, unrealized, dailyPnl, cumulativePnl, sharpe }
}

export function buildAllocationData(positions) {
  const safe = positions ?? []
  const total = safe.reduce((acc, p) => acc + Number(p.qty || 0) * Number(p.lastPrice || 0), 0)
  if (!Number.isFinite(total) || total <= 0) return []
  return safe
    .map((p) => {
      const value = Number(p.qty || 0) * Number(p.lastPrice || 0)
      return {
        name: p.symbol,
        value,
        weight: value / total
      }
    })
    .sort((a, b) => b.value - a.value)
}

export function buildMockEquitySeries({ days = 30, startEquity = 100000 } = {}) {
  const out = []
  const now = new Date()

  for (let i = days - 1; i >= 0; i -= 1) {
    const d = new Date(now)
    d.setDate(now.getDate() - i)

    // deterministic-ish w/ gentle trend and noise
    const t = (days - 1 - i) / Math.max(1, days - 1)
    const drift = 120 * t
    const noise = Math.sin(i * 1.7) * 220 + Math.cos(i * 0.9) * 120
    const equity = startEquity + drift * (days - i) + noise

    out.push({
      date: d.toISOString().slice(5, 10),
      equity: Math.round(equity * 100) / 100
    })
  }

  return out
}

function calcSharpeFromEquity(series) {
  if (!Array.isArray(series) || series.length < 3) return null
  const returns = []
  for (let i = 1; i < series.length; i += 1) {
    const prev = Number(series[i - 1].equity)
    const cur = Number(series[i].equity)
    if (!Number.isFinite(prev) || prev === 0 || !Number.isFinite(cur)) continue
    returns.push((cur - prev) / prev)
  }
  if (returns.length < 2) return null

  const mean = returns.reduce((a, r) => a + r, 0) / returns.length
  const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / (returns.length - 1)
  const stdev = Math.sqrt(variance)
  if (!Number.isFinite(stdev) || stdev === 0) return null

  return (mean / stdev) * Math.sqrt(252)
}
