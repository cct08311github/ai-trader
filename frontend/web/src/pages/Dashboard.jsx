import React, { useMemo, useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import KpiCard from '../components/KpiCard'
import PmStatusCard from '../components/PmStatusCard'
import AllocationDonut from '../components/charts/AllocationDonut'
import {
  buildAllocationData,
  buildMockEquitySeries,
  calcPortfolioKpis,
  fetchPortfolioPositions,
  mockPositions
} from '../lib/portfolio'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'
import { getToken, getApiBase } from '../lib/auth'

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

export default function DashboardPage() {
  const [positions, setPositions] = useState([])
  const [source, setSource] = useState('api')
  const [preferApi, setPreferApi] = useState(true)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [analysisSnap, setAnalysisSnap] = useState(null)

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
      setPositions([])
      setSource('error')
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

  useEffect(() => {
    fetch(`${getApiBase()}/api/analysis/latest`, {
      headers: { Authorization: `Bearer ${getToken()}` }
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => data && setAnalysisSnap(data))
      .catch(() => {})
  }, [])

  const allocation = useMemo(() => buildAllocationData(positions), [positions])
  const kpis = useMemo(() => calcPortfolioKpis(positions, { equitySeries }), [positions, equitySeries])

  const dailyTone = kpis.dailyPnl >= 0 ? 'good' : 'bad'
  const cumulativeTone = kpis.cumulativePnl >= 0 ? 'good' : 'bad'

  const total = kpis.total

  return (
    <div className="space-y-6">
      {/* Daily PM approval status — must be checked every morning before market open */}
      <PmStatusCard />

      {analysisSnap && (
        <Link to="/analysis" className="block rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] px-4 py-3 hover:bg-[rgb(var(--surface))/0.4] transition-colors">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[rgb(var(--muted))]">
              盤後分析 · {analysisSnap.trade_date}
            </span>
            <span className="text-xs text-emerald-400">查看 →</span>
          </div>
          <p className="mt-1 text-sm truncate">
            {analysisSnap.strategy?.summary || '分析完成'}
          </p>
        </Link>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-sm font-semibold">儀表板總覽 (Dashboard)</div>
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

          {/* Prefer API checkbox removed per user request */}
        </div>

        <button
          type="button"
          onClick={() => load(preferApi)}
          disabled={loading}
          className="w-full sm:w-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.35] px-4 py-2 text-sm text-[rgb(var(--text))] shadow-panel transition hover:bg-[rgb(var(--surface))/0.5] disabled:opacity-50"
        >
          {loading ? '讀取中…' : '重新整理'}
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
        <KpiCard title="風險評級" value="B+" subtext="Medium risk" />
        <KpiCard title="API 配額" value="87%" subtext="87/100 requests" />
        <KpiCard title="持倉數" value={positions.length} subtext="active positions" />
        <KpiCard title="總槓桿" value="1.2x" subtext="Low leverage" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="持倉總覽" right={`${positions.length} positions`}>
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
                </tr>
              </thead>
              <tbody className="divide-y divide-[rgb(var(--border))]">
                {positions.slice(0, 5).map((p) => {
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
                    <tr key={p.symbol} className="hover:bg-[rgb(var(--surface))/0.35]">
                      <td className="px-4 py-3 font-medium text-[rgb(var(--text))]">{p.symbol}</td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{Number.isFinite(avg) ? formatCurrency(avg) : '-'}</td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{formatCurrency(last)}</td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{formatNumber(qty, { maximumFractionDigits: 4 })}</td>
                      <td className={`px-4 py-3 ${pnlTone}`}>{unreal == null ? '-' : formatCurrency(unreal)}</td>
                      <td className="px-4 py-3 text-[rgb(var(--text))]">{formatPercent(weight)}</td>
                    </tr>
                  )
                })}

                {positions.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-[rgb(var(--muted))]">
                      No positions.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {positions.length > 5 && (
            <div className="mt-4 text-center">
              <Link to="/portfolio" className="text-xs text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]">
                View all {positions.length} positions →
              </Link>
            </div>
          )}
        </Panel>

        <Panel title="板塊分佈" right={allocation.length ? `${allocation.length} symbols` : 'No data'}>
          {allocation.length ? (
            <AllocationDonut data={allocation} />
          ) : (
            <div className="py-16 text-center text-sm text-[rgb(var(--muted))]">No allocation data.</div>
          )}
        </Panel>
      </div>

      <div className="sr-only" aria-live="polite">
        {loading ? '讀取儀表板資料中...' : `資料來源：${source}`}
      </div>
    </div>
  )
}
