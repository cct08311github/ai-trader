/**
 * Analysis.jsx -- Intelligence Dashboard Layout
 *
 * Complete layout restructure:
 *   Hero: Full-width K-line chart area
 *   Left sidebar (3 cols): Indicator readings with color-coded gauges
 *   Right content (9 cols): AI strategy recommendation as briefing document
 *   Bottom: Institutional flow heatmap grid (foreign/trust/dealer x buy/sell)
 *
 * All data fetching and state management preserved from original.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { getToken, authFetch, getApiBase } from '../lib/auth'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import KlineChart from '../components/KlineChart'
import { FileText, ChevronDown, ChevronRight } from 'lucide-react'
import LoadingSpinner from '../components/LoadingSpinner'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import EconomicCalendar from '../components/EconomicCalendar'

/* ── Sentiment Badge ──────────────────────────────────────── */
function SentimentBadge({ sentiment }) {
  const map = {
    bullish: ['BULLISH', '--up'],
    bearish: ['BEARISH', '--danger'],
    neutral: ['NEUTRAL', '--muted']
  }
  const [label, colorVar] = map[sentiment] || ['UNKNOWN', '--muted']
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: `rgb(var(${colorVar}))`, boxShadow: `0 0 6px rgba(var(${colorVar}),0.4)` }} />
      <span className="font-mono text-xs font-black uppercase tracking-widest" style={{ color: `rgb(var(${colorVar}))` }}>{label}</span>
    </span>
  )
}

/* ── RSI Bar Gauge ────────────────────────────────────────── */
function RsiGauge({ value }) {
  if (value == null) return <span className="font-mono text-sm text-[rgb(var(--muted))]">--</span>
  const pct = Math.min(100, Math.max(0, value))
  const color = value >= 70 ? '--danger' : value <= 30 ? '--up' : '--text'
  const zone = value >= 70 ? 'OVERBOUGHT' : value <= 30 ? 'OVERSOLD' : 'NEUTRAL'

  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between">
        <span className="font-mono text-lg font-black tabular-nums" style={{ color: `rgb(var(${color}))` }}>{value.toFixed(1)}</span>
        <span className="font-mono text-[9px] uppercase tracking-widest" style={{ color: `rgb(var(${color}))` }}>{zone}</span>
      </div>
      <div className="relative h-2 w-full bg-[rgba(var(--grid),0.15)] overflow-hidden" style={{ borderRadius: '1px' }}>
        {/* Overbought zone marker */}
        <div className="absolute right-0 top-0 bottom-0 w-[30%] bg-[rgba(var(--danger),0.08)]" />
        {/* Oversold zone marker */}
        <div className="absolute left-0 top-0 bottom-0 w-[30%] bg-[rgba(var(--up),0.08)]" />
        {/* Indicator */}
        <div className="absolute top-0 bottom-0 w-1 transition-all" style={{
          left: `${pct}%`,
          backgroundColor: `rgb(var(${color}))`,
          boxShadow: `0 0 4px rgba(var(${color}),0.5)`,
          borderRadius: '1px',
        }} />
      </div>
    </div>
  )
}

