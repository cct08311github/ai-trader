import React, { useEffect, useMemo, useState } from 'react'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'
import { downloadTextFile, fetchTrades, fetchTradeCausalChain, mockTrades, tradesToCsv, tradesToExcelXml } from '../lib/trades'
import { authFetch, getApiBase } from '../lib/auth'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'

function toIsoDate(d) {
  if (!d) return ''
  // input[type=date] gives YYYY-MM-DD
  return `${d}T00:00:00Z`
}

function toIsoDateEnd(d) {
  if (!d) return ''
  return `${d}T23:59:59Z`
}

/** 將 ISO UTC 字串轉為 TWN (UTC+8) 可讀格式 */
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

/** Monthly Stats Summary — design doc §4.2 */
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
    { label: '本月成交金額', value: data ? formatCurrency(data.total_amount) : '-' },
    { label: '手續費+稅金', value: data ? formatCurrency(data.total_fee_tax) : '-' },
    { label: '勝率', value: data ? formatPercent(data.win_rate) : '-', good: data?.win_rate >= 0.5 },
    { label: '平均持倉天數', value: data ? `${Number(data.avg_holding_days).toFixed(1)} 天` : '-' },
    { label: '最大單筆獲利', value: data ? (data.max_profit != null ? formatCurrency(data.max_profit) : '-') : '-', good: true },
    { label: '最大單筆虧損', value: data ? (data.max_loss != null ? formatCurrency(data.max_loss) : '-') : '-', bad: true },
  ]

  return (
    <div className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/20 p-4 shadow-panel">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-200">月度統計摘要</div>
          <div className="text-xs text-slate-500 mt-0.5">設計書 §4.2 — 成交金額、費用、勝率、持倉天數</div>
        </div>
        <input
          type="month"
          value={month}
          onChange={e => setMonth(e.target.value)}
          className="rounded-xl border border-slate-700 bg-slate-950/60 px-3 py-1.5 text-sm text-slate-200 focus:border-emerald-500/50 focus:outline-none"
        />
      </div>
      {loading ? (
        <div className="text-xs text-slate-500 py-2">載入中…</div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {stats.map(s => (
            <div key={s.label} className="rounded-xl border border-slate-800 bg-slate-950/30 p-3">
              <div className="text-[11px] text-slate-400 mb-1">{s.label}</div>
              <div className={`text-sm font-bold ${s.good ? 'text-emerald-300' : s.bad ? 'text-rose-300' : 'text-slate-100'
                }`}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
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
  const [activeTab, setActiveTab] = useState('details') // 'details' or 'causal'

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
      // Do NOT fallback to mock — show real error so user knows data is unavailable
      setItems([])
      setTotal(0)
      setSource('error')
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

  async function handleTradeSelect(trade) {
    setSelected(trade)
    setActiveTab('details')
    setCausalData(null)

    // 加载因果链数据
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
    <div className="p-4 md:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-100">交易明細</h1>
        <div className="mt-1 text-sm text-slate-400">查看歷史交易記錄與決策因果鏈</div>
      </div>

      {/* Monthly Summary — design doc §4.2 */}
      <MonthlySummaryPanel />

      {/* Filters */}
      <div className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/20 p-4 shadow-panel">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Symbol</div>
            <input
              type="text"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="e.g. 2330"
              className="w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Type</div>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200"
            >
              <option value="">All</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">Start date</div>
            <input
              type="date"
              value={dateStart}
              onChange={(e) => setDateStart(e.target.value)}
              className="w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200"
            />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">End date</div>
            <input
              type="date"
              value={dateEnd}
              onChange={(e) => setDateEnd(e.target.value)}
              className="w-full rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm text-slate-200"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => load()}
              disabled={loading}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-900/30 disabled:opacity-50"
            >
              {loading ? '讀取中...' : '套用篩選'}
            </button>
            <button
              type="button"
              onClick={() => {
                setSymbol('')
                setType('')
                setDateStart('')
                setDateEnd('')
                setStatus('')
                setTimeout(() => load(), 0)
              }}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm text-slate-400 hover:bg-slate-900/30"
            >
              Clear
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={exportCsv}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm text-slate-400 hover:bg-slate-900/30"
            >
              CSV
            </button>
            <button
              type="button"
              onClick={exportExcel}
              className="rounded-xl border border-slate-800 bg-slate-900/10 px-4 py-2 text-sm text-slate-400 hover:bg-slate-900/30"
            >
              Excel
            </button>
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
                    onClick={() => handleTradeSelect(t)}
                  >
                    <td className="px-4 py-3 font-medium text-slate-100">{toTWN(t.timestamp)}</td>
                    <td className="px-4 py-3 text-slate-200">{formatSymbol(t.symbol, symbolNames)}</td>
                    <td className={`px-4 py-3 font-medium ${sideTone}`}>{String(t.action).toUpperCase()}</td>
                    <td className="px-4 py-3 text-right text-slate-200">
                      {formatNumber(qty, { maximumFractionDigits: 4 })}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-200">{formatCurrency(price)}</td>
                    <td className="px-4 py-3 text-right text-slate-200">{formatCurrency(amount)}</td>
                    <td className={`px-4 py-3 text-right font-medium ${t.pnl == null ? 'text-slate-500' : pnlTone}`}>
                      {t.pnl == null ? '-' : formatCurrency(pnl)}
                    </td>
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
            className="w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">交易详情 - {selected.symbol}</div>
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

            {/* Tabs */}
            <div className="mt-4 flex border-b border-slate-800">
              <button
                type="button"
                className={`px-4 py-2 text-sm font-medium ${activeTab === 'details' ? 'border-b-2 border-emerald-500 text-emerald-300' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setActiveTab('details')}
              >
                交易详情
              </button>
              <button
                type="button"
                className={`px-4 py-2 text-sm font-medium ${activeTab === 'causal' ? 'border-b-2 border-emerald-500 text-emerald-300' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setActiveTab('causal')}
              >
                决策因果链
              </button>
            </div>

            {/* Tab content */}
            <div className="mt-4">
              {activeTab === 'details' ? (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                  <Field label="Timestamp (TWN)" value={toTWN(selected.timestamp)} />
                  <Field label="Symbol" value={selected.symbol} />
                  <Field label="Side" value={String(selected.action).toUpperCase()} />
                  <Field label="Quantity" value={formatNumber(Number(selected.quantity || 0))} />
                  <Field label="Price" value={formatCurrency(Number(selected.price || 0))} />
                  <Field label="Amount" value={formatCurrency(Number(selected.amount ?? 0))} />
                  <Field label="PnL" value={selected.pnl == null ? '-' : formatCurrency(Number(selected.pnl))} />
                  <Field label="Fee" value={formatCurrency(Number(selected.fee || 0))} />
                  <Field label="Tax" value={formatCurrency(Number(selected.tax || 0))} />
                  <Field label="Status" value={selected.status || 'filled'} />
                  <Field label="Agent" value={selected.agent_id || '-'} />
                  <Field label="Decision" value={selected.decision_id || '-'} />
                </div>
              ) : (
                <div>
                  {causalLoading ? (
                    <div className="py-8 text-center text-slate-400">加载决策因果链中...</div>
                  ) : causalData ? (
                    <div className="space-y-4">
                      {/* 决策信息 */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4">
                        <div className="text-xs font-medium text-slate-400">决策信息</div>
                        <div className="mt-2 space-y-2">
                          <div className="flex justify-between">
                            <span className="text-sm text-slate-300">决策ID:</span>
                            <span className="text-sm text-slate-200">{causalData.decision.decision_id}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-sm text-slate-300">信号方向:</span>
                            <span className={`text-sm font-medium ${causalData.decision.signal_side === 'buy' ? 'text-emerald-300' : 'text-rose-300'}`}>
                              {causalData.decision.signal_side.toUpperCase()}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* 风控检查 */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4">
                        <div className="text-xs font-medium text-slate-400">风控检查</div>
                        <div className="mt-2">
                          <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ${causalData.risk_check.passed ? 'bg-emerald-900/30 text-emerald-300' : 'bg-rose-900/30 text-rose-300'}`}>
                            {causalData.risk_check.passed ? '✓ 通过' : '✗ 拒绝'}
                          </div>
                          {causalData.risk_check.reject_code && (
                            <div className="mt-2 text-sm text-slate-300">拒绝代码: {causalData.risk_check.reject_code}</div>
                          )}
                        </div>
                      </div>

                      {/* LLM Traces */}
                      {causalData.llm_traces && causalData.llm_traces.length > 0 ? (
                        <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4">
                          <div className="text-xs font-medium text-slate-400">LLM 决策轨迹</div>
                          <div className="mt-2 space-y-3">
                            {causalData.llm_traces.map((trace, index) => (
                              <div key={index} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
                                <div className="flex items-center justify-between">
                                  <span className="text-sm font-medium text-slate-200">{trace.agent}</span>
                                  {trace.created_at && (
                                    <span className="text-xs text-slate-500">{new Date(trace.created_at * 1000).toLocaleString()}</span>
                                  )}
                                </div>
                                <div className="mt-2">
                                  <div className="text-xs text-slate-400">Prompt:</div>
                                  <div className="mt-1 text-sm text-slate-300 overflow-auto max-h-20">{trace.prompt_text}</div>
                                </div>
                                <div className="mt-2">
                                  <div className="text-xs text-slate-400">Response:</div>
                                  <div className="mt-1 text-sm text-slate-300 overflow-auto max-h-20">{trace.response_text}</div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4">
                          <div className="text-center text-sm text-slate-400">无 LLM 决策轨迹记录</div>
                        </div>
                      )}

                      {/* 成交信息 */}
                      <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4">
                        <div className="text-xs font-medium text-slate-400">成交信息</div>
                        <div className="mt-2 space-y-2">
                          {causalData.fills.map((fill, index) => (
                            <div key={index} className="flex justify-between">
                              <span className="text-sm text-slate-300">成交 #{index + 1}:</span>
                              <span className="text-sm text-slate-200">
                                {fill.qty} @ {formatCurrency(fill.price)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="py-8 text-center text-slate-400">
                      无法加载决策因果链数据
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

function Field({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-3">
      <div className="text-xs font-medium text-slate-400">{label}</div>
      <div className="mt-1 text-sm text-slate-100 break-all">{value}</div>
    </div>
  )
}
