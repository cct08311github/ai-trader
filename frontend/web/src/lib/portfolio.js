const DEFAULT_API_BASE = ''

const API_BASE = (import.meta?.env?.VITE_API_BASE || DEFAULT_API_BASE).replace(/\/$/, '')
const API_URL = `${API_BASE}/api/portfolio/positions`

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
  if (!res.ok) throw new Error()
  const data = await res.json()
  // Backend returns { status: "ok", source, simulation, positions }
  if (data.positions && Array.isArray(data.positions)) {
    // Map backend fields to frontend expected fields
    return data.positions.map(p => ({
      symbol: p.symbol || '',
      qty: p.qty || p.quantity || 0,
      lastPrice: p.last_price || p.lastPrice || 0,
      avgCost: p.avg_price || p.avgCost,
      chipHealthScore: p.chip_health_score || p.chipHealthScore,
      sector: p.sector
    }))
  }
  // Fallback: assume array directly
  if (!Array.isArray(data)) throw new Error('Invalid API response: expected array or object with positions')
  return data
}

export async function fetchPositionDetail(symbol) {
  const res = await fetch(`${API_BASE}/api/portfolio/position-detail/${symbol}`)
  if (!res.ok) throw new Error(`Failed to fetch position detail for ${symbol}`)
  const data = await res.json()
  if (data.status === 'ok' && data.data) {
    return data.data
  }
  throw new Error('Invalid API response format')
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
      date: d.toISOString().slice(0, 10),
      equity
    })
  }

  return out
}

function calcSharpeFromEquity(series) {
  if (!Array.isArray(series) || series.length < 2) return null
  const returns = []
  for (let i = 1; i < series.length; i += 1) {
    const prev = series[i - 1].equity
    const curr = series[i].equity
    if (prev <= 0) continue
    returns.push((curr - prev) / prev)
  }
  if (returns.length < 2) return null

  const mean = returns.reduce((a, r) => a + r, 0) / returns.length
  const variance = returns.reduce((a, r) => a + (r - mean) ** 2, 0) / (returns.length - 1)
  const stdev = Math.sqrt(variance)
  if (!Number.isFinite(stdev) || stdev === 0) return null

  return (mean / stdev) * Math.sqrt(252)
}
