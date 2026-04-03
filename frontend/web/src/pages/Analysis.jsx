/**
 * Analysis.jsx -- BattleTheme Redesign
 *
 * Post-market analysis war room: market overview, technical
 * indicators, institutional flows, AI strategy recommendations.
 * Brutalist panels, monospace labels, status dots, accent borders.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { getToken, authFetch, getApiBase } from '../lib/auth'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import KlineChart from '../components/KlineChart'
import { FileText } from 'lucide-react'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'

const TABS = ['MARKET OVERVIEW', 'TECHNICAL ANALYSIS', 'INSTITUTIONAL FLOWS', 'AI STRATEGY']

/* ── Panel wrapper (brutalist) ─────────────────────────────── */
function Panel({ title, right, children, className = '', accent }) {
  return (
    <section
      className={`border border-[rgba(var(--grid),0.3)] ${accent ? `border-l-2 border-l-[rgba(var(--accent),0.5)]` : ''} bg-[rgba(var(--surface),0.6)] ${className}`}
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

function SentimentBadge({ sentiment }) {
  const map = {
    bullish: ['BULLISH', 'text-[rgb(var(--up))]', 'bg-[rgb(var(--up))]'],
    bearish: ['BEARISH', 'text-[rgb(var(--danger))]', 'bg-[rgb(var(--danger))]'],
    neutral: ['NEUTRAL', 'text-[rgb(var(--muted))]', 'bg-[rgb(var(--muted))]']
  }
  const [label, textCls, dotCls] = map[sentiment] || ['UNKNOWN', 'text-[rgb(var(--muted))]', 'bg-[rgb(var(--muted))]']
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${dotCls}`} />
      <span className={`font-mono text-xs font-bold uppercase tracking-widest ${textCls}`}>{label}</span>
    </span>
  )
}

/* ── Market Overview Tab ───────────────────────────────────── */
function MarketOverviewTab({ report }) {
  const { market_summary } = report
  const topMovers = market_summary?.top_movers || []
  const instFlows = market_summary?.institution_flows || []

  return (
    <div className="space-y-4">
      <Panel title="MARKET SENTIMENT" accent>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">TODAY:</span>
          <SentimentBadge sentiment={market_summary?.sentiment} />
        </div>
      </Panel>

      <Panel title="TOP MOVERS">
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr className="border-b border-[rgba(var(--grid),0.15)]">
                <th className="text-left py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CODE</th>
                <th className="text-left py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">NAME</th>
                <th className="text-right py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CLOSE</th>
                <th className="text-right py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CHG</th>
              </tr>
            </thead>
            <tbody>
              {topMovers.map(r => (
                <tr key={r.symbol} className="border-b border-[rgba(var(--grid),0.08)]">
                  <td className="py-2 pr-3 font-bold text-[rgb(var(--text))]">{r.symbol}</td>
                  <td className="py-2 pr-3 text-[rgb(var(--muted))]">{r.name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-[rgb(var(--text))]">{r.close?.toFixed(1)}</td>
                  <td className={`py-2 text-right tabular-nums font-bold ${(r.change||0) >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                    {(r.change||0) >= 0 ? '+' : ''}{r.change?.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {instFlows.length > 0 && (
        <Panel title="INSTITUTIONAL FLOWS (10K TWD)">
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs" style={{ borderCollapse: 'collapse' }}>
              <thead>
                <tr className="border-b border-[rgba(var(--grid),0.15)]">
                  <th className="text-left py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CODE</th>
                  <th className="text-right py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">FOREIGN</th>
                  <th className="text-right py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">TRUST</th>
                  <th className="text-right py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">DEALER</th>
                </tr>
              </thead>
              <tbody>
                {instFlows.map(r => (
                  <tr key={r.symbol} className="border-b border-[rgba(var(--grid),0.08)]">
                    <td className="py-2 pr-3 font-bold text-[rgb(var(--text))]">{r.symbol}</td>
                    <td className={`py-2 pr-3 text-right tabular-nums ${(r.foreign_net||0) >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                      {((r.foreign_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-2 pr-3 text-right tabular-nums ${(r.investment_trust_net||0) >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                      {((r.investment_trust_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-2 text-right tabular-nums ${(r.dealer_net||0) >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                      {((r.dealer_net||0)/10000).toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}

/* ── Stock Chips Panel ─────────────────────────────────────── */
const fmtShares = v => (v == null ? '--' : (v / 10000).toFixed(1))
const fmtLots = v => (v == null ? '--' : Number(v).toLocaleString())
const netCls = v => (v == null || v >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]')

function StockChipsPanel({ symbol }) {
  const [data, setData] = useState(null)
  const [chipsDate, setChipsDate] = useState(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    if (!symbol) return
    setLoading(true); setData(null); setMsg(null)
    authFetch(`${getApiBase()}/api/chips/dates`)
      .then(r => r.json())
      .then(d => {
        const date = d.dates?.[0]
        if (!date) { setMsg('No chip data'); setLoading(false); return null }
        setChipsDate(date)
        return authFetch(`${getApiBase()}/api/chips/${date}/summary?symbol=${symbol.toUpperCase()}`)
      })
      .then(r => {
        if (!r) return
        if (r.status === 404) { setMsg('No chip data for this stock'); setLoading(false); return null }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { if (d) { setData(d.data?.[0] ?? null); setLoading(false) } })
      .catch(e => { setMsg(String(e?.message || e)); setLoading(false) })
  }, [symbol])

  if (!symbol) return null
  if (loading) return <div className="py-8"><LoadingSpinner label="Loading chip data..." /></div>
  if (msg || !data) return (
    <div className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] px-4 py-3 font-mono text-xs text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>
      {msg || 'No chip data'}
    </div>
  )

  return (
    <Panel title={`INSTITUTIONAL CHIPS (${chipsDate})`}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 font-mono text-xs">
        {[
          ['FOREIGN', data.foreign_net],
          ['TRUST', data.trust_net],
          ['DEALER', data.dealer_net],
          ['TOTAL', data.total_net],
        ].map(([label, val]) => (
          <div key={label} className="border-l-2 border-l-[rgba(var(--grid),0.2)] pl-3">
            <div className="text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
            <div className={`mt-0.5 font-bold tabular-nums ${netCls(val)}`}>
              {fmtShares(val)} 10K
            </div>
          </div>
        ))}
      </div>
      {(data.margin_balance != null || data.short_balance != null) && (
        <div className="mt-3 flex gap-6 font-mono text-xs">
          <div>
            <span className="text-[rgb(var(--muted))]">MARGIN: </span>
            <span className="tabular-nums text-[rgb(var(--info))]">{fmtLots(data.margin_balance)}</span>
          </div>
          <div>
            <span className="text-[rgb(var(--muted))]">SHORT: </span>
            <span className="tabular-nums text-[rgb(var(--warn))]">{fmtLots(data.short_balance)}</span>
          </div>
        </div>
      )}
    </Panel>
  )
}

/* ── Technical Tab ──────────────────────────────────────────── */
function TechnicalTab({ report }) {
  const technical = report.technical || {}
  const symbols = Object.keys(technical)
  const [selected, setSelected] = useState(symbols[0] || '')
  const [searchInput, setSearchInput] = useState('')
  const symbolNames = useSymbolNames()
  const sym = technical[selected]

  const handleSearch = () => {
    const code = searchInput.trim().split(/\s+/)[0].toUpperCase()
    if (code) { setSelected(code); setSearchInput('') }
  }

  // RSI color coding
  const rsiColor = (v) => {
    if (v == null) return 'text-[rgb(var(--text))]'
    if (v >= 70) return 'text-[rgb(var(--danger))]'
    if (v <= 30) return 'text-[rgb(var(--up))]'
    return 'text-[rgb(var(--text))]'
  }

  return (
    <div className="space-y-4">
      {/* Symbol selector */}
      <div className="flex flex-wrap gap-2">
        {symbols.map(s => (
          <button key={s}
            onClick={() => { setSelected(s); setSearchInput('') }}
            className={`px-3 py-1 font-mono text-xs transition-colors ${
              selected === s && !searchInput
                ? 'border border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.1)] text-[rgb(var(--accent))] font-bold'
                : 'border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
            }`}
            style={{ borderRadius: '3px' }}
          >{formatSymbol(s, symbolNames)}</button>
        ))}
      </div>

      {/* Search */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Query stock (e.g. 2330)"
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          className="flex-1 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-1.5 font-mono text-sm text-[rgb(var(--text))] outline-none focus:border-[rgba(var(--accent),0.5)] placeholder:text-[rgb(var(--muted))]"
          style={{ borderRadius: '3px' }}
        />
        <button onClick={handleSearch}
          className="border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-4 py-1.5 font-mono text-xs font-bold text-[rgb(var(--accent))] hover:bg-[rgba(var(--accent),0.15)]"
          style={{ borderRadius: '3px' }}
        >QUERY</button>
      </div>

      {selected && (
        <>
          <div className="flex items-baseline gap-2 border-b border-[rgba(var(--grid),0.3)] pb-2">
            <span className="font-mono text-lg font-bold text-[rgb(var(--text))]">{selected}</span>
            {symbolNames?.[selected] && (
              <span className="font-mono text-sm text-[rgb(var(--muted))]">{symbolNames[selected]}</span>
            )}
          </div>

          <KlineChart symbol={selected} />

          {sym && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {[
                ['CLOSE', sym.close, null],
                ['MA5', sym.ma5, null],
                ['MA20', sym.ma20, null],
                ['MA60', sym.ma60, null],
                ['RSI14', sym.rsi14?.toFixed(1), rsiColor(sym.rsi14)],
                ['MACD', sym.macd?.macd?.toFixed(2), null],
                ['SIGNAL', sym.macd?.signal?.toFixed(2), null],
                ['SUPPORT', sym.support, null],
                ['RESISTANCE', sym.resistance, null],
              ].map(([label, value, colorOverride]) => (
                <div key={label}
                  className="border-l-2 border-l-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-3 py-2"
                  style={{ borderRadius: '2px' }}
                >
                  <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
                  <div className={`mt-1 font-mono text-sm font-bold tabular-nums ${colorOverride || 'text-[rgb(var(--text))]'}`}>
                    {value ?? '--'}
                  </div>
                  {/* RSI zone indicator */}
                  {label === 'RSI14' && sym.rsi14 != null && (
                    <div className="mt-0.5 font-mono text-[9px] text-[rgb(var(--muted))]">
                      {sym.rsi14 >= 70 ? 'OVERBOUGHT' : sym.rsi14 <= 30 ? 'OVERSOLD' : 'NEUTRAL'}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <StockChipsPanel symbol={selected} />
        </>
      )}
    </div>
  )
}

/* ── Chips Tab ──────────────────────────────────────────────── */
function ChipsTab({ report }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const symbolNames = useSymbolNames()
  const tradeDate = report?.trade_date

  useEffect(() => {
    if (!tradeDate) { setError('No institutional data today'); setLoading(false); return }
    setLoading(true); setError(null)
    fetch(`${getApiBase()}/api/chips/${tradeDate}/summary`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then(r => {
        if (r.status === 404) { setError('No institutional data today'); setLoading(false); return null }
        if (!r.ok) throw new Error(`Cannot load chip data (HTTP ${r.status})`)
        return r.json()
      })
      .then(d => { if (d) { setData(d); setLoading(false) } })
      .catch(() => { setError('Cannot load chip data'); setLoading(false) })
  }, [tradeDate])

  if (loading) return <div className="py-8"><LoadingSpinner label="Loading chip data..." /></div>
  if (error) return <ErrorState message="Failed to load institutional data" description={error} />
  if (!data?.data?.length) return <EmptyState icon={FileText} title="NO DATA" description="Updated after market close daily" />

  const rows = data.data
  const hasMargin = rows.some(r => r.margin_balance != null)

  return (
    <div className="space-y-4">
      <Panel title="INSTITUTIONAL NET BUY/SELL (10K SHARES)">
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs" style={{ borderCollapse: 'collapse' }}>
            <thead>
              <tr className="border-b border-[rgba(var(--grid),0.15)]">
                {['CODE', 'FOREIGN', 'TRUST', 'DEALER', 'TOTAL'].map(h => (
                  <th key={h} className={`py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] ${h !== 'CODE' ? 'text-right' : 'text-left'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.symbol} className="border-b border-[rgba(var(--grid),0.08)]">
                  <td className="py-2 pr-3 font-bold text-[rgb(var(--text))]">{formatSymbol(r.symbol, symbolNames || {})}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${netCls(r.foreign_net)}`}>{fmtShares(r.foreign_net)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${netCls(r.trust_net)}`}>{fmtShares(r.trust_net)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${netCls(r.dealer_net)}`}>{fmtShares(r.dealer_net)}</td>
                  <td className={`py-2 text-right tabular-nums font-bold ${netCls(r.total_net)}`}>{fmtShares(r.total_net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {hasMargin && (
        <Panel title="MARGIN / SHORT BALANCE (LOTS)">
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs" style={{ borderCollapse: 'collapse' }}>
              <thead>
                <tr className="border-b border-[rgba(var(--grid),0.15)]">
                  <th className="text-left py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CODE</th>
                  <th className="text-right py-2 pr-3 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">MARGIN</th>
                  <th className="text-right py-2 text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">SHORT</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.symbol} className="border-b border-[rgba(var(--grid),0.08)]">
                    <td className="py-2 pr-3 font-bold text-[rgb(var(--text))]">{formatSymbol(r.symbol, symbolNames || {})}</td>
                    <td className="py-2 pr-3 text-right tabular-nums text-[rgb(var(--info))]">{fmtLots(r.margin_balance)}</td>
                    <td className="py-2 text-right tabular-nums text-[rgb(var(--warn))]">{fmtLots(r.short_balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  )
}

/* ── Strategy Tab ──────────────────────────────────────────── */
function StrategyTab({ report }) {
  const strategy = report.strategy || {}
  const outlook = strategy.market_outlook || {}
  const actions = strategy.position_actions || []
  const opportunities = strategy.watchlist_opportunities || []
  const risks = strategy.risk_notes || []
  const symbolNames = useSymbolNames()

  return (
    <div className="space-y-4">
      <Panel title="MARKET OUTLOOK" accent>
        <p className="font-mono text-xs leading-relaxed text-[rgb(var(--text))]">{strategy.summary || '--'}</p>
        {outlook.sector_focus?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {outlook.sector_focus.map(s => (
              <span key={s} className="border border-[rgba(var(--accent),0.3)] bg-[rgba(var(--accent),0.08)] px-2 py-0.5 font-mono text-[10px] text-[rgb(var(--accent))]" style={{ borderRadius: '2px' }}>{s}</span>
            ))}
          </div>
        )}
      </Panel>

      {actions.length > 0 && (
        <Panel title="POSITION ACTIONS">
          {actions.map(a => (
            <div key={a.symbol} className="border-b border-[rgba(var(--grid),0.1)] py-3 last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold text-[rgb(var(--text))]">{formatSymbol(a.symbol, symbolNames)}</span>
                <span className={`border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
                  a.action === 'hold' ? 'border-[rgba(var(--grid),0.3)] text-[rgb(var(--muted))]' :
                  a.action === 'reduce' ? 'border-[rgba(var(--warn),0.3)] text-[rgb(var(--warn))]' :
                  'border-[rgba(var(--danger),0.3)] text-[rgb(var(--danger))]'
                }`} style={{ borderRadius: '2px' }}>{a.action}</span>
              </div>
              <p className="mt-1 font-mono text-[11px] text-[rgb(var(--muted))]">{a.reason}</p>
            </div>
          ))}
        </Panel>
      )}

      {opportunities.length > 0 && (
        <Panel title="WATCHLIST OPPORTUNITIES">
          {opportunities.map(o => (
            <div key={o.symbol} className="border-b border-[rgba(var(--grid),0.1)] py-3 last:border-0">
              <span className="font-mono text-sm font-bold text-[rgb(var(--text))]">{formatSymbol(o.symbol, symbolNames)}</span>
              <p className="font-mono text-[11px] text-[rgb(var(--muted))]">{o.entry_condition}</p>
              {o.stop_loss && <p className="font-mono text-[11px] text-[rgb(var(--danger))]">STOP: {o.stop_loss}</p>}
            </div>
          ))}
        </Panel>
      )}

      {risks.length > 0 && (
        <Panel title="RISK NOTES">
          <ul className="space-y-1">
            {risks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 font-mono text-xs text-[rgb(var(--warn))]">
                <span className="mt-0.5 shrink-0 h-1.5 w-1.5 rounded-full bg-[rgb(var(--warn))]" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}

/* ── Main Page ─────────────────────────────────────────────── */
export default function AnalysisPage() {
  const [activeTab, setActiveTab] = useState(0)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [noData, setNoData] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null); setNoData(false)
    try {
      const r = await fetch(`${getApiBase()}/api/analysis/latest`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.status === 404) { setNoData(true); return }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setReport(await r.json())
    } catch (e) { setError(String(e?.message || e)) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-4 pb-20 lg:pb-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-bold tracking-tight text-[rgb(var(--text))]">POST-MARKET ANALYSIS</h1>
          <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
            TECHNICAL + INSTITUTIONAL + AI STRATEGY
          </p>
        </div>
        {report && (
          <span className="font-mono text-[10px] text-[rgb(var(--muted))]">DATE: {report.trade_date}</span>
        )}
      </div>

      {/* States */}
      {loading && <div className="py-4"><LoadingSpinner label="Loading..." /></div>}
      {noData && !loading && (
        <div className="border-l-2 border-l-[rgb(var(--info))] bg-[rgba(var(--surface),0.3)] p-6 text-center font-mono text-xs text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>
          Post-market analysis not yet generated (auto-runs at 22:00 on trading days)
        </div>
      )}
      {error && (
        <div className="border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] p-4 font-mono text-xs text-[rgb(var(--danger))]" style={{ borderRadius: '2px' }}>
          Cannot load analysis: {error}
        </div>
      )}

      {report && !loading && (
        <>
          {/* Tab bar */}
          <div className="flex gap-1 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] p-1" style={{ borderRadius: '3px' }}>
            {TABS.map((tab, i) => (
              <button key={tab} onClick={() => setActiveTab(i)}
                className={`flex-1 py-1.5 font-mono text-[10px] font-bold uppercase tracking-widest transition-colors ${
                  activeTab === i
                    ? 'bg-[rgba(var(--accent),0.15)] text-[rgb(var(--accent))]'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
                style={{ borderRadius: '2px' }}
              >{tab}</button>
            ))}
          </div>

          {activeTab === 0 && <MarketOverviewTab report={report} />}
          {activeTab === 1 && <TechnicalTab report={report} />}
          {activeTab === 2 && <ChipsTab report={report} />}
          {activeTab === 3 && <StrategyTab report={report} />}
        </>
      )}
    </div>
  )
}
