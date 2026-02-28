import React, { useEffect, useMemo, useState } from 'react'
import KpiCard from '../components/KpiCard'
import { calcPortfolioKpis, fetchPortfolioPositions, mockPositions } from '../lib/portfolio'
import { formatCurrency, formatNumber } from '../lib/format'

export default function PortfolioPage() {
  const [positions, setPositions] = useState(mockPositions)
  const [source, setSource] = useState('mock')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)

    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 1500)

    try {
      const data = await fetchPortfolioPositions({ signal: controller.signal })
      setPositions(data)
      setSource('api')
    } catch (e) {
      setPositions(mockPositions)
      setSource('mock')
      setError(String(e?.message || e))
    } finally {
      clearTimeout(timeout)
      setLoading(false)
    }
  }

  useEffect(() => {
    // MVP: try API first; fallback to mock
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const kpis = useMemo(() => calcPortfolioKpis(positions), [positions])
  const unrealizedTone = kpis.unrealized >= 0 ? 'good' : 'bad'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold">庫存總覽 (Portfolio)</div>
          <div className="mt-1 text-xs text-slate-400">
            Data source:{' '}
            <span
              className={
                source === 'api'
                  ? 'rounded-md bg-emerald-500/10 px-2 py-0.5 text-emerald-300 ring-1 ring-emerald-500/20'
                  : 'rounded-md bg-slate-800/50 px-2 py-0.5 text-slate-200 ring-1 ring-slate-700'
              }
            >
              {source.toUpperCase()}
            </span>
            {error ? <span className="ml-2 text-rose-300">(fallback: {error})</span> : null}
          </div>
        </div>

        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2 text-sm text-slate-200 shadow-panel transition hover:bg-slate-900 disabled:opacity-50"
        >
          {loading ? 'Loading…' : 'Reload'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <KpiCard title="總資產" value={formatCurrency(kpis.total)} subtext="Σ (qty × lastPrice)" />
        <KpiCard
          title="未實現損益"
          value={formatCurrency(kpis.unrealized)}
          subtext="需要 avgCost 才能計算；API 可選" 
          tone={unrealizedTone}
        />
      </div>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 shadow-panel">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="text-sm font-semibold">持倉列表</div>
          <div className="text-xs text-slate-400">{positions.length} positions</div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">代碼</th>
                <th className="px-4 py-3">數量</th>
                <th className="px-4 py-3">現價</th>
                <th className="px-4 py-3">市值</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {positions.map((p) => {
                const qty = Number(p.qty || 0)
                const last = Number(p.lastPrice || 0)
                const mv = qty * last
                return (
                  <tr key={p.symbol} className="hover:bg-slate-900/40">
                    <td className="px-4 py-3 font-medium text-slate-100">{p.symbol}</td>
                    <td className="px-4 py-3 text-slate-200">{formatNumber(qty, { maximumFractionDigits: 4 })}</td>
                    <td className="px-4 py-3 text-slate-200">{formatCurrency(last)}</td>
                    <td className="px-4 py-3 text-slate-200">{formatCurrency(mv)}</td>
                  </tr>
                )
              })}

              {positions.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-10 text-center text-slate-400">
                    No positions.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
