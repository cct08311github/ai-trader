import React, { useEffect, useMemo, useState } from 'react'
import { Lock, TrendingDown } from 'lucide-react'
import { useToast } from '../components/ToastProvider'
import PmStatusCard from '../components/PmStatusCard'
import KpiCard from '../components/KpiCard'
import AllocationDonut from '../components/charts/AllocationDonut'
import PnlLineChart from '../components/charts/PnlLineChart'
import PositionDetailDrawer from '../components/PositionDetailDrawer'
import { mockPositions, fetchPortfolioPositions, fetchEquityCurve, buildAllocationData, calcPortfolioKpis, fetchPortfolioKpis, fetchLockedSymbols, lockSymbol, unlockSymbol, closePosition } from '../lib/portfolio'
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

/** Chip health score bar — design doc §4.1 visual spec */
function ChipScoreBar({ score }) {
  if (score == null) return <span className="text-[rgb(var(--muted))]">-</span>
  const pct = Math.min(100, Math.max(0, (score / 10) * 100))
  let barColor = 'bg-rose-500'
  let textColor = 'text-rose-400'
  if (score >= 7) { barColor = 'bg-emerald-500'; textColor = 'text-emerald-400' }
  else if (score >= 4) { barColor = 'bg-amber-500'; textColor = 'text-amber-400' }
  return (
    <span className="flex items-center gap-2">
      <span className="relative h-1.5 w-14 rounded-full bg-slate-700 overflow-hidden">
        <span className={`absolute inset-y-0 left-0 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </span>
      <span className={`text-xs font-medium ${textColor}`}>{score}</span>
    </span>
  )
}

/** Sector concentration donut with 40% warning — design doc §4.1 */
function AllocationWithWarning({ data }) {
  const warnings = data.filter(d => (d.weight ?? 0) > 0.40)
  return (
    <div>
      <AllocationDonut data={data} warnThreshold={40} />
      {warnings.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {warnings.map(d => (
            <span key={d.label} className="flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs text-rose-300">
              ⚠️ {d.label} {((d.weight ?? 0) * 100).toFixed(1)}% 超過 40% 集中度上限
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** 平倉確認 Modal */
function ClosePositionModal({ position, onConfirm, onCancel, busy }) {
  if (!position) return null
  const qty = Number(position.qty || 0)
  const avg = Number(position.avgCost || position.avg_price || 0)
  const last = Number(position.lastPrice || position.last_price || avg)
  const unreal = Number.isFinite(avg) && last ? (last - avg) * qty : null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onCancel}>
      <div
        className="w-full max-w-sm rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
        onMouseDown={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <TrendingDown className="h-5 w-5 text-rose-400 flex-shrink-0" />
          <div>
            <div className="text-sm font-semibold text-slate-100">確認平倉</div>
            <div className="text-xs text-slate-400 mt-0.5">以下操作將立即反向賣出全部持倉</div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 space-y-2 text-xs mb-5">
          <div className="flex justify-between">
            <span className="text-slate-400">標的</span>
            <span className="text-slate-100 font-mono font-semibold">
              {position.symbol}{position.name && position.name !== position.symbol ? ` ${position.name}` : ''}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">賣出數量</span>
            <span className="text-slate-100">{formatNumber(qty)} 股</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">均價（成本）</span>
            <span className="text-slate-100">{formatCurrency(avg)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">賣出參考價</span>
            <span className="text-slate-100">{last ? formatCurrency(last) : '均價（市場休市）'}</span>
          </div>
          {unreal != null && (
            <div className="flex justify-between border-t border-slate-800 pt-2">
              <span className="text-slate-400">未實現損益</span>
              <span className={unreal >= 0 ? 'text-emerald-400 font-medium' : 'text-rose-400 font-medium'}>
                {unreal >= 0 ? '+' : ''}{formatCurrency(unreal)}
              </span>
            </div>
          )}
        </div>

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={busy}
            className="flex-1 rounded-xl border border-slate-700 py-2.5 text-sm font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-50 transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="flex-1 rounded-xl bg-rose-600 py-2.5 text-sm font-semibold text-white hover:bg-rose-500 disabled:opacity-50 transition-colors"
          >
            {busy ? '執行中…' : '確認平倉'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PortfolioPage() {
  const [positions, setPositions] = useState([])
  const [source, setSource] = useState('api')
  const [preferApi, setPreferApi] = useState(true)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  // Drawer state — design doc §4.1
  const [drawerSymbol, setDrawerSymbol] = useState(null)
  const [drawerPosition, setDrawerPosition] = useState(null)
  const toast = useToast()
  // Close position state
  const [closeTarget, setCloseTarget] = useState(null)   // position object
  const [closeBusy, setCloseBusy] = useState(false)

  const [equitySeries, setEquitySeries] = useState([])
  const [equitySource, setEquitySource] = useState('讀取中...')
  const [backendKpis, setBackendKpis] = useState({ available_cash: 0, today_trades_count: 0, overall_win_rate: 0 })
  const [lockedSymbols, setLockedSymbols] = useState(new Set())

  // P1-6: Fetch real equity curve on mount; fallback to mock if no DB data
  useEffect(() => {
    fetchEquityCurve({ days: 60, startEquity: 100000 }).then(data => {
      if (data.length > 0) {
        setEquitySeries(data)
        setEquitySource('DB')
      } else {
        setEquitySource('mock (no trades)')
      }
    })
    fetchLockedSymbols().then(setLockedSymbols)
  }, [])

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
    const timeout = setTimeout(() => controller.abort(), 10000)

    try {
      const [data, kpisData] = await Promise.all([
        fetchPortfolioPositions({ signal: controller.signal }),
        fetchPortfolioKpis({ signal: controller.signal })
      ])
      setPositions(data)
      setBackendKpis(kpisData)
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

  async function handleCloseConfirm() {
    if (!closeTarget) return
    setCloseBusy(true)
    try {
      const res = await closePosition(closeTarget.symbol)
      toast.success(`已平倉 ${res.qty_closed} 股 @ ${formatCurrency(res.sell_price)}`)
      setCloseTarget(null)
      await load(preferApi)   // refresh positions
    } catch (e) {
      toast.error(String(e?.message || e))
      setCloseTarget(null)
    } finally {
      setCloseBusy(false)
    }
  }

  const allocation = useMemo(() => buildAllocationData(positions), [positions])
  const kpis = useMemo(() => calcPortfolioKpis(positions, { equitySeries }), [positions, equitySeries])

  const dailyTone = kpis.dailyPnl >= 0 ? 'good' : 'bad'
  const cumulativeTone = kpis.cumulativePnl >= 0 ? 'good' : 'bad'
  const total = kpis.total

  return (
    <div className="space-y-6">
      {/* Daily PM approval status */}
      <PmStatusCard />

      {/* Header / controls */}
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

      {/* KPIs — design doc §4.1: 當日損益、總資產 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KpiCard title="總資產" value={formatCurrency(kpis.total)} subtext="Σ (qty × lastPrice)" />
        <KpiCard title="可用現金" value={formatCurrency(backendKpis.available_cash)} subtext="DB Snapshot" tone="neutral" />
        <KpiCard title="日損益" value={formatCurrency(kpis.dailyPnl)} subtext={`Equity (${equitySource})`} tone={dailyTone} />
        <KpiCard title="累計損益" value={formatCurrency(kpis.cumulativePnl)} subtext={`Equity (${equitySource})`} tone={cumulativeTone} />

        <KpiCard title="今日成交筆數" value={formatNumber(backendKpis.today_trades_count)} subtext="Trades DB" tone="neutral" />
        <KpiCard
          title="整體勝率"
          value={`${formatNumber(backendKpis.overall_win_rate * 100, { maximumFractionDigits: 1 })}%`}
          subtext="Winning / Closed Trades"
          tone={backendKpis.overall_win_rate >= 0.5 ? 'good' : (backendKpis.overall_win_rate === 0 ? 'neutral' : 'bad')}
        />
        <KpiCard
          title="夏普比率"
          value={kpis.sharpe == null ? '-' : formatNumber(kpis.sharpe, { maximumFractionDigits: 2 })}
          subtext={kpis.sharpe == null ? '需有已實現損益才可計算' : `(${equitySource}) annualized`}
          tone={kpis.sharpe != null && kpis.sharpe >= 1 ? 'good' : 'neutral'}
        />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel title="板塊集中度" right={allocation.length ? `${allocation.length} symbols` : 'No data'}>
          {allocation.length ? (
            <AllocationWithWarning data={allocation} />
          ) : (
            <div className="py-16 text-center text-sm text-[rgb(var(--muted))]">No allocation data.</div>
          )}
        </Panel>

        <Panel title="損益趨勢" right={`Equity curve (${equitySource})`}>
          <PnlLineChart data={equitySeries} />
        </Panel>
      </div>

      {/* Positions table — click row to open drawer */}
      <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] shadow-panel">
        <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-3">
          <div className="text-sm font-semibold">持倉列表</div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-[rgb(var(--muted))]">{positions.length} positions</span>
            <span className="text-xs text-emerald-400/70 hidden sm:block">← 點擊任一行查看詳情</span>
          </div>
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
                <th className="hidden sm:table-cell px-4 py-3">持倉比例</th>
                <th className="hidden sm:table-cell px-4 py-3">籌碼評分</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[rgb(var(--border))]">
              {positions.map((p) => {
                const qty = Number(p.qty || 0)
                const last = Number(p.lastPrice || p.last_price || 0)
                const avg = Number(p.avgCost || p.avg_price)
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
                  <tr
                    key={p.symbol}
                    className="cursor-pointer hover:bg-emerald-500/5 hover:ring-1 hover:ring-inset hover:ring-emerald-500/20 transition-colors"
                    onClick={() => { setDrawerSymbol(p.symbol); setDrawerPosition(p) }}
                    title={`點擊查看 ${p.symbol} 詳情`}
                  >
                    <td className="px-4 py-3 font-medium text-[rgb(var(--text))]">
                      <div className="flex items-center gap-1.5">
                        {p.symbol}
                        {lockedSymbols.has(p.symbol) && (
                          <Lock className="h-3.5 w-3.5 text-amber-400 flex-shrink-0" title="鎖定：禁止賣出" />
                        )}
                      </div>
                      {p.name && <div className="text-xs text-[rgb(var(--muted))]">{p.name}</div>}
                    </td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{Number.isFinite(avg) ? formatCurrency(avg) : '-'}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{formatCurrency(last)}</td>
                    <td className="px-4 py-3 text-[rgb(var(--text))]">{formatNumber(qty, { maximumFractionDigits: 4 })}</td>
                    <td className={`px-4 py-3 ${pnlTone}`}>{unreal == null ? '-' : formatCurrency(unreal)}</td>
                    <td className="hidden sm:table-cell px-4 py-3 text-[rgb(var(--text))]">{formatPercent(weight)}</td>
                    <td className="hidden sm:table-cell px-4 py-3">
                      <ChipScoreBar score={p.chip_score ?? p.chip_health_score ?? null} />
                    </td>
                    <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                      {lockedSymbols.has(p.symbol) ? (
                        <span className="flex items-center gap-1 text-xs text-amber-500/60" title="鎖定部位，無法平倉">
                          <Lock className="h-3 w-3" /> 鎖定
                        </span>
                      ) : (
                        <button
                          onClick={() => setCloseTarget(p)}
                          className="rounded-lg border border-rose-700/50 bg-rose-900/20 px-2.5 py-1.5 text-[11px] font-semibold text-rose-300 hover:bg-rose-800/40 transition-colors"
                        >
                          平倉
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}

              {positions.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-10 text-center text-[rgb(var(--muted))]">
                    No positions.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="border-t border-[rgb(var(--border))] px-4 py-3 text-xs text-[rgb(var(--muted))]">
          點擊持倉行查看進場理由、止損止盈、決策鏈及籌碼趨勢。損益曲線與夏普比率在首次平倉後將自動顯示。
        </div>
      </section>

      {/* Close Position Modal */}
      <ClosePositionModal
        position={closeTarget}
        onConfirm={handleCloseConfirm}
        onCancel={() => setCloseTarget(null)}
        busy={closeBusy}
      />

      {/* Position Detail Drawer — design doc §4.1 */}
      {drawerSymbol && (
        <PositionDetailDrawer
          symbol={drawerSymbol}
          position={drawerPosition}
          isLocked={lockedSymbols.has(drawerSymbol)}
          onLockChange={(symbol, locked) => {
            setLockedSymbols(prev => {
              const next = new Set(prev)
              if (locked) next.add(symbol)
              else next.delete(symbol)
              return next
            })
          }}
          onClose={() => { setDrawerSymbol(null); setDrawerPosition(null) }}
        />
      )}

      <div className="sr-only" aria-live="polite">
        {loading ? 'Loading portfolio data' : `Portfolio data loaded from ${source}`}
      </div>
    </div>
  )
}
