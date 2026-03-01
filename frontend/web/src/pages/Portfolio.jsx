import React, { useEffect, useMemo, useState } from 'react'
import KpiCard from '../components/KpiCard'
import AllocationDonut from '../components/charts/AllocationDonut'
import PnlLineChart from '../components/charts/PnlLineChart'
import {
  buildAllocationData,
  buildMockEquitySeries,
  calcPortfolioKpis,
  fetchPortfolioPositions,
  mockPositions
} from '../lib/portfolio'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'

function Panel({ title, right, children }) {
  return (
    <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] shadow-panel">
      <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
        <div className="text-sm font-semibold">{title}</div>
        {right ? <div className="text-xs text-[rgb(var(--muted))]">{right}</div> : null}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

export default function PortfolioPage() {
  const [positions, setPositions] = useState(mockPositions)
  const [selectedSymbol, setSelectedSymbol] = useState(null)
  const [source, setSource] = useState('mock')
  const [preferApi, setPreferApi] = useState(true)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const equitySeries = useMemo(() => buildMockEquitySeries({ days: 30, startEquity: 100000 }), [])

  async function load(nextPreferApi = preferApi) {
    setLoading(true)
    setError(null)

    if (!nextPreferApi) {
      setPositions(mockPositions)
      setSource('mock')
      setLoading(false)
      return
    }

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
    load(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const allocation = useMemo(() => buildAllocationData(positions), [positions])
  const kpis = useMemo(() => calcPortfolioKpis(positions, { equitySeries }), [positions, equitySeries])

  const dailyTone = kpis.dailyPnl >= 0 ? 'good' : 'bad'
  const cumulativeTone = kpis.cumulativePnl >= 0 ? 'good' : 'bad'

  const total = kpis.total

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold">庫存總覽 (Portfolio)</div>
          <div className="mt-1 text-xs text-[rgb(var(--muted))]">
            Data source:{' '}
            <span
              className={
                source === 'api'
                  ? 'rounded-md bg-emerald-500/10 px-2 py-0.5 text-emerald-600 dark:text-emerald-300 ring-1 ring-emerald-500/20'
                  : 'rounded-md bg-[rgb(var(--surface))/0.45] px-2 py-0.5 text-[rgb(var(--text))] ring-1 ring-[rgb(var(--border))]'
              }
            >
              {source.toUpperCase()}
            </span>
            {error ? <span className="ml-2 text-rose-600 dark:text-rose-300">(fallback: {error})</span> : null}
          </div>

          <label className="mt-3 inline-flex items-center gap-2 text-xs text-[rgb(var(--muted))]">
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={preferApi}
              onChange={(e) => {
                const v = e.target.checked
                setPreferApi(v)
                load(v)
              }}
            />
            Prefer API (failover to mock)
          </label>
        </div>

        <button
          type="button"
          onClick={() => load(preferApi)}
          disabled={loading}
          className="w-full sm:w-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.35] px-4 py-2 text-sm text-[rgb(var(--text))] shadow-panel transition hover:bg-[rgb(var(--surface))/0.5] disabled:opacity-50"
        >
          {loading ? 'Loading…' : 'Reload'}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard title="總資產" value={formatCurrency(kpis.total)} subtext="Σ (qty × lastPrice)" />
        <KpiCard title="日損益" value={formatCurrency(kpis.dailyPnl)} subtext="Mock equity curve" tone={dailyTone} />
        <KpiCard title="累計損益" value={formatCurrency(kpis.cumulativePnl)} subtext="Mock equity curve" tone={cumulativeTone} />
        <KpiCard
          title="夏普比率"
          value={kpis.sharpe == null ? '-' : formatNumber(kpis.sharpe, { maximumFractionDigits: 2 })}
          subtext="(mock) annualized"
          tone={kpis.sharpe != null && kpis.sharpe >= 1 ? 'good' : 'neutral'}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="資產分配" right={allocation.length ? `${allocation.length} symbols` : 'No data'}>
          {allocation.length ? (
            <AllocationDonut data={allocation} />
          ) : (
            <div className="py-16 text-center text-sm text-[rgb(var(--muted))]">No allocation data.</div>
          )}
        </Panel>

        <Panel title="損益趨勢" right="Equity curve (mock)">
          <PnlLineChart data={equitySeries} />
        </Panel>
      </div>

      <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] shadow-panel">
        <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
          <div className="text-sm font-semibold">持倉列表</div>
          <div className="text-xs text-[rgb(var(--muted))]">{positions.length} positions</div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-[rgb(var(--muted))]">
              <tr>
                <th className="px-4 py-3">代碼</th>
                <th className="px-4 py-3">成本</th>
                <th className="px-4 py-3">現價</th>
                <th className="px-4 py-3">數量</th>
                <th className="px-4 py-3">未實現損益</th>
                <th className="px-4 py-3">持倉比例</th>
                <th className="px-4 py-3">籌碼健康度</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[rgb(var(--border))]">
              {positions.map((p) => {
                const qty = Number(p.qty || 0)
                const last = Number(p.lastPrice || 0)
                const avg = Number(p.avgCost)
                const mv = qty * last
                const weight = total > 0 ? mv / total : 0
                const unreal = Number.isFinite(avg) ? (last - avg) * qty : null

                const pnlTone =
                  unreal == null
                    ? 'text-[rgb(var(--muted))]'
                    : unreal >= 0
                      ? 'text-emerald-600 dark:text-emerald-300'
                      : 'text-rose-600 dark:text-rose-300'

                return (
                  <tr key={p.symbol} className="hover:bg-[rgb(var(--surface))/0.35] cursor-pointer" onClick={() => setSelectedSymbol(p.symbol)}>
                    <td className="px-4 py-3 font-medium text-[rgb(var(--text))]">{p.symbol}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{Number.isFinite(avg) ? formatCurrency(avg) : '-'}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{formatCurrency(last)}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{formatNumber(qty, { maximumFractionDigits: 4 })}</td>
                    <td className={`px-4 py-3 ${pnlTone}`}>{unreal == null ? '-' : formatCurrency(unreal)}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{formatPercent(weight)}</td>
                    <td className="px-4 py-3">
                      {p.chipHealthScore != null ? (
                        <div className="flex items-center gap-2">
                          <div className="h-2 w-16 rounded-full bg-gray-800">
                            <div
                              className={`h-full rounded-full ${
                                p.chipHealthScore <= 3 ? 'bg-red-500' : p.chipHealthScore <= 6 ? 'bg-yellow-500' : 'bg-green-500'
                              }`}
                              style={{`width: ${p.chipHealthScore * 10}%`}}
                            />
                          </div>
                          <span className={`text-xs ${
                                p.chipHealthScore <= 3 ? 'text-red-400' : p.chipHealthScore <= 6 ? 'text-yellow-400' : 'text-green-400'
                          }`}>
                            {p.chipHealthScore}
                          </span>
                        </div>
                      ) : (
                        '-'
                      )}
                    </td>                  </tr>
                )
              })}

              {positions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-[rgb(var(--muted))]">
                    No positions.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="border-t border-[rgb(var(--border))] px-4 py-3 text-xs text-[rgb(var(--muted))]">
          Notes: 未實現損益需提供 avgCost；此頁面包含 mock equity curve（之後可替換為真實 PnL API）。
        </div>
      </section>

      <div className="sr-only" aria-live="polite">
        {loading ? 'Loading portfolio data' : `Portfolio data loaded from ${source}`}
      </div>
    </div>
  )
}

      {selectedSymbol && (
        <div className="fixed inset-0 z-50 flex items-center justify-end bg-black/60" onClick={() => setSelectedSymbol(null)}>
          <div className="h-full w-full max-w-md bg-slate-900 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-slate-800 p-4">
              <h3 className="text-lg font-semibold">持倉詳情 - {selectedSymbol}</h3>
              <button onClick={() => setSelectedSymbol(null)} className="text-slate-400 hover:text-white">
                Close
              </button>
            </div>
            <div className="p-4">
              <p>Loading details for {selectedSymbol}...</p>
              {/* TODO: Fetch position details from API */}
            </div>
          </div>
        </div>
      )}
