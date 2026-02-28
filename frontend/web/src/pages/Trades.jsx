import React, { useEffect, useMemo, useState } from 'react'
import { formatCurrency, formatNumber } from '../lib/format'
import { downloadTextFile, fetchTrades, mockTrades, tradesToCsv, tradesToExcelXml } from '../lib/trades'

function toIsoDate(d) {
  if (!d) return ''
  // input[type=date] gives YYYY-MM-DD
  return `${d}T00:00:00Z`
}

function toIsoDateEnd(d) {
  if (!d) return ''
  return `${d}T23:59:59Z`
}

export default function TradesPage() {
  const [items, setItems] = useState(mockTrades)
  const [total, setTotal] = useState(mockTrades.length)
  const [source, setSource] = useState('mock')

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
    const timeout = setTimeout(() => controller.abort(), 4000)

    try {
      const data = await fetchTrades({ ...query, signal: controller.signal })
      setItems(data.items)
      setTotal(data.total)
      setSource('api')
    } catch (e) {
      setItems(mockTrades)
      setTotal(mockTrades.length)
      setSource('mock')
      setError(String(e?.message || e))
    } finally {
      clearTimeout(timeout)
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    // MVP: try API first; fallback to mock
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold">交易明細 (Trades)</div>
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

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => load()}
            disabled={loading}
            className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2 text-sm text-slate-200 shadow-panel transition hover:bg-slate-900 disabled:opacity-50"
          >
            {loading ? 'Loading…' : 'Search'}
          </button>
          <button
            type="button"
            onClick={exportCsv}
            className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm text-slate-200 shadow-panel transition hover:bg-slate-900"
          >
            Export CSV
          </button>
          <button
            type="button"
            onClick={exportExcel}
            className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm text-slate-200 shadow-panel transition hover:bg-slate-900"
          >
            Export Excel
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-4 shadow-panel">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-6">
          <div className="md:col-span-2">
            <div className="text-xs font-medium text-slate-400">Date start</div>
            <input
              type="date"
              value={dateStart}
              onChange={(e) => setDateStart(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
          </div>
          <div className="md:col-span-2">
            <div className="text-xs font-medium text-slate-400">Date end</div>
            <input
              type="date"
              value={dateEnd}
              onChange={(e) => setDateEnd(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
          </div>
          <div className="md:col-span-1">
            <div className="text-xs font-medium text-slate-400">Symbol</div>
            <input
              type="text"
              placeholder="2330"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/40"
            />
          </div>
          <div className="md:col-span-1">
            <div className="text-xs font-medium text-slate-400">Type</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/40"
            >
              <option value="">All</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div className="md:col-span-1">
            <div className="text-xs font-medium text-slate-400">Status</div>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 outline-none focus:ring-2 focus:ring-emerald-500/40"
            >
              <option value="">All</option>
              <option value="filled">Filled</option>
            </select>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <div>
            Sorting: <span className="text-slate-200">{sortBy}</span> / <span className="text-slate-200">{sortDir}</span>
          </div>
          <div className="flex items-center gap-2">
            <div>Limit</div>
            <select
              value={limit}
              onChange={(e) => {
                setLimit(Number(e.target.value))
                setOffset(0)
              }}
              className="rounded-xl border border-slate-800 bg-slate-950/40 px-2 py-1 text-xs text-slate-200"
            >
              {[20, 50, 100, 200].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 shadow-panel">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="text-sm font-semibold">交易列表</div>
          <div className="text-xs text-slate-400">
            {formatNumber(total)} trades · offset {formatNumber(offset)}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">
                  <button type="button" className="hover:text-slate-200" onClick={() => toggleSort('time')}>
                    Time
                  </button>
                </th>
                <th className="px-4 py-3">Symbol</th>
                <th className="px-4 py-3">Side</th>
                <th className="px-4 py-3 text-right">Qty</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-right">
                  <button type="button" className="hover:text-slate-200" onClick={() => toggleSort('amount')}>
                    Amount
                  </button>
                </th>
                <th className="px-4 py-3 text-right">
                  <button type="button" className="hover:text-slate-200" onClick={() => toggleSort('pnl')}>
                    PnL
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {items.map((t) => {
                const qty = Number(t.quantity || 0)
                const price = Number(t.price || 0)
                const amount = Number(t.amount ?? qty * price)
                const pnl = Number(t.pnl || 0)
                const pnlTone = pnl >= 0 ? 'text-emerald-300' : 'text-rose-300'
                const sideTone = String(t.action).toLowerCase() === 'buy' ? 'text-emerald-200' : 'text-rose-200'

                return (
                  <tr
                    key={t.id}
                    className="cursor-pointer hover:bg-slate-900/40"
                    onClick={() => setSelected(t)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-100">{t.timestamp}</td>
                    <td className="px-4 py-3 text-slate-200">{t.symbol}</td>
                    <td className={`px-4 py-3 font-medium ${sideTone}`}>{String(t.action).toUpperCase()}</td>
                    <td className="px-4 py-3 text-right text-slate-200">
                      {formatNumber(qty, { maximumFractionDigits: 4 })}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200">{formatCurrency(price)}</td>
                    <td className="px-4 py-3 text-right text-slate-200">{formatCurrency(amount)}</td>
                    <td className={`px-4 py-3 text-right font-medium ${pnlTone}`}>{formatCurrency(pnl)}</td>
                  </tr>
                )
              })}

              {items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-400">
                    No trades.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between border-t border-slate-800 px-4 py-3">
          <div className="text-xs text-slate-400">
            Page: {Math.floor(offset / limit) + 1} / {Math.max(1, Math.ceil(total / limit))}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canPrev}
              onClick={() => {
                setOffset((o) => Math.max(0, o - limit))
                setTimeout(() => load({ silent: true }), 0)
              }}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={!canNext}
              onClick={() => {
                setOffset((o) => o + limit)
                setTimeout(() => load({ silent: true }), 0)
              }}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-3 py-1.5 text-sm text-slate-200 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </div>

      {/* Detail modal */}
      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setSelected(null)}>
          <div
            className="w-full max-w-2xl rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">Trade detail</div>
                <div className="mt-1 text-xs text-slate-400">{selected.id}</div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                className="rounded-xl border border-slate-800 bg-slate-900/10 px-3 py-1.5 text-sm text-slate-200"
              >
                Close
              </button>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
              <Field label="Timestamp" value={selected.timestamp} />
              <Field label="Symbol" value={selected.symbol} />
              <Field label="Side" value={String(selected.action).toUpperCase()} />
              <Field label="Quantity" value={formatNumber(Number(selected.quantity || 0))} />
              <Field label="Price" value={formatCurrency(Number(selected.price || 0))} />
              <Field label="Amount" value={formatCurrency(Number(selected.amount ?? 0))} />
              <Field label="PnL" value={formatCurrency(Number(selected.pnl || 0))} />
              <Field label="Fee" value={formatCurrency(Number(selected.fee || 0))} />
              <Field label="Tax" value={formatCurrency(Number(selected.tax || 0))} />
              <Field label="Status" value={selected.status || 'filled'} />
              <Field label="Agent" value={selected.agent_id || '-'} />
              <Field label="Decision" value={selected.decision_id || '-'} />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-3">
      <div className="text-xs font-medium text-slate-400">{label}</div>
      <div className="mt-1 text-sm text-slate-100 break-all">{value}</div>
    </div>
  )
}
