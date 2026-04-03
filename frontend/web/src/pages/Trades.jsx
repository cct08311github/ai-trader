/**
 * Trades.jsx -- BattleTheme Redesign
 *
 * Brutalist trade ledger. Orders and fills displayed as a
 * military intelligence dossier -- monospace numbers,
 * status dots, accent-border panels, no rounded SaaS cards.
 */

import React, { useEffect, useMemo, useState } from 'react'
import { FileText } from 'lucide-react'
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

/* ── Panel wrapper (brutalist) ─────────────────────────────── */
function Panel({ title, right, children, className = '' }) {
  return (
    <section
      className={`border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.6)] ${className}`}
      style={{ borderRadius: '4px' }}
    >
      <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
        <div className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">{title}</div>
        {right && <div className="font-mono text-[10px] text-[rgb(var(--muted))]">{right}</div>}
      </div>
      <div className="p-4">{children}</div>
    </section>
  )
}

/* ── Status dot ─────────────────────────────────────────────── */
function StatusDot({ color, label }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      <span className="font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</span>
    </span>
  )
}

/* ── Monthly Stats Summary ─────────────────────────────────── */
function MonthlySummaryPanel() {
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

  const stats = [
    { label: 'TURNOVER', value: data ? formatCurrency(data.total_amount) : '-' },
    { label: 'FEE + TAX', value: data ? formatCurrency(data.total_fee_tax) : '-' },
    { label: 'WIN RATE', value: data ? formatPercent(data.win_rate) : '-', good: data?.win_rate >= 0.5 },
    { label: 'AVG HOLD', value: data ? `${Number(data.avg_holding_days).toFixed(1)}d` : '-' },
    { label: 'MAX GAIN', value: data ? (data.max_profit != null ? formatCurrency(data.max_profit) : '-') : '-', good: true },
    { label: 'MAX LOSS', value: data ? (data.max_loss != null ? formatCurrency(data.max_loss) : '-') : '-', bad: true },
  ]

  return (
    <Panel title="MONTHLY SUMMARY" right={month} className="mb-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">
          MONTHLY STATS
        </span>
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-1.5 font-mono text-sm text-[rgb(var(--text))] focus:border-[rgba(var(--accent),0.5)] focus:outline-none"
          style={{ borderRadius: '3px' }}
        />
      </div>
      {loading ? (
        <div className="py-4"><LoadingSpinner label="Loading..." /></div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {stats.map(s => (
            <div key={s.label}
              className="border-l-2 border-[rgba(var(--accent),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2"
              style={{ borderRadius: '2px' }}
            >
              <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{s.label}</div>
              <div className={`mt-1 font-mono text-sm font-bold tabular-nums ${
                s.good ? 'text-[rgb(var(--up))]' : s.bad ? 'text-[rgb(var(--danger))]' : 'text-[rgb(var(--text))]'
              }`}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
    </Panel>
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

  return (
    <div className="space-y-4 pb-20 lg:pb-4">
      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight text-[rgb(var(--text))]">TRADE LEDGER</h1>
          <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
            ORDER HISTORY + CAUSAL CHAIN
          </p>
        </div>
        <StatusDot
          color={source === 'api' ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}
          label={source === 'api' ? 'API LIVE' : source.toUpperCase()}
        />
      </div>

      {/* ── Monthly Summary ─────────────────────────────────────── */}
      <MonthlySummaryPanel />

      {/* ── Filters ─────────────────────────────────────────────── */}
      <Panel title="FILTERS" right={`SORT: ${sortBy} ${sortDir}`}>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">SYMBOL</div>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="e.g. 2330"
              className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))] placeholder:text-[rgb(var(--muted))] focus:outline-none focus:border-[rgba(var(--accent),0.5)]"
              style={{ borderRadius: '3px' }}
            />
          </div>
          <div>
            <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">TYPE</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))]"
              style={{ borderRadius: '3px' }}
            >
              <option value="">All</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div>
            <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FROM</div>
            <input
              type="date"
              value={dateStart}
              onChange={(e) => setDateStart(e.target.value)}
              className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))]"
              style={{ borderRadius: '3px' }}
            />
          </div>
          <div>
            <div className="mb-1 font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">TO</div>
            <input
              type="date"
              value={dateEnd}
              onChange={(e) => setDateEnd(e.target.value)}
              className="w-full border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))]"
              style={{ borderRadius: '3px' }}
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => load()}
              disabled={loading}
              className="border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-4 py-2 font-mono text-xs font-bold uppercase tracking-widest text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.15)] disabled:opacity-50"
              style={{ borderRadius: '3px' }}
            >
              {loading ? '...' : 'APPLY'}
            </button>
            <button
              type="button"
              onClick={() => {
                setSymbol(''); setType(''); setDateStart(''); setDateEnd(''); setStatus('')
                setTimeout(() => load(), 0)
              }}
              className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-4 py-2 font-mono text-xs text-[rgb(var(--muted))] transition hover:bg-[rgba(var(--surface),0.5)]"
              style={{ borderRadius: '3px' }}
            >
              CLEAR
            </button>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={exportCsv}
              className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-xs text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.5)]"
              style={{ borderRadius: '3px' }}
            >CSV</button>
            <button type="button" onClick={exportExcel}
              className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-xs text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.5)]"
              style={{ borderRadius: '3px' }}
            >EXCEL</button>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between font-mono text-[10px] text-[rgb(var(--muted))]">
          <div>LIMIT</div>
          <select
            value={limit}
            onChange={(e) => { setLimit(Number(e.target.value)); setOffset(0) }}
            className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--text))]"
            style={{ borderRadius: '3px' }}
          >
            {[20, 50, 100, 200].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </Panel>

      {/* ── Trade Table ─────────────────────────────────────────── */}
      <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.6)]" style={{ borderRadius: '4px' }}>
        <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">TRADE LIST</span>
          <span className="font-mono text-[10px] text-[rgb(var(--muted))]">
            {formatNumber(total)} TRADES / OFFSET {formatNumber(offset)}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr className="border-b border-[rgba(var(--grid),0.15)]">
                <th className="px-4 py-3 font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                  <button type="button" className="hover:text-[rgb(var(--text))]" onClick={() => toggleSort('time')}>
                    TIME {sortBy === 'time' ? (sortDir === 'asc' ? '^' : 'v') : ''}
                  </button>
                </th>
                <th className="px-4 py-3 font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">SYMBOL</th>
                <th className="px-4 py-3 font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">SIDE</th>
                <th className="px-4 py-3 text-right font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">QTY</th>
                <th className="px-4 py-3 text-right font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">PRICE</th>
                <th className="px-4 py-3 text-right font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                  <button type="button" className="hover:text-[rgb(var(--text))]" onClick={() => toggleSort('amount')}>
                    AMOUNT {sortBy === 'amount' ? (sortDir === 'asc' ? '^' : 'v') : ''}
                  </button>
                </th>
                <th className="px-4 py-3 text-right font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                  <button type="button" className="hover:text-[rgb(var(--text))]" onClick={() => toggleSort('pnl')}>
                    PNL {sortBy === 'pnl' ? (sortDir === 'asc' ? '^' : 'v') : ''}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => {
                const qty = Number(t.quantity || 0)
                const price = Number(t.price || 0)
                const amount = Number(t.amount ?? qty * price)
                const pnl = Number(t.pnl || 0)
                const isBuy = String(t.action).toLowerCase() === 'buy'

                return (
                  <tr
                    key={t.id}
                    className="cursor-pointer border-b border-[rgba(var(--grid),0.08)] transition hover:bg-[rgba(var(--surface),0.4)]"
                    onClick={() => handleTradeSelect(t)}
                  >
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-[rgb(var(--text))]">{toTWN(t.timestamp)}</td>
                    <td className="px-4 py-3 font-mono text-xs font-bold text-[rgb(var(--text))]">{formatSymbol(t.symbol, symbolNames)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1.5 font-mono text-xs font-bold ${
                        isBuy ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'
                      }`}>
                        <span className={`h-1.5 w-1.5 rounded-full ${isBuy ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}`} />
                        {String(t.action).toUpperCase()}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-[rgb(var(--text))]">
                      {formatNumber(qty, { maximumFractionDigits: 4 })}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-[rgb(var(--text))]">{formatCurrency(price)}</td>
                    <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-[rgb(var(--text))]">{formatCurrency(amount)}</td>
                    <td className={`px-4 py-3 text-right font-mono text-xs font-bold tabular-nums ${
                      t.pnl == null ? 'text-[rgb(var(--muted))]' : pnl >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'
                    }`}>
                      {t.pnl == null ? '-' : formatCurrency(pnl)}
                    </td>
                  </tr>
                )
              })}

              {loading && items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12">
                    <LoadingSpinner label="Loading trades..." />
                  </td>
                </tr>
              ) : error && items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8">
                    <ErrorState message="Failed to load trades" description={error} onRetry={() => load()} />
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10">
                    <EmptyState
                      icon={FileText}
                      title="NO TRADES"
                      description="Trade records will appear here after execution"
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between border-t border-[rgba(var(--grid),0.15)] px-4 py-2.5">
          <div className="font-mono text-[10px] text-[rgb(var(--muted))]">
            PAGE {Math.floor(offset / limit) + 1} / {Math.max(1, Math.ceil(total / limit))}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canPrev}
              onClick={() => { setOffset((o) => Math.max(0, o - limit)); setTimeout(() => load({ silent: true }), 0) }}
              className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))] disabled:opacity-30"
              style={{ borderRadius: '3px' }}
            >PREV</button>
            <button
              type="button"
              disabled={!canNext}
              onClick={() => { setOffset((o) => o + limit); setTimeout(() => load({ silent: true }), 0) }}
              className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))] disabled:opacity-30"
              style={{ borderRadius: '3px' }}
            >NEXT</button>
          </div>
        </div>
      </div>

      {/* ── Detail Modal ────────────────────────────────────────── */}
      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={() => setSelected(null)}>
          <div
            className="w-full max-w-4xl border border-[rgba(var(--grid),0.4)] bg-[rgb(var(--bg))] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            style={{ borderRadius: '4px' }}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-mono text-sm font-bold text-[rgb(var(--text))]">TRADE DETAIL -- {selected.symbol}</div>
                <div className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">{selected.id}</div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-xs text-[rgb(var(--text))] hover:bg-[rgba(var(--surface),0.5)]"
                style={{ borderRadius: '3px' }}
              >CLOSE</button>
            </div>

            {/* Tabs */}
            <div className="mt-4 flex border-b border-[rgba(var(--grid),0.3)]">
              <button
                type="button"
                className={`px-4 py-2 font-mono text-xs font-bold uppercase tracking-widest ${
                  activeTab === 'details'
                    ? 'border-b-2 border-[rgb(var(--accent))] text-[rgb(var(--accent))]'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
                onClick={() => setActiveTab('details')}
              >DETAILS</button>
              <button
                type="button"
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
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  <Field label="TIMESTAMP (TWN)" value={toTWN(selected.timestamp)} />
                  <Field label="SYMBOL" value={selected.symbol} />
                  <Field label="SIDE" value={String(selected.action).toUpperCase()}
                    highlight={String(selected.action).toLowerCase() === 'buy' ? 'up' : 'down'} />
                  <Field label="QUANTITY" value={formatNumber(Number(selected.quantity || 0))} />
                  <Field label="PRICE" value={formatCurrency(Number(selected.price || 0))} />
                  <Field label="AMOUNT" value={formatCurrency(Number(selected.amount ?? 0))} />
                  <Field label="PNL" value={selected.pnl == null ? '-' : formatCurrency(Number(selected.pnl))}
                    highlight={selected.pnl == null ? null : Number(selected.pnl) >= 0 ? 'up' : 'down'} />
                  <Field label="FEE" value={formatCurrency(Number(selected.fee || 0))} />
                  <Field label="TAX" value={formatCurrency(Number(selected.tax || 0))} />
                  <Field label="STATUS" value={selected.status || 'filled'} />
                  <Field label="AGENT" value={selected.agent_id || '-'} />
                  <Field label="DECISION" value={selected.decision_id || '-'} />
                </div>
              ) : (
                <div>
                  {causalLoading ? (
                    <div className="py-8 text-center font-mono text-xs text-[rgb(var(--muted))]">Loading causal chain...</div>
                  ) : causalData ? (
                    <div className="space-y-3">
                      {/* Decision */}
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

                      {/* Risk Check */}
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

                      {/* LLM Traces */}
                      {causalData.llm_traces && causalData.llm_traces.length > 0 ? (
                        <div className="border-l-2 border-[rgba(var(--info),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                          <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">LLM TRACES</div>
                          <div className="mt-2 space-y-3">
                            {causalData.llm_traces.map((trace, index) => (
                              <div key={index} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] p-3" style={{ borderRadius: '2px' }}>
                                <div className="flex items-center justify-between">
                                  <span className="font-mono text-xs font-bold text-[rgb(var(--text))]">{trace.agent}</span>
                                  {trace.created_at && (
                                    <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{new Date(trace.created_at * 1000).toLocaleString()}</span>
                                  )}
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

                      {/* Fills */}
                      <div className="border-l-2 border-[rgba(var(--accent),0.5)] bg-[rgba(var(--surface),0.3)] p-4" style={{ borderRadius: '2px' }}>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FILLS</div>
                        <div className="mt-2 space-y-1">
                          {causalData.fills.map((fill, index) => (
                            <div key={index} className="flex justify-between font-mono text-xs">
                              <span className="text-[rgb(var(--muted))]">FILL #{index + 1}</span>
                              <span className="tabular-nums text-[rgb(var(--text))]">
                                {fill.qty} @ {formatCurrency(fill.price)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="py-8 text-center font-mono text-xs text-[rgb(var(--muted))]">
                      UNABLE TO LOAD CAUSAL CHAIN
                    </div>
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

function Field({ label, value, highlight }) {
  const colorCls = highlight === 'up'
    ? 'text-[rgb(var(--up))]'
    : highlight === 'down'
      ? 'text-[rgb(var(--danger))]'
      : 'text-[rgb(var(--text))]'

  return (
    <div
      className="border-l-2 border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-3 py-2"
      style={{ borderRadius: '2px' }}
    >
      <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
      <div className={`mt-1 break-all font-mono text-sm font-semibold tabular-nums ${colorCls}`}>{value}</div>
    </div>
  )
}
