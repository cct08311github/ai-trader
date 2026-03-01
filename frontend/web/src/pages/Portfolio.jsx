import React, { useEffect, useMemo, useState } from 'react'
import KpiCard from '../components/KpiCard'
import AllocationDonut from '../components/charts/AllocationDonut'
import PnlLineChart from '../components/charts/PnlLineChart'
import {
  buildAllocationData,
  buildMockEquitySeries,
  calcPortfolioKpis,
  fetchPortfolioPositions,
  mockPositions,
  fetchPositionDetail
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

function PositionDetailDrawer({ symbol, onClose }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    setError(null)
    fetchPositionDetail(symbol)
      .then(data => {
        setDetail(data)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [symbol])

  if (!symbol) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/50" 
        onClick={onClose}
      />
      
      {/* Drawer */}
      <div className="relative ml-auto h-full w-full max-w-md bg-[rgb(var(--surface))] shadow-2xl transform transition-transform duration-300 ease-out">
        <div className="flex h-full flex-col">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-6 py-4">
            <div className="text-lg font-semibold">持倉詳情 - {symbol}</div>
            <button
              onClick={onClose}
              className="rounded-full p-2 hover:bg-[rgb(var(--surface))/0.5]"
              aria-label="Close"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {loading ? (
              <div className="flex h-32 items-center justify-center">
                <div className="text-sm text-[rgb(var(--muted))]">載入中...</div>
              </div>
            ) : error ? (
              <div className="rounded-lg border border-rose-200 bg-rose-50 p-4 dark:border-rose-800 dark:bg-rose-900/20">
                <div className="text-sm font-medium text-rose-800 dark:text-rose-300">錯誤</div>
                <div className="mt-1 text-sm text-rose-700 dark:text-rose-400">{error}</div>
              </div>
            ) : detail ? (
              <div className="space-y-6">
                {/* Entry Reason */}
                <div>
                  <div className="text-sm font-medium text-[rgb(var(--muted))]">進場理由</div>
                  <div className="mt-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] p-4">
                    <div className="text-sm">{detail.entry_reason}</div>
                  </div>
                </div>

                {/* Stop Loss / Take Profit */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="text-sm font-medium text-[rgb(var(--muted))]">止損價</div>
                    <div className="mt-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] p-4">
                      <div className="text-lg font-semibold">{formatCurrency(detail.stop_loss)}</div>
                    </div>
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[rgb(var(--muted))]">止盈價</div>
                    <div className="mt-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] p-4">
                      <div className="text-lg font-semibold">{formatCurrency(detail.take_profit)}</div>
                    </div>
                  </div>
                </div>

                {/* PM Authorization */}
                <div>
                  <div className="text-sm font-medium text-[rgb(var(--muted))]">PM 授權原文</div>
                  <div className="mt-2 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] p-4">
                    <div className="text-sm whitespace-pre-wrap">{detail.pm_authorization}</div>
                  </div>
                </div>

                {/* Chip Trend */}
                <div>
                  <div className="text-sm font-medium text-[rgb(var(--muted))]">籌碼趨勢歷史</div>
                  <div className="mt-2 overflow-hidden rounded-lg border border-[rgb(var(--border))]">
                    <table className="min-w-full text-sm">
                      <thead className="border-b border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25]">
                        <tr>
                          <th className="px-4 py-2 text-left">日期</th>
                          <th className="px-4 py-2 text-left">外資買</th>
                          <th className="px-4 py-2 text-left">外資賣</th>
                          <th className="px-4 py-2 text-left">評分</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[rgb(var(--border))]">
                        {detail.chip_trend.map((item, idx) => (
                          <tr key={idx}>
                            <td className="px-4 py-2">{item.date}</td>
                            <td className="px-4 py-2">{item.institution_buy.toLocaleString()}</td>
                            <td className="px-4 py-2">{item.institution_sell.toLocaleString()}</td>
                            <td className="px-4 py-2">
                              <span className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
                                item.score <= 3 ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' :
                                item.score <= 6 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300' :
                                'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
                              }`}>
                                {item.score}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : null}
          </div>

          {/* Footer */}
          <div className="border-t border-[rgb(var(--border))] px-6 py-4">
            <button
              onClick={onClose}
              className="w-full rounded-lg bg-[rgb(var(--primary))] px-4 py-2.5 text-sm font-medium text-white hover:opacity-90"
            >
              關閉
            </button>
          </div>
        </div>
      </div>
    </div>
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
    <>
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
                                style={{width: `${p.chipHealthScore * 10}%`}}
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
                    <td colSpan={7} className="px-4 py-10 text-center text-[rgb