/* ── MACD Mini Histogram ──────────────────────────────────── */
function MacdMini({ macd }) {
  if (!macd) return <span className="font-mono text-sm text-[rgb(var(--muted))]">--</span>
  const hist = (macd.macd || 0) - (macd.signal || 0)
  const isPositive = hist >= 0

  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-3">
        <div>
          <div className="font-mono text-[9px] text-[rgb(var(--muted))]">MACD</div>
          <div className="font-mono text-sm font-bold tabular-nums text-[rgb(var(--text))]">{macd.macd?.toFixed(2) ?? '--'}</div>
        </div>
        <div>
          <div className="font-mono text-[9px] text-[rgb(var(--muted))]">SIGNAL</div>
          <div className="font-mono text-sm tabular-nums text-[rgb(var(--text))]">{macd.signal?.toFixed(2) ?? '--'}</div>
        </div>
      </div>
      {/* Mini bar */}
      <div className="flex items-center gap-1">
        <div className="flex-1 h-3 flex items-end justify-center bg-[rgba(var(--grid),0.1)] overflow-hidden" style={{ borderRadius: '1px' }}>
          <div className="w-3 transition-all" style={{
            height: `${Math.min(100, Math.abs(hist) * 10)}%`,
            minHeight: '2px',
            backgroundColor: isPositive ? 'rgb(var(--up))' : 'rgb(var(--danger))',
          }} />
        </div>
        <span className={`font-mono text-[10px] font-bold tabular-nums ${isPositive ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
          {hist >= 0 ? '+' : ''}{hist.toFixed(2)}
        </span>
      </div>
    </div>
  )
}

/* ── MA Crossover Status ──────────────────────────────────── */
function MaCrossover({ ma5, ma20, ma60 }) {
  const bullish = ma5 != null && ma20 != null && ma5 > ma20
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${bullish ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--danger))]'}`}
              style={{ boxShadow: `0 0 6px ${bullish ? 'rgba(var(--up),0.4)' : 'rgba(var(--danger),0.4)'}` }} />
        <span className={`font-mono text-[10px] font-bold uppercase ${bullish ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
          {bullish ? 'BULLISH CROSS' : 'BEARISH CROSS'}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 font-mono text-[10px]">
        {[['MA5', ma5], ['MA20', ma20], ['MA60', ma60]].map(([label, val]) => (
          <div key={label}>
            <div className="text-[rgb(var(--muted))]">{label}</div>
            <div className="font-bold tabular-nums text-[rgb(var(--text))]">{val ?? '--'}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Classification Label ─────────────────────────────────── */
function ClassificationLabel({ classification }) {
  const map = {
    STRONG_BUY: { color: '--up', glow: true },
    BUY: { color: '--up', glow: false },
    HOLD: { color: '--warn', glow: false },
    SELL: { color: '--danger', glow: false },
    STRONG_SELL: { color: '--danger', glow: true },
  }
  const cls = String(classification || 'HOLD').toUpperCase().replace(' ', '_')
  const config = map[cls] || map.HOLD

  return (
    <div className="inline-flex items-center gap-3 border-2 px-5 py-3"
         style={{
           borderColor: `rgb(var(${config.color}))`,
           backgroundColor: `rgba(var(${config.color}),0.08)`,
           borderRadius: '3px',
           boxShadow: config.glow ? `0 0 16px rgba(var(${config.color}),0.3)` : 'none',
         }}>
      <span className="font-mono text-2xl font-black uppercase tracking-tight"
            style={{ color: `rgb(var(${config.color}))` }}>
        {cls.replace('_', ' ')}
      </span>
    </div>
  )
}

/* ── Stock Chips Panel ────────────────────────────────────── */
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
  if (loading) return <div className="py-4"><LoadingSpinner label="Loading chip data..." /></div>
  if (msg || !data) return (
    <div className="font-mono text-[10px] text-[rgb(var(--muted))] py-2">{msg || 'No chip data'}</div>
  )

  return (
    <div className="space-y-2">
      <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">INSTITUTIONAL CHIPS ({chipsDate})</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[['FOREIGN', data.foreign_net], ['TRUST', data.trust_net], ['DEALER', data.dealer_net], ['TOTAL', data.total_net]].map(([label, val]) => (
          <div key={label} className="border-l-2 border-l-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.2)] pl-3 py-2">
            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</div>
            <div className={`mt-0.5 font-mono text-sm font-bold tabular-nums ${netCls(val)}`}>{fmtShares(val)} 10K</div>
          </div>
        ))}
      </div>
      {(data.margin_balance != null || data.short_balance != null) && (
        <div className="flex gap-4 font-mono text-[10px]">
          <span><span className="text-[rgb(var(--muted))]">MARGIN:</span> <span className="tabular-nums text-[rgb(var(--info))]">{fmtLots(data.margin_balance)}</span></span>
          <span><span className="text-[rgb(var(--muted))]">SHORT:</span> <span className="tabular-nums text-[rgb(var(--warn))]">{fmtLots(data.short_balance)}</span></span>
        </div>
      )}
    </div>
  )
}

/* ── Institutional Flow Heatmap ───────────────────────────── */
function InstitutionalHeatmap({ flows }) {
  if (!flows || flows.length === 0) return null

  const maxAbs = Math.max(1, ...flows.flatMap(r => [
    Math.abs(r.foreign_net || 0), Math.abs(r.investment_trust_net || 0), Math.abs(r.dealer_net || 0)
  ]))

  function cellStyle(val) {
    if (val == null) return {}
    const intensity = Math.min(1, Math.abs(val) / maxAbs)
    const colorVar = val >= 0 ? '--up' : '--danger'
    return {
      backgroundColor: `rgba(var(${colorVar}),${0.05 + intensity * 0.3})`,
      borderLeft: `2px solid rgba(var(${colorVar}),${0.2 + intensity * 0.6})`,
    }
  }

  return (
    <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] overflow-hidden" style={{ borderRadius: '4px' }}>
      <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">INSTITUTIONAL FLOW HEATMAP</span>
        <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{flows.length} STOCKS</span>
      </div>
      <div className="overflow-x-auto p-3">
        <div className="grid gap-1" style={{ gridTemplateColumns: `120px repeat(3, 1fr)` }}>
          {/* Header */}
          <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] py-2">STOCK</div>
          {['FOREIGN', 'TRUST', 'DEALER'].map(h => (
            <div key={h} className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] text-center py-2">{h}</div>
          ))}
          {/* Rows */}
          {flows.map(r => (
            <React.Fragment key={r.symbol}>
              <div className="font-mono text-xs font-bold text-[rgb(var(--text))] py-2 px-2">{r.symbol}</div>
              {[r.foreign_net, r.investment_trust_net, r.dealer_net].map((val, i) => (
                <div key={i} className="py-2 px-3 text-center" style={{ ...cellStyle(val), borderRadius: '2px' }}>
                  <span className={`font-mono text-xs font-bold tabular-nums ${netCls(val)}`}>
                    {val != null ? `${val >= 0 ? '+' : ''}${((val || 0) / 10000).toFixed(0)}` : '--'}
                  </span>
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  )
}

/* ── Full-width Chips Table ───────────────────────────────── */
function ChipsFullTable({ report }) {
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

  if (loading) return <div className="py-4"><LoadingSpinner label="Loading chip data..." /></div>
  if (error) return null
  if (!data?.data?.length) return null

  return <InstitutionalHeatmap flows={data.data.map(r => ({
    symbol: formatSymbol(r.symbol, symbolNames || {}),
    foreign_net: r.foreign_net,
    investment_trust_net: r.trust_net,
    dealer_net: r.dealer_net,
  }))} />
}

/* ══════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════ */
export default function AnalysisPage() {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [noData, setNoData] = useState(false)
  const [selectedSymbol, setSelectedSymbol] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const symbolNames = useSymbolNames()

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

  // Derive technical data for the selected symbol
  const technical = report?.technical || {}
  const symbols = Object.keys(technical)

  useEffect(() => {
    if (symbols.length > 0 && !selectedSymbol) setSelectedSymbol(symbols[0])
  }, [symbols.length])

  const sym = technical[selectedSymbol]
  const strategy = report?.strategy || {}
  const outlook = strategy.market_outlook || {}
  const actions = strategy.position_actions || []
  const opportunities = strategy.watchlist_opportunities || []
  const risks = strategy.risk_notes || []
  const instFlows = report?.market_summary?.institution_flows || []

  const handleSearch = () => {
    const code = searchInput.trim().split(/\s+/)[0].toUpperCase()
    if (code) { setSelectedSymbol(code); setSearchInput('') }
  }

  return (
    <div className="space-y-4 pb-20 lg:pb-4">

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
          {/* ══════════════════════════════════════════════════════════
              HERO: Full-width chart with sentiment overlay
              ══════════════════════════════════════════════════════════ */}
          <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] overflow-hidden" style={{ borderRadius: '4px' }}>
            <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-3">
              <div className="flex items-center gap-4">
                <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">INTELLIGENCE DASHBOARD</span>
                <SentimentBadge sentiment={report.market_summary?.sentiment} />
                {report.trade_date && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{report.trade_date}</span>}
              </div>
              {/* Symbol selector + search */}
              <div className="flex items-center gap-2">
                <div className="flex flex-wrap gap-1">
                  {symbols.slice(0, 6).map(s => (
                    <button key={s} onClick={() => { setSelectedSymbol(s); setSearchInput('') }}
                      className={`px-2.5 py-1 font-mono text-[10px] font-bold transition-colors ${
                        selectedSymbol === s
                          ? 'border border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.12)] text-[rgb(var(--accent))]'
                          : 'border border-[rgba(var(--grid),0.3)] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                      }`} style={{ borderRadius: '2px' }}
                    >{formatSymbol(s, symbolNames)}</button>
                  ))}
                </div>
                <input type="text" placeholder="Stock" value={searchInput}
                  onChange={e => setSearchInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSearch()}
                  className="w-20 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-2 py-1 font-mono text-[10px] text-[rgb(var(--text))] placeholder:text-[rgb(var(--muted))] focus:outline-none"
                  style={{ borderRadius: '2px' }} />
              </div>
            </div>
            {/* K-line chart */}
            <div className="p-3">
              {selectedSymbol && <KlineChart symbol={selectedSymbol} />}
            </div>
          </div>

          {/* ══════════════════════════════════════════════════════════
              BATTLE LAYOUT -- asymmetric 3:9 split
              Left: Indicator readings
              Right: AI strategy briefing
              ══════════════════════════════════════════════════════════ */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">

            {/* ── LEFT SIDEBAR: Indicator Readings ──────────── */}
            <div className="lg:col-span-3 space-y-4">
              <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] px-1">
                TECHNICAL INDICATORS
                {selectedSymbol && <span className="ml-2 text-[rgb(var(--text))]">{selectedSymbol}</span>}
              </div>

              {sym ? (
                <>
                  {/* Close price -- prominent */}
                  <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
                    <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CLOSE</div>
                    <div className="mt-1 font-mono text-2xl font-black tabular-nums text-[rgb(var(--text))]">{sym.close ?? '--'}</div>
                  </div>

                  {/* RSI gauge */}
                  <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
                    <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">RSI (14)</div>
                    <RsiGauge value={sym.rsi14} />
                  </div>

                  {/* MACD */}
                  <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
                    <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">MACD</div>
                    <MacdMini macd={sym.macd} />
                  </div>

                  {/* MA crossover */}
                  <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
                    <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">MOVING AVERAGES</div>
                    <MaCrossover ma5={sym.ma5} ma20={sym.ma20} ma60={sym.ma60} />
                  </div>

                  {/* Support/Resistance */}
                  <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3" style={{ borderRadius: '2px' }}>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">SUPPORT</div>
                        <div className="mt-1 font-mono text-sm font-bold tabular-nums text-[rgb(var(--up))]">{sym.support ?? '--'}</div>
                      </div>
                      <div>
                        <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">RESISTANCE</div>
                        <div className="mt-1 font-mono text-sm font-bold tabular-nums text-[rgb(var(--danger))]">{sym.resistance ?? '--'}</div>
                      </div>
                    </div>
                  </div>

                  {/* Chips for selected symbol */}
                  <StockChipsPanel symbol={selectedSymbol} />
                </>
              ) : (
                <div className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.15)] p-6 text-center font-mono text-[10px] text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>
                  {selectedSymbol ? `No technical data for ${selectedSymbol}` : 'Select a symbol'}
                </div>
              )}
            </div>

            {/* ── RIGHT CONTENT: AI Strategy Briefing ─────── */}
            <div className="lg:col-span-9 space-y-4">

              {/* Classification + Confidence */}
              <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] p-6" style={{ borderRadius: '4px' }}>
                <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] mb-4">AI STRATEGY RECOMMENDATION</div>

                <div className="flex flex-wrap items-center gap-6 mb-5">
                  <ClassificationLabel classification={outlook.classification || (report.market_summary?.sentiment === 'bullish' ? 'BUY' : report.market_summary?.sentiment === 'bearish' ? 'SELL' : 'HOLD')} />
                  {/* Confidence meter */}
                  <div>
                    <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-1">CONFIDENCE</div>
                    <div className="flex items-center gap-2">
                      <div className="w-32 h-3 bg-[rgba(var(--grid),0.15)] overflow-hidden" style={{ borderRadius: '2px' }}>
                        <div className="h-full bg-[rgb(var(--accent))] transition-all" style={{ width: `${(outlook.confidence || 0.5) * 100}%` }} />
                      </div>
                      <span className="font-mono text-xs font-bold tabular-nums text-[rgb(var(--text))]">{Math.round((outlook.confidence || 0.5) * 100)}%</span>
                    </div>
                  </div>
                </div>

                {/* Key reasoning */}
                <div className="border-l-2 border-l-[rgba(var(--accent),0.4)] pl-4 mb-4">
                  <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">KEY REASONING</div>
                  <p className="font-mono text-[12px] leading-relaxed text-[rgb(var(--text))]">{strategy.summary || '(No strategy summary available)'}</p>
                </div>

                {/* Sector focus */}
                {outlook.sector_focus?.length > 0 && (
                  <div className="flex flex-wrap gap-2 mb-4">
                    {outlook.sector_focus.map(s => (
                      <span key={s} className="border border-[rgba(var(--accent),0.3)] bg-[rgba(var(--accent),0.08)] px-2.5 py-1 font-mono text-[10px] font-bold text-[rgb(var(--accent))]" style={{ borderRadius: '2px' }}>{s}</span>
                    ))}
                  </div>
                )}

                {/* Supporting evidence -- collapsible */}
                {(actions.length > 0 || opportunities.length > 0 || risks.length > 0) && (
                  <div className="border border-[rgba(var(--grid),0.2)] overflow-hidden" style={{ borderRadius: '2px' }}>
                    <button onClick={() => setEvidenceOpen(o => !o)}
                      className="w-full flex items-center justify-between px-4 py-2.5 font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--muted))] hover:bg-[rgba(var(--surface),0.3)]">
                      <span>SUPPORTING EVIDENCE</span>
                      {evidenceOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                    </button>
                    {evidenceOpen && (
                      <div className="border-t border-[rgba(var(--grid),0.15)] p-4 space-y-4">
                        {/* Position Actions */}
                        {actions.length > 0 && (
                          <div>
                            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">POSITION ACTIONS</div>
                            {actions.map(a => (
                              <div key={a.symbol} className="border-b border-[rgba(var(--grid),0.1)] py-2 last:border-0">
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-xs font-bold text-[rgb(var(--text))]">{formatSymbol(a.symbol, symbolNames)}</span>
                                  <span className={`border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
                                    a.action === 'hold' ? 'border-[rgba(var(--grid),0.3)] text-[rgb(var(--muted))]' :
                                    a.action === 'reduce' ? 'border-[rgba(var(--warn),0.3)] text-[rgb(var(--warn))]' :
                                    'border-[rgba(var(--danger),0.3)] text-[rgb(var(--danger))]'
                                  }`} style={{ borderRadius: '2px' }}>{a.action}</span>
                                </div>
                                <p className="mt-1 font-mono text-[10px] text-[rgb(var(--muted))]">{a.reason}</p>
                              </div>
                            ))}
                          </div>
                        )}
                        {/* Opportunities */}
                        {opportunities.length > 0 && (
                          <div>
                            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">WATCHLIST OPPORTUNITIES</div>
                            {opportunities.map(o => (
                              <div key={o.symbol} className="border-b border-[rgba(var(--grid),0.1)] py-2 last:border-0">
                                <span className="font-mono text-xs font-bold text-[rgb(var(--text))]">{formatSymbol(o.symbol, symbolNames)}</span>
                                <p className="font-mono text-[10px] text-[rgb(var(--muted))]">{o.entry_condition}</p>
                                {o.stop_loss && <p className="font-mono text-[10px] text-[rgb(var(--danger))]">STOP: {o.stop_loss}</p>}
                              </div>
                            ))}
                          </div>
                        )}
                        {/* Risks */}
                        {risks.length > 0 && (
                          <div>
                            <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))] mb-2">RISK NOTES</div>
                            <ul className="space-y-1">
                              {risks.map((r, i) => (
                                <li key={i} className="flex items-start gap-2 font-mono text-[10px] text-[rgb(var(--warn))]">
                                  <span className="mt-0.5 shrink-0 h-1.5 w-1.5 rounded-full bg-[rgb(var(--warn))]" />
                                  <span>{r}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Top Movers */}
              {report.market_summary?.top_movers?.length > 0 && (
                <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
                  <div className="flex items-center justify-between border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
                    <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">TOP MOVERS</span>
                  </div>
                  <div className="p-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                    {report.market_summary.top_movers.map(r => (
                      <div key={r.symbol}
                        className="border-l-2 bg-[rgba(var(--surface),0.3)] px-3 py-2"
                        style={{
                          borderLeftColor: (r.change || 0) >= 0 ? 'rgb(var(--up))' : 'rgb(var(--danger))',
                          borderRadius: '2px'
                        }}>
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-mono text-xs font-bold text-[rgb(var(--text))]">{r.symbol}</span>
                          <span className={`font-mono text-xs font-bold tabular-nums ${(r.change || 0) >= 0 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--danger))]'}`}>
                            {(r.change || 0) >= 0 ? '+' : ''}{r.change?.toFixed(2)}
                          </span>
                        </div>
                        {r.name && <div className="font-mono text-[9px] text-[rgb(var(--muted))] truncate">{r.name}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ══════════════════════════════════════════════════════════
              Economic Calendar (Module 2D)
              ══════════════════════════════════════════════════════════ */}
          <EconomicCalendar maxItems={10} />

          {/* ══════════════════════════════════════════════════════════
              BOTTOM: Institutional Flow Heatmap
              ══════════════════════════════════════════════════════════ */}
          {instFlows.length > 0 && (
            <InstitutionalHeatmap flows={instFlows} />
          )}

          <ChipsFullTable report={report} />
        </>
      )}
    </div>
  )
}
