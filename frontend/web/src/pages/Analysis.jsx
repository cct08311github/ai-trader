import React, { useState, useEffect, useCallback } from 'react'
import { getToken, authFetch, getApiBase } from '../lib/auth'
import { useSymbolNames, formatSymbol } from '../lib/symbolNames'
import KlineChart from '../components/KlineChart'

const TABS = ['今日市場概覽', '個股技術分析', '法人籌碼', 'AI 明日策略']

function Panel({ title, children }) {
  return (
    <section className="rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] shadow-panel">
      <div className="border-b border-[rgb(var(--border))] px-4 py-3 text-sm font-semibold">{title}</div>
      <div className="p-4">{children}</div>
    </section>
  )
}

function SentimentBadge({ sentiment }) {
  const map = { bullish: ['偏多', 'text-emerald-400'], bearish: ['偏空', 'text-rose-400'], neutral: ['中性', 'text-slate-400'] }
  const [label, cls] = map[sentiment] || ['未知', 'text-slate-500']
  return <span className={`font-semibold ${cls}`}>{label}</span>
}

function MarketOverviewTab({ report }) {
  const { market_summary } = report
  const topMovers = market_summary?.top_movers || []
  const instFlows = market_summary?.institution_flows || []
  return (
    <div className="space-y-4">
      <Panel title="市場氣氛">
        <div className="flex items-center gap-3">
          <span className="text-sm text-[rgb(var(--muted))]">今日多空：</span>
          <SentimentBadge sentiment={market_summary?.sentiment} />
        </div>
      </Panel>
      <Panel title="漲跌幅前 10 名">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-[rgb(var(--muted))]">
              <th className="text-left py-1 pr-3">代碼</th>
              <th className="text-left py-1 pr-3">名稱</th>
              <th className="text-right py-1 pr-3">收盤</th>
              <th className="text-right py-1">漲跌</th>
            </tr></thead>
            <tbody>
              {topMovers.map(r => (
                <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                  <td className="py-1 pr-3 font-mono">{r.symbol}</td>
                  <td className="py-1 pr-3">{r.name}</td>
                  <td className="py-1 pr-3 text-right">{r.close?.toFixed(1)}</td>
                  <td className={`py-1 text-right ${(r.change||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {(r.change||0) >= 0 ? '+' : ''}{r.change?.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {instFlows.length > 0 && (
        <Panel title="三大法人流向（萬元）">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-[rgb(var(--muted))]">
                <th className="text-left py-1 pr-3">代碼</th>
                <th className="text-right py-1 pr-3">外資</th>
                <th className="text-right py-1 pr-3">投信</th>
                <th className="text-right py-1">自營</th>
              </tr></thead>
              <tbody>
                {instFlows.map(r => (
                  <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                    <td className="py-1 pr-3 font-mono">{r.symbol}</td>
                    <td className={`py-1 pr-3 text-right ${(r.foreign_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {((r.foreign_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-1 pr-3 text-right ${(r.investment_trust_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {((r.investment_trust_net||0)/10000).toFixed(0)}
                    </td>
                    <td className={`py-1 text-right ${(r.dealer_net||0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
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
        if (!date) { setMsg('尚無籌碼資料'); setLoading(false); return null }
        setChipsDate(date)
        return authFetch(`${getApiBase()}/api/chips/${date}/summary?symbol=${symbol.toUpperCase()}`)
      })
      .then(r => {
        if (!r) return
        if (r.status === 404) { setMsg('此股票無籌碼資料'); setLoading(false); return null }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => { if (d) { setData(d.data?.[0] ?? null); setLoading(false) } })
      .catch(e => { setMsg(String(e?.message || e)); setLoading(false) })
  }, [symbol])

  if (!symbol) return null
  if (loading) return <div className="text-xs text-[rgb(var(--muted))]">載入籌碼中…</div>
  if (msg || !data) return (
    <div className="rounded-xl border border-slate-500/20 bg-slate-500/5 px-4 py-3 text-xs text-[rgb(var(--muted))]">
      {msg || '無籌碼資料'}
    </div>
  )
  return (
    <Panel title={`法人籌碼（${chipsDate}）`}>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
        {[
          ['外資', data.foreign_net],
          ['投信', data.trust_net],
          ['自營商', data.dealer_net],
          ['三大合計', data.total_net],
        ].map(([label, val]) => (
          <div key={label}>
            <div className="text-[rgb(var(--muted))]">{label}</div>
            <div className={`mt-0.5 font-mono font-semibold ${netCls(val)}`}>
              {fmtShares(val)} 萬股
            </div>
          </div>
        ))}
      </div>
      {(data.margin_balance != null || data.short_balance != null) && (
        <div className="mt-3 flex gap-6 text-xs">
          <div>
            <span className="text-[rgb(var(--muted))]">融資餘額 </span>
            <span className="font-mono text-sky-300">{fmtLots(data.margin_balance)} 張</span>
          </div>
          <div>
            <span className="text-[rgb(var(--muted))]">融券餘額 </span>
            <span className="font-mono text-amber-300">{fmtLots(data.short_balance)} 張</span>
          </div>
        </div>
      )}
    </Panel>
  )
}

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

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {symbols.map(s => (
          <button key={s}
            onClick={() => { setSelected(s); setSearchInput('') }}
            className={`rounded-lg px-3 py-1 text-xs font-mono transition-colors ${
              selected === s && !searchInput
                ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/30'
                : 'bg-[rgb(var(--surface))/0.3] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
            }`}
          >{formatSymbol(s, symbolNames)}</button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          placeholder="查詢其他股票（輸入代號，如 2330）"
          value={searchInput}
          onChange={e => setSearchInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSearch()}
          className="flex-1 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.3] px-3 py-1.5 text-sm text-[rgb(var(--text))] outline-none focus:border-emerald-500/50 placeholder:text-[rgb(var(--muted))]"
        />
        <button
          onClick={handleSearch}
          className="rounded-lg bg-emerald-500/20 px-4 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/30 transition-colors"
        >查詢</button>
      </div>

      {selected && (
        <>
          <div className="flex items-baseline gap-2 border-b border-[rgb(var(--border))] pb-2">
            <span className="font-mono text-lg font-semibold text-[rgb(var(--text))]">{selected}</span>
            {symbolNames?.[selected] && (
              <span className="text-sm text-[rgb(var(--muted))]">{symbolNames[selected]}</span>
            )}
          </div>
          <KlineChart symbol={selected} />
          {sym && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {[
                ['收盤', sym.close],
                ['MA5', sym.ma5],
                ['MA20', sym.ma20],
                ['MA60', sym.ma60],
                ['RSI14', sym.rsi14?.toFixed(1)],
                ['MACD', sym.macd?.macd?.toFixed(2)],
                ['Signal', sym.macd?.signal?.toFixed(2)],
                ['支撐', sym.support],
                ['壓力', sym.resistance],
              ].map(([label, value]) => (
                <div key={label} className="rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] px-3 py-2">
                  <div className="text-xs text-[rgb(var(--muted))]">{label}</div>
                  <div className="mt-1 font-mono text-sm">{value ?? '—'}</div>
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

// 股數轉萬股：550000 → "55.0"（用於三大法人買賣超）
const fmtShares = v => (v == null ? '—' : (v / 10000).toFixed(1))
// 張數格式化：12000 → "12,000"（用於融資借券餘額）
const fmtLots = v => (v == null ? '—' : Number(v).toLocaleString())
const netCls = v => (v == null || v >= 0 ? 'text-emerald-400' : 'text-rose-400')


function ChipsTab({ report }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const symbolNames = useSymbolNames()
  const tradeDate = report?.trade_date

  useEffect(() => {
    if (!tradeDate) { setError('本日尚無法人籌碼資料'); setLoading(false); return }
    setLoading(true); setError(null)
    fetch(`/api/chips/${tradeDate}/summary`, { headers: { Authorization: `Bearer ${getToken()}` } })
      .then(r => {
        if (r.status === 404) { setError('本日尚無法人籌碼資料'); setLoading(false); return null }
        if (!r.ok) throw new Error(`無法載入籌碼資料 (HTTP ${r.status})`)
        return r.json()
      })
      .then(d => { if (d) { setData(d); setLoading(false) } })
      .catch(() => { setError('無法載入籌碼資料'); setLoading(false) })
  }, [tradeDate])

  if (loading) return <div className="text-sm text-[rgb(var(--muted))]">讀取籌碼資料中…</div>
  if (error) return <div className="rounded-xl border border-slate-500/30 bg-slate-500/10 p-4 text-sm text-[rgb(var(--muted))]">{error}</div>
  if (!data?.data?.length) return <div className="rounded-xl border border-slate-500/30 bg-slate-500/10 p-4 text-sm text-[rgb(var(--muted))]">本日尚無法人籌碼資料</div>

  const rows = data.data
  const hasMargin = rows.some(r => r.margin_balance != null)

  return (
    <div className="space-y-4">
      <Panel title="三大法人買賣超（萬股）">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-[rgb(var(--muted))]">
              <th className="text-left py-1 pr-3">代碼</th>
              <th className="text-right py-1 pr-3">外資</th>
              <th className="text-right py-1 pr-3">投信</th>
              <th className="text-right py-1 pr-3">自營</th>
              <th className="text-right py-1">合計</th>
            </tr></thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                  <td className="py-1 pr-3 font-mono">{formatSymbol(r.symbol, symbolNames || {})}</td>
                  <td className={`py-1 pr-3 text-right font-mono ${netCls(r.foreign_net)}`}>{fmtShares(r.foreign_net)}</td>
                  <td className={`py-1 pr-3 text-right font-mono ${netCls(r.trust_net)}`}>{fmtShares(r.trust_net)}</td>
                  <td className={`py-1 pr-3 text-right font-mono ${netCls(r.dealer_net)}`}>{fmtShares(r.dealer_net)}</td>
                  <td className={`py-1 text-right font-mono font-semibold ${netCls(r.total_net)}`}>{fmtShares(r.total_net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {hasMargin && (
        <Panel title="融資借券餘額（張）">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-[rgb(var(--muted))]">
                <th className="text-left py-1 pr-3">代碼</th>
                <th className="text-right py-1 pr-3">融資餘額</th>
                <th className="text-right py-1">融券餘額</th>
              </tr></thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.symbol} className="border-t border-[rgb(var(--border))]">
                    <td className="py-1 pr-3 font-mono">{formatSymbol(r.symbol, symbolNames || {})}</td>
                    <td className="py-1 pr-3 text-right font-mono text-sky-300">{fmtLots(r.margin_balance)}</td>
                    <td className="py-1 text-right font-mono text-amber-300">{fmtLots(r.short_balance)}</td>
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

function StrategyTab({ report }) {
  const strategy = report.strategy || {}
  const outlook = strategy.market_outlook || {}
  const actions = strategy.position_actions || []
  const opportunities = strategy.watchlist_opportunities || []
  const risks = strategy.risk_notes || []
  const symbolNames = useSymbolNames()

  return (
    <div className="space-y-4">
      <Panel title="整體市場展望">
        <p className="text-sm">{strategy.summary || '—'}</p>
        {outlook.sector_focus?.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {outlook.sector_focus.map(s => (
              <span key={s} className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300">{s}</span>
            ))}
          </div>
        )}
      </Panel>
      {actions.length > 0 && (
        <Panel title="持倉操作建議">
          {actions.map(a => (
            <div key={a.symbol} className="border-b border-[rgb(var(--border))] py-2 last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm">{formatSymbol(a.symbol, symbolNames)}</span>
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                  a.action === 'hold' ? 'bg-slate-500/20 text-slate-300' :
                  a.action === 'reduce' ? 'bg-amber-500/20 text-amber-300' :
                  'bg-rose-500/20 text-rose-300'
                }`}>{a.action}</span>
              </div>
              <p className="mt-1 text-xs text-[rgb(var(--muted))]">{a.reason}</p>
            </div>
          ))}
        </Panel>
      )}
      {opportunities.length > 0 && (
        <Panel title="觀察名單機會">
          {opportunities.map(o => (
            <div key={o.symbol} className="border-b border-[rgb(var(--border))] py-2 last:border-0">
              <span className="font-mono text-sm">{formatSymbol(o.symbol, symbolNames)}</span>
              <p className="text-xs text-[rgb(var(--muted))]">{o.entry_condition}</p>
              {o.stop_loss && <p className="text-xs text-rose-400">Stop loss: {o.stop_loss}</p>}
            </div>
          ))}
        </Panel>
      )}
      {risks.length > 0 && (
        <Panel title="風險注意事項">
          <ul className="space-y-1">
            {risks.map((r, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-amber-300">
                <span className="mt-0.5 shrink-0">⚠</span><span>{r}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}

export default function AnalysisPage() {
  const [activeTab, setActiveTab] = useState(0)
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [noData, setNoData] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    setNoData(false)
    try {
      const r = await fetch('/api/analysis/latest', {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.status === 404) { setNoData(true); return }
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setReport(await r.json())
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">盤後分析</h2>
        {report && (
          <span className="text-xs text-[rgb(var(--muted))]">
            分析日期：{report.trade_date}
          </span>
        )}
      </div>

      {loading && <div className="text-sm text-[rgb(var(--muted))]">讀取中…</div>}
      {noData && !loading && (
        <div className="rounded-xl border border-slate-500/30 bg-slate-500/10 p-6 text-center text-sm text-[rgb(var(--muted))]">
          📊 今日盤後分析尚未產生（每交易日 22:00 自動執行）
        </div>
      )}
      {error && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">無法載入盤後分析：{error}</div>}

      {report && !loading && (
        <>
          <div className="flex gap-1 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] p-1">
            {TABS.map((tab, i) => (
              <button
                key={tab}
                onClick={() => setActiveTab(i)}
                className={`flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors ${
                  activeTab === i
                    ? 'bg-emerald-500/15 text-emerald-300'
                    : 'text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]'
                }`}
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
