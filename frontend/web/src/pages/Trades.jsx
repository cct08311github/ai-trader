/**
 * Trades.jsx -- Trading Terminal Layout
 *
 * Complete layout restructure:
 *   Top: Command bar with filter toggles (monospace buttons)
 *   Left column (4/12): Live order stats -- today's fills, volume, win rate
 *   Right column (8/12): Order list as mini-cards (not table rows)
 *   Bottom: Fixed daily P&L summary bar
 *
 * All data fetching and state management preserved from original.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { FileText, ChevronDown, ChevronUp, Download, Filter, X } from 'lucide-react'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'
import { downloadTextFile, fetchTrades, fetchTradeCausalChain, mockTrades, tradesToCsv, tradesToExcelXml } from '../lib/trades'
import { authFetch, getApiBase } from '../lib/auth'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorState from '../components/ErrorState'

function toIsoDate(d) {
  if (!d) return ''
  return `${d}T00:00:00Z`
}

function toIsoDateEnd(d) {
  if (!d) return ''
  return `${d}T23:59:59Z`
}

function toTWN(isoStr) {
  if (!isoStr) return '-'
  try {
    const dt = new Date(isoStr)
    if (isNaN(dt)) return isoStr
    return dt.toLocaleString('zh-TW', {
      timeZone: 'Asia/Taipei',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false
    })
  } catch {
    return isoStr
  }
}

function toTimeOnly(isoStr) {
  if (!isoStr) return '-'
  try {
    const dt = new Date(isoStr)
    if (isNaN(dt)) return '-'
    return dt.toLocaleString('zh-TW', {
      timeZone: 'Asia/Taipei',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false
    })
  } catch { return '-' }
}

/* ── Toggle Button (monospace filter) ─────────────────────── */
function ToggleBtn({ active, label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 font-mono text-[10px] font-bold uppercase tracking-widest transition-all ${
        active
          ? 'border border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.12)] text-[rgb(var(--accent))]'
          : 'border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.2)] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))] hover:border-[rgba(var(--grid),0.5)]'
      }`}
      style={{ borderRadius: '2px' }}
    >{label}</button>
  )
}

/* ── Status Dot ───────────────────────────────────────────── */
function StatusDot({ status }) {
  const s = String(status || 'filled').toLowerCase()
  const colorMap = {
    filled: 'bg-[rgb(var(--up))]',
    partial: 'bg-[rgb(var(--warn))]',
    cancelled: 'bg-[rgb(var(--danger))]',
    pending: 'bg-[rgb(var(--warn))] animate-pulse',
  }
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${colorMap[s] || 'bg-[rgb(var(--muted))]'}`}
      title={s.toUpperCase()}
      style={{ boxShadow: s === 'filled' ? '0 0 4px rgba(var(--up),0.4)' : 'none' }}
    />
  )
}

