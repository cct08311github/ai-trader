const API_URL = 'http://localhost:8080/api/portfolio/positions'

export const mockPositions = [
  { symbol: 'AAPL', qty: 40, lastPrice: 182.34, avgCost: 165.1 },
  { symbol: 'TSLA', qty: 15, lastPrice: 196.72, avgCost: 210.0 },
  { symbol: 'NVDA', qty: 8, lastPrice: 865.5, avgCost: 740.25 }
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

export function calcPortfolioKpis(positions) {
  const total = (positions ?? []).reduce((acc, p) => acc + Number(p.qty || 0) * Number(p.lastPrice || 0), 0)
  const unrealized = (positions ?? []).reduce((acc, p) => {
    const qty = Number(p.qty || 0)
    const last = Number(p.lastPrice || 0)
    const cost = Number(p.avgCost)
    if (!Number.isFinite(cost)) return acc
    return acc + (last - cost) * qty
  }, 0)

  return { total, unrealized }
}