/* ── Stat Block (for left panel) ──────────────────────────── */
function StatBlock({ label, value, sub, tone }) {
  const toneMap = {
    good: 'text-[rgb(var(--up))]',
    bad: 'text-[rgb(var(--danger))]',
    warn: 'text-[rgb(var(--warn))]',
    neutral: 'text-[rgb(var(--text))]',
  }
  return (
    <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
      <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">{label}</div>
      <div className={`mt-1.5 font-mono text-xl font-black tabular-nums ${toneMap[tone] || toneMap.neutral}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 font-mono text-[10px] text-[rgb(var(--muted))]">{sub}</div>}
    </div>
  )
}

/* ── Monthly Stats (for left panel) ───────────────────────── */
function MonthlyStats() {
  const now = new Date()
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  const [month, setMonth] = useState(defaultMonth)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    const base = getApiBase()
    authFetch(`${base}/api/portfolio/monthly-summary?month=${month}`)
      .then(r => r.json())
      .then(d => { setData(d?.data || d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [month])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">MONTHLY STATS</span>
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--text))] focus:border-[rgba(var(--accent),0.5)] focus:outline-none"
          style={{ borderRadius: '2px' }}
        />
      </div>
      {loading ? (
        <div className="py-4"><LoadingSpinner label="Loading..." /></div>
      ) : (
        <div className="space-y-2">
          <StatBlock label="TURNOVER" value={data ? formatCurrency(data.total_amount) : '--'} />
          <StatBlock label="FEE + TAX" value={data ? formatCurrency(data.total_fee_tax) : '--'} tone="warn" />
          <StatBlock label="WIN RATE" value={data ? formatPercent(data.win_rate) : '--'} tone={data?.win_rate >= 0.5 ? 'good' : 'bad'} />
          <StatBlock label="AVG HOLDING" value={data ? `${Number(data.avg_holding_days).toFixed(1)}d` : '--'} />
          <StatBlock label="MAX GAIN" value={data?.max_profit != null ? formatCurrency(data.max_profit) : '--'} tone="good" />
          <StatBlock label="MAX LOSS" value={data?.max_loss != null ? formatCurrency(data.max_loss) : '--'} tone="bad" />
        </div>
      )}
    </div>
  )
}

/* ── Trade Mini-Card ──────────────────────────────────────── */
function TradeMiniCard({ trade, symbolNames, onClick, isExpanded }) {
  const qty = Number(trade.quantity || 0)
  const price = Number(trade.price || 0)
  const amount = Number(trade.amount ?? qty * price)
  const pnl = Number(trade.pnl || 0)
  const isBuy = String(trade.action).toLowerCase() === 'buy'
  const accentColor = isBuy ? '--up' : '--danger'

  return (
    <div
      className="group cursor-pointer border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.4)] transition-all hover:bg-[rgba(var(--surface),0.6)] hover:border-[rgba(var(--grid),0.4)]"
      style={{
        borderRadius: '2px',
        borderLeft: `3px solid rgb(var(${accentColor}))`,
      }}
      onClick={() => onClick(trade)}
    >
      <div className="px-4 py-3">
        {/* Row 1: Symbol + Status */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="font-mono text-base font-black tracking-tight text-[rgb(var(--text))]">
              {formatSymbol(trade.symbol, symbolNames)}
            </span>
            <span className={`font-mono text-[10px] font-bold uppercase tracking-widest`}
                  style={{ color: `rgb(var(${accentColor}))` }}>
              {String(trade.action).toUpperCase()}
            </span>
          </div>
          <StatusDot status={trade.status} />
        </div>

        {/* Row 2: Price / Qty / Time stacked */}
        <div className="mt-2 flex items-end justify-between gap-4">
          <div className="flex gap-5">
            <div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">PRICE</div>
              <div className="font-mono text-sm font-bold tabular-nums text-[rgb(var(--text))]">{formatCurrency(price)}</div>
            </div>
            <div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">QTY</div>
              <div className="font-mono text-sm tabular-nums text-[rgb(var(--text))]">{formatNumber(qty, { maximumFractionDigits: 4 })}</div>
            </div>
            <div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">AMOUNT</div>
              <div className="font-mono text-sm tabular-nums text-[rgb(var(--text))]">{formatCurrency(amount)}</div>
            </div>
          </div>
          <div className="text-right">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">P&L</div>
            <div className={`font-mono text-sm font-bold tabular-nums ${
              trade.pnl == null ? 'text-[rgb(var(--muted))]' : pnl >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'
            }`}>
              {trade.pnl == null ? '--' : formatCurrency(pnl)}
            </div>
          </div>
        </div>

        {/* Row 3: Timestamp */}
        <div className="mt-2 font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">
          {toTWN(trade.timestamp)}
        </div>
      </div>
    </div>
  )
}

export default function TradesPage() {
  const symbolNames = useSymbolNames()
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [source, setSource] = useState('loading')

  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState('')
  const [status, setStatus] = useState('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')

  const [sortBy, setSortBy] = useState('time')
  const [sortDir, setSortDir] = useState('desc')

  const [limit, setLimit] = useState(50)
  const [offset, setOffset] = useState(0)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [causalData, setCausalData] = useState(null)
  const [causalLoading, setCausalLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('details')
  const [showFilters, setShowFilters] = useState(false)

  const query = useMemo(
    () => ({
      start: dateStart ? toIsoDate(dateStart) : undefined,
      end: dateEnd ? toIsoDateEnd(dateEnd) : undefined,
      symbol: symbol.trim() ? symbol.trim() : undefined,
      type: type || undefined,
      status: status || undefined,
      limit,
      offset,
      sortBy,
      sortDir
    }),
    [dateStart, dateEnd, symbol, type, status, limit, offset, sortBy, sortDir]
  )

  async function load({ silent = false } = {}) {
    if (!silent) setLoading(true)
    setError(null)
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 8000)
    try {
      const data = await fetchTrades({ ...query, signal: controller.signal })
      setItems(data.items)
      setTotal(data.total)
      setSource('api')
    } catch (e) {
      setItems([])
      setTotal(0)
      setSource('error')
      setError(String(e?.message || e))
    } finally {
      clearTimeout(timeout)
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function handleTradeSelect(trade) {
    setSelected(trade)
    setActiveTab('details')
    setCausalData(null)
    if (trade.id) {
      setCausalLoading(true)
      try {
        const data = await fetchTradeCausalChain(trade.id)
        setCausalData(data)
      } catch (e) {
        console.error('Failed to load causal chain:', e)
        setCausalData(null)
      } finally {
        setCausalLoading(false)
      }
    }
  }

  function toggleSort(next) {
    if (sortBy === next) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(next)
      setSortDir('desc')
    }
    setOffset(0)
  }

  const canPrev = offset > 0
  const canNext = offset + limit < total

  function exportCsv() {
    const csv = tradesToCsv(items)
    downloadTextFile(csv, `trades_${new Date().toISOString().slice(0, 10)}.csv`, 'text/csv;charset=utf-8')
  }

  function exportExcel() {
    const xml = tradesToExcelXml(items, { sheetName: 'Trades' })
    downloadTextFile(xml, `trades_${new Date().toISOString().slice(0, 10)}.xls`, 'application/vnd.ms-excel')
  }

  // Compute live stats from current items
  const liveStats = useMemo(() => {
    const buys = items.filter(t => String(t.action).toLowerCase() === 'buy')
    const sells = items.filter(t => String(t.action).toLowerCase() === 'sell')
    const totalVolume = items.reduce((sum, t) => sum + Number(t.amount ?? Number(t.quantity || 0) * Number(t.price || 0)), 0)
    const withPnl = items.filter(t => t.pnl != null)
    const wins = withPnl.filter(t => Number(t.pnl) > 0)
    const winRate = withPnl.length > 0 ? wins.length / withPnl.length : 0
    const dailyPnl = withPnl.reduce((sum, t) => sum + Number(t.pnl || 0), 0)
    return { buys: buys.length, sells: sells.length, totalVolume, winRate, dailyPnl, fillCount: items.length }
  }, [items])

  return (
    <div data-testid="trades-page" className="space-y-4 pb-24 lg:pb-4">

      {/* ══════════════════════════════════════════════════════════
          COMMAND BAR -- filters as monospace toggle buttons
          ══════════════════════════════════════════════════════════ */}
      <div data-testid="trades-filters" className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '3px' }}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">TRADING TERMINAL</span>
            <span className={`h-2 w-2 rounded-full ${source === 'api' ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}`}
                  style={{ boxShadow: source === 'api' ? '0 0 6px rgba(var(--up),0.4)' : 'none' }} />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Side toggles */}
            <ToggleBtn active={!type} label="ALL" onClick={() => { setType(''); setOffset(0) }} />
            <ToggleBtn active={type === 'buy'} label="BUY" onClick={() => { setType(type === 'buy' ? '' : 'buy'); setOffset(0) }} />
            <ToggleBtn active={type === 'sell'} label="SELL" onClick={() => { setType(type === 'sell' ? '' : 'sell'); setOffset(0) }} />

            <div className="w-px h-5 bg-[rgba(var(--grid),0.3)]" />

            {/* Sort toggles */}
            <ToggleBtn active={sortBy === 'time'} label={`TIME ${sortBy === 'time' ? (sortDir === 'desc' ? 'v' : '^') : ''}`} onClick={() => toggleSort('time')} />
            <ToggleBtn active={sortBy === 'pnl'} label={`P&L ${sortBy === 'pnl' ? (sortDir === 'desc' ? 'v' : '^') : ''}`} onClick={() => toggleSort('pnl')} />
            <ToggleBtn active={sortBy === 'amount'} label={`AMT ${sortBy === 'amount' ? (sortDir === 'desc' ? 'v' : '^') : ''}`} onClick={() => toggleSort('amount')} />

            <div className="w-px h-5 bg-[rgba(var(--grid),0.3)]" />

            <button onClick={() => setShowFilters(f => !f)}
              className="flex items-center gap-1 px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))] border border-[rgba(var(--grid),0.3)]"
              style={{ borderRadius: '2px' }}
            >
              <Filter className="h-3 w-3" />FILTERS
            </button>
            <button onClick={() => load()} disabled={loading}
              className="px-3 py-1.5 font-mono text-[10px] font-bold uppercase tracking-widest border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] text-[rgb(var(--accent))] disabled:opacity-50"
              style={{ borderRadius: '2px' }}
            >{loading ? '...' : 'APPLY'}</button>
          </div>
        </div>

        {/* Expanded filter row */}
        {showFilters && (
          <div className="border-t border-[rgba(var(--grid),0.2)] px-4 py-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div>
                <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">SYMBOL</div>
                <input type="text" value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="e.g. 2330"
                  className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))] placeholder:text-[rgb(var(--muted))] focus:outline-none focus:border-[rgba(var(--accent),0.5)]"
                  style={{ borderRadius: '2px' }} />
              </div>
              <div>
                <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FROM</div>
                <input type="date" value={dateStart} onChange={e => setDateStart(e.target.value)}
                  className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))]"
                  style={{ borderRadius: '2px' }} />
              </div>
              <div>
                <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">TO</div>
                <input type="date" value={dateEnd} onChange={e => setDateEnd(e.target.value)}
                  className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))]"
                  style={{ borderRadius: '2px' }} />
              </div>
              <div className="flex items-end gap-2">
                <button onClick={() => { setSymbol(''); setDateStart(''); setDateEnd(''); setStatus(''); setType(''); setTimeout(() => load(), 0) }}
                  className="px-3 py-1.5 font-mono text-[10px] text-[rgb(var(--muted))] border border-[rgba(var(--grid),0.3)]"
                  style={{ borderRadius: '2px' }}
                >CLEAR</button>
                <button data-testid="export-csv" onClick={exportCsv} className="px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--muted))] border border-[rgba(var(--grid),0.3)]" style={{ borderRadius: '2px' }}>
                  <Download className="h-3 w-3 inline mr-1" />CSV
                </button>
                <button data-testid="export-excel" onClick={exportExcel} className="px-2 py-1.5 font-mono text-[10px] text-[rgb(var(--muted))] border border-[rgba(var(--grid),0.3)]" style={{ borderRadius: '2px' }}>
                  <Download className="h-3 w-3 inline mr-1" />XLS
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════
          BATTLE LAYOUT -- asymmetric 4:8 split
          Left: Live order stats
          Right: Order mini-cards
          ══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">

        {/* ── LEFT COLUMN: Live Order Stats ──────────────────── */}
        <div data-testid="trades-stats" className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">ORDER STATS</span>
            <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">{formatNumber(total)} TOTAL</span>
          </div>

          <StatBlock label="FILLS TODAY" value={liveStats.fillCount} sub={`${liveStats.buys} BUY / ${liveStats.sells} SELL`} />
          <StatBlock label="TOTAL VOLUME" value={formatCurrency(liveStats.totalVolume)} sub="CURRENT VIEW" />
          <StatBlock label="WIN RATE" value={formatPercent(liveStats.winRate)} tone={liveStats.winRate >= 0.5 ? 'good' : 'bad'} sub="REALIZED TRADES" />

          <div className="border-t border-[rgba(var(--grid),0.15)] pt-3" />

          <MonthlyStats />
        </div>

        {/* ── RIGHT COLUMN: Order Mini-Cards ─────────────────── */}
        <div className="lg:col-span-8 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">ORDER FEED</span>
            <div className="flex items-center gap-3">
              <select value={limit} onChange={e => { setLimit(Number(e.target.value)); setOffset(0) }}
                className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--text))]"
                style={{ borderRadius: '2px' }}
              >
                {[20, 50, 100, 200].map(n => <option key={n} value={n}>{n}/page</option>)}
              </select>
              <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">
                {Math.floor(offset / limit) + 1}/{Math.max(1, Math.ceil(total / limit))}
              </span>
            </div>
          </div>

          {/* Cards */}
          {loading && items.length === 0 ? (
            <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.15)] py-16" style={{ borderRadius: '3px' }}>
              <LoadingSpinner label="Loading trades..." />
            </div>
          ) : error && items.length === 0 ? (
            <div className="border border-[rgba(var(--danger),0.3)] bg-[rgba(var(--danger),0.05)] p-4" style={{ borderRadius: '3px' }}>
              <ErrorState message="Failed to load trades" description={error} onRetry={() => load()} />
            </div>
          ) : items.length === 0 ? (
            <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.1)] p-8" style={{ borderRadius: '3px' }}>
              <EmptyState icon={FileText} title="NO TRADES" description="Trade records will appear here after execution" />
            </div>
          ) : (
            <div data-testid="trade-list" className="space-y-2">
              {items.map(t => (
                <TradeMiniCard key={t.id} trade={t} symbolNames={symbolNames} onClick={handleTradeSelect} />
              ))}
            </div>
          )}

          {/* Pagination */}
          {items.length > 0 && (
            <div className="flex items-center justify-between border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-2.5" style={{ borderRadius: '2px' }}>
              <div className="font-mono text-[10px] text-[rgb(var(--muted))]">
                PAGE {Math.floor(offset / limit) + 1} / {Math.max(1, Math.ceil(total / limit))}
              </div>
              <div className="flex items-center gap-2">
                <button type="button" disabled={!canPrev}
                  onClick={() => { setOffset(o => Math.max(0, o - limit)); setTimeout(() => load({ silent: true }), 0) }}
                  className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1 font-mono text-[10px] text-[rgb(var(--text))] disabled:opacity-30"
                  style={{ borderRadius: '2px' }}
                >PREV</button>
                <button type="button" disabled={!canNext}
                  onClick={() => { setOffset(o => o + limit); setTimeout(() => load({ silent: true }), 0) }}
                  className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1 font-mono text-[10px] text-[rgb(var(--text))] disabled:opacity-30"
                  style={{ borderRadius: '2px' }}
                >NEXT</button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          BOTTOM: Fixed Daily P&L Summary Bar
          ══════════════════════════════════════════════════════════ */}
      <div data-testid="daily-pnl" className="fixed bottom-0 left-0 right-0 z-40 border-t-2 border-[rgba(var(--grid),0.3)] bg-[rgb(var(--bg))] backdrop-blur-xl lg:left-64">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">DAILY P&L</span>
              <span className={`font-mono text-lg font-black tabular-nums ${liveStats.dailyPnl >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                {liveStats.dailyPnl >= 0 ? '+' : ''}{formatCurrency(liveStats.dailyPnl)}
              </span>
            </div>
            <div className="hidden sm:flex items-center gap-2">
              <span className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FILLS</span>
              <span className="font-mono text-sm font-bold tabular-nums text-[rgb(var(--text))]">{liveStats.fillCount}</span>
            </div>
            <div className="hidden sm:flex items-center gap-2">
              <span className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">VOLUME</span>
              <span className="font-mono text-sm font-bold tabular-nums text-[rgb(var(--text))]">{formatCurrency(liveStats.totalVolume)}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${source === 'api' ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}`} />
            <span className="font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
              {source === 'api' ? 'LIVE' : source.toUpperCase()}
            </span>
          </div>
        </div>
      </div>

      {/* ── Detail Modal ──────────────────────────────────────── */}
      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={() => setSelected(null)}>
          <div
            className="w-full max-w-4xl border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl max-h-[90dvh] overflow-y-auto"
            onClick={e => e.stopPropagation()}
            style={{ borderRadius: '4px' }}
          >
            {/* Modal Header */}
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-1" style={{
                  backgroundColor: String(selected.action).toLowerCase() === 'buy' ? 'rgb(var(--up))' : 'rgb(var(--danger))',
                  borderRadius: '1px'
                }} />
                <div>
                  <div className="font-mono text-lg font-black text-[rgb(var(--text))]">{selected.symbol}</div>
                  <div className="font-mono text-[10px] text-[rgb(var(--muted))]">{selected.id}</div>
                </div>
              </div>
              <button type="button" onClick={() => setSelected(null)}
                className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))] hover:bg-[rgba(var(--surface),0.5)]"
                style={{ borderRadius: '3px' }}
              ><X className="h-4 w-4" /></button>
            </div>

            {/* Tabs */}
            <div className="mt-4 flex border-b border-[rgba(var(--grid),0.3)]">
              <button type="button"
                className={`px-4 py-2 font-mono text-xs font-bold uppercase tracking-widest ${
                  activeTab === 'details'
                    ? 'border-b-2 border-[rgb(var(--accent))] text-[rgb(var(--accent))]'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
                onClick={() => setActiveTab('details')}
              >DETAILS</button>
              <button type="button"
                className={`px-4 py-2 font-mono text-xs font-bold uppercase tracking-widest ${
                  activeTab === 'causal'
                    ? 'border-b-2 border-[rgb(var(--accent))] text-[rgb(var(--accent))]'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
                onClick={() => setActiveTab('causal')}
              >CAUSAL CHAIN</button>
            </div>

            {/* Tab content */}
            <div className="mt-4">
              {activeTab === 'details' ? (
                <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                  {[
                    ['TIMESTAMP', toTWN(selected.timestamp)],
                    ['SYMBOL', selected.symbol],
                    ['SIDE', String(selected.action).toUpperCase(), String(selected.action).toLowerCase() === 'buy' ? 'up' : 'down'],
                    ['QUANTITY', formatNumber(Number(selected.quantity || 0))],
                    ['PRICE', formatCurrency(Number(selected.price || 0))],
                    ['AMOUNT', formatCurrency(Number(selected.amount ?? 0))],
                    ['PNL', selected.pnl == null ? '-' : formatCurrency(Number(selected.pnl)), selected.pnl == null ? null : Number(selected.pnl) >= 0 ? 'up' : 'down'],
                    ['FEE', formatCurrency(Number(selected.fee || 0))],
                    ['TAX', formatCurrency(Number(selected.tax || 0))],
                    ['STATUS', selected.status || 'filled'],
                    ['AGENT', selected.agent_id || '-'],
                    ['DECISION', selected.decision_id || '-'],
                  ].map(([label, value, highlight]) => (
                    <div key={label} className="border-l-2 border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-3 py-2" style={{ borderRadius: '2px' }}>
                      <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
                      <div className={`mt-1 break-all font-mono text-sm font-semibold tabular-nums ${
                        highlight === 'up' ? 'text-[rgb(var(--up))]' : highlight === 'down' ? 'text-[rgb(var(--danger))]' : 'text-[rgb(var(--text))]'
                      }`}>{value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div>
                  {causalLoading ? (
                    <div className="py-8 text-center font-mono text-xs text-[rgb(var(--muted))]">Loading causal chain...</div>
                  ) : causalData ? (
                    <div className="space-y-3">
                      <div className="border-l-2 border-[rgba(var(--accent),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">DECISION</div>
                        <div className="mt-2 space-y-1 font-mono text-xs">
                          <div className="flex justify-between">
                            <span className="text-[rgb(var(--muted))]">ID</span>
                            <span className="text-[rgb(var(--text))]">{causalData.decision.decision_id}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-[rgb(var(--muted))]">SIGNAL</span>
                            <span className={`font-bold ${causalData.decision.signal_side === 'buy' ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                              {causalData.decision.signal_side.toUpperCase()}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="border-l-2 border-[rgba(var(--warn),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">RISK CHECK</div>
                        <div className="mt-2 flex items-center gap-2">
                          <span className={`h-2 w-2 rounded-full ${causalData.risk_check.passed ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}`} />
                          <span className={`font-mono text-xs font-bold ${causalData.risk_check.passed ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                            {causalData.risk_check.passed ? 'PASSED' : 'REJECTED'}
                          </span>
                        </div>
                        {causalData.risk_check.reject_code && (
                          <div className="mt-1 font-mono text-xs text-[rgb(var(--muted))]">Code: {causalData.risk_check.reject_code}</div>
                        )}
                      </div>
                      {causalData.llm_traces && causalData.llm_traces.length > 0 ? (
                        <div className="border-l-2 border-[rgba(var(--info),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                          <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">LLM TRACES</div>
                          <div className="mt-2 space-y-3">
                            {causalData.llm_traces.map((trace, index) => (
                              <div key={index} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
                                <div className="flex items-center justify-between">
                                  <span className="font-mono text-xs font-bold text-[rgb(var(--text))]">{trace.agent}</span>
                                  {trace.created_at && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{new Date(trace.created_at * 1000).toLocaleString()}</span>}
                                </div>
                                <div className="mt-2">
                                  <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">PROMPT</div>
                                  <div className="mt-1 max-h-20 overflow-auto font-mono text-[11px] text-[rgb(var(--text))]">{trace.prompt_text}</div>
                                </div>
                                <div className="mt-2">
                                  <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">RESPONSE</div>
                                  <div className="mt-1 max-h-20 overflow-auto font-mono text-[11px] text-[rgb(var(--text))]">{trace.response_text}</div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-4 text-center font-mono text-xs text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>
                          NO LLM TRACE RECORDS
                        </div>
                      )}
                      <div className="border-l-2 border-[rgba(var(--accent),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FILLS</div>
                        <div className="mt-2 space-y-1">
                          {causalData.fills.map((fill, index) => (
                            <div key={index} className="flex justify-between font-mono text-xs">
                              <span className="text-[rgb(var(--muted))]">FILL #{index + 1}</span>
                              <span className="tabular-nums text-[rgb(var(--text))]">{fill.qty} @ {formatCurrency(fill.price)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="py-8 text-center font-mono text-xs text-[rgb(var(--muted))]">UNABLE TO LOAD CAUSAL CHAIN</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
