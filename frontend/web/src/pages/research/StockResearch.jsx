import React, { useState, useCallback } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'

import { PriceChart } from '../../components/charts/PriceChart'
import { DataCard } from '../../components/ui/DataCard'
import { MetricBadge } from '../../components/ui/MetricBadge'
import { SentimentIndicator } from '../../components/ui/SentimentIndicator'

// ── BattleTheme colour references ─────────────────────────────────────────────
const C_UP     = 'rgb(var(--up,    34 197 94))'
const C_DOWN   = 'rgb(var(--down,  239 68 68))'
const C_ACCENT = 'rgb(var(--accent, 56 189 248))'
const C_WARN   = 'rgb(var(--warn,  251 146 60))'
const C_MUTED  = 'rgb(var(--muted, 100 116 139))'
const C_TEXT   = 'rgb(var(--text,  226 232 240))'
const C_GOLD   = 'rgb(var(--gold,  161 138 90))'

// ── Rating badge colours ──────────────────────────────────────────────────────
const RATING_COLOR = { A: C_UP, B: C_ACCENT, C: C_WARN, D: C_DOWN }

// ── API fetchers ──────────────────────────────────────────────────────────────

async function apiFetch(url) {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json?.data ?? json
}

const fetchWatchlist        = ()       => apiFetch('/api/research/watchlist')
const fetchStockReport      = (sym)    => apiFetch(`/api/research/stocks/${sym}`)
const fetchDebate           = (sym)    => apiFetch(`/api/research/debate/${sym}`)
const fetchPortfolioSummary = ()       => apiFetch('/api/portfolio/summary')
const fetchPositionDetail   = (sym)    => apiFetch(`/api/portfolio/position-detail/${encodeURIComponent(sym)}`)
const fetchStockHistory     = (sym)    => apiFetch(`/api/research/stocks/${sym}/history`)

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, decimals = 2) {
  if (n === null || n === undefined) return '—'
  return Number(n).toFixed(decimals)
}

function fmtPct(n) {
  if (n === null || n === undefined) return '—'
  return `${Number(n * 100).toFixed(2)}%`
}

function fmtN(n) {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat('zh-TW').format(n)
}

// AI Score = confidence * 10, capped 0-10
function aiScore(confidence) {
  if (confidence === null || confidence === undefined) return '—'
  return (Math.min(10, Math.max(0, Number(confidence) * 10))).toFixed(1)
}

// Recommendation sentiment mapping
function recToSentiment(rec) {
  if (!rec) return 'neutral'
  const r = rec.toLowerCase()
  if (r.includes('buy') || r.includes('long') || r.includes('看多') || r.includes('多')) return 'bullish'
  if (r.includes('sell') || r.includes('short') || r.includes('看空') || r.includes('空')) return 'bearish'
  return 'neutral'
}

// Build radar data from llm_synthesis_json
function buildRadarData(synthesis) {
  if (!synthesis) {
    return [
      { subject: '技術面', fullMark: 10, value: 0 },
      { subject: '法人面', fullMark: 10, value: 0 },
      { subject: '基本面', fullMark: 10, value: 0 },
      { subject: '事件面', fullMark: 10, value: 0 },
    ]
  }
  return [
    { subject: '技術面', fullMark: 10, value: Number(synthesis.technical_score  ?? synthesis.technical  ?? 0) },
    { subject: '法人面', fullMark: 10, value: Number(synthesis.institutional_score ?? synthesis.institutional ?? 0) },
    { subject: '基本面', fullMark: 10, value: Number(synthesis.fundamental_score ?? synthesis.fundamental ?? 0) },
    { subject: '事件面', fullMark: 10, value: Number(synthesis.event_score       ?? synthesis.event       ?? 0) },
  ]
}

// Extract OHLCV array from position-detail response
function extractOhlcv(detail) {
  if (!detail) return []
  // Various shapes the backend might return
  const raw = detail.ohlcv ?? detail.kline ?? detail.candles ?? detail.price_history ?? []
  if (!Array.isArray(raw)) return []
  return raw.map((d) => ({
    time:   d.time  ?? d.date ?? d.trade_date,
    open:   Number(d.open),
    high:   Number(d.high),
    low:    Number(d.low),
    close:  Number(d.close),
    volume: Number(d.volume ?? 0),
  })).filter((d) => d.time)
}

// Find the holding for this symbol in portfolio summary
function findHolding(summary, symbol) {
  if (!summary) return null
  const positions = summary.positions ?? summary.holdings ?? []
  return positions.find(
    (p) => (p.symbol ?? p.ticker ?? '').toUpperCase() === symbol.toUpperCase()
  ) ?? null
}

// ── Sub-components ────────────────────────────────────────────────────────────

function RatingBadge({ rating }) {
  const color = RATING_COLOR[rating?.toUpperCase()] ?? C_MUTED
  return (
    <span
      className="inline-flex items-center justify-center w-7 h-7 rounded-sm text-sm font-bold border"
      style={{
        fontFamily: 'var(--font-mono)',
        color,
        borderColor: color,
        backgroundColor: `${color}1a`,
        textShadow: `0 0 8px ${color}`,
      }}
    >
      {rating?.toUpperCase() ?? '?'}
    </span>
  )
}

function AiScoreBadge({ confidence }) {
  const score = confidence !== null && confidence !== undefined
    ? (Math.min(10, Math.max(0, Number(confidence) * 10))).toFixed(1)
    : null
  const color = score === null ? C_MUTED
    : Number(score) >= 7 ? C_UP
    : Number(score) >= 5 ? C_WARN
    : C_DOWN
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-bold border"
      style={{
        fontFamily: 'var(--font-data)',
        color,
        borderColor: color,
        backgroundColor: `${color}1a`,
      }}
    >
      <span style={{ fontSize: '9px', opacity: 0.7, fontFamily: 'var(--font-mono)' }}>AI</span>
      {score ?? '—'}
    </span>
  )
}

function ConfidenceBar({ value, color }) {
  const pct = Math.min(100, Math.max(0, Number(value ?? 0) * 100))
  return (
    <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: `${color}33` }}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  )
}

// ── Portfolio cross-reference block ──────────────────────────────────────────

function PortfolioCrossRef({ symbol, summary }) {
  const holding = findHolding(summary, symbol)
  if (!holding) return null

  const qty       = holding.quantity    ?? holding.shares ?? 0
  const avgCost   = holding.avg_cost    ?? holding.cost_basis ?? holding.average_cost ?? 0
  const mktValue  = holding.market_value ?? (qty * (holding.last_price ?? 0))
  const unrealPnl = holding.unrealized_pnl ?? holding.unrealized_gain ?? (mktValue - qty * avgCost)
  const pnlPct    = holding.unrealized_pnl_pct ?? (avgCost > 0 ? (unrealPnl / (qty * avgCost)) : 0)
  const weight    = holding.weight ?? holding.portfolio_weight ?? null

  const pnlColor = unrealPnl >= 0 ? C_UP : C_DOWN

  return (
    <DataCard
      title="投資組合持倉"
      accentColor={C_GOLD}
      className="mb-4"
    >
      <div className="flex flex-wrap items-center gap-4">
        <div className="flex flex-col">
          <span className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)', fontSize: '10px' }}>
            持倉
          </span>
          <span className="text-sm" style={{ fontFamily: 'var(--font-data)', color: C_TEXT }}>
            {fmtN(qty)} 股 @ {fmt(avgCost)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)', fontSize: '10px' }}>
            未實現損益
          </span>
          <span className="text-sm font-bold tabular-nums" style={{ fontFamily: 'var(--font-data)', color: pnlColor }}>
            {unrealPnl >= 0 ? '+' : ''}{fmt(unrealPnl)}&nbsp;
            <span className="text-xs opacity-80">({unrealPnl >= 0 ? '+' : ''}{fmtPct(pnlPct)})</span>
          </span>
        </div>
        {weight !== null && (
          <div className="flex flex-col">
            <span className="text-xs text-th-muted" style={{ fontFamily: 'var(--font-ui)', fontSize: '10px' }}>
              投組佔比
            </span>
            <span className="text-sm tabular-nums" style={{ fontFamily: 'var(--font-data)', color: C_ACCENT }}>
              {fmtPct(weight)}
            </span>
          </div>
        )}
      </div>
    </DataCard>
  )
}

// ── Radar chart ───────────────────────────────────────────────────────────────

function AiRadar({ synthesis }) {
  const data = buildRadarData(synthesis)
  return (
    <ResponsiveContainer width="100%" height={200}>
      <RadarChart cx="50%" cy="50%" outerRadius="72%" data={data}>
        <PolarGrid stroke={`${C_MUTED}44`} />
        <PolarAngleAxis
          dataKey="subject"
          tick={{ fill: C_MUTED, fontSize: 11, fontFamily: 'var(--font-ui)' }}
        />
        <PolarRadiusAxis
          angle={30}
          domain={[0, 10]}
          tick={{ fill: C_MUTED, fontSize: 9 }}
          axisLine={false}
          tickCount={3}
        />
        <Radar
          name="AI Score"
          dataKey="value"
          stroke={C_ACCENT}
          fill={C_ACCENT}
          fillOpacity={0.18}
          dot={{ fill: C_ACCENT, r: 3 }}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: 'rgb(var(--card, 13 19 30))',
            border: `1px solid ${C_MUTED}44`,
            borderRadius: '2px',
            fontFamily: 'var(--font-data)',
            fontSize: '11px',
            color: C_TEXT,
          }}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

// ── Fundamentals panel ────────────────────────────────────────────────────────

function FundamentalsPanel({ report }) {
  const pe       = report?.pe_ratio
  const pb       = report?.pb_ratio
  const eps      = report?.eps
  const divYield = report?.dividend_yield
  const revYoY   = report?.monthly_revenue_yoy

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <MetricBadge label="P/E"           value={pe       !== undefined ? fmt(pe, 1)     : null} format="raw" />
      <MetricBadge label="P/B"           value={pb       !== undefined ? fmt(pb, 2)     : null} format="raw" />
      <MetricBadge label="EPS (TTM)"     value={eps      !== undefined ? fmt(eps, 2)    : null} format="raw" />
      <MetricBadge label="殖利率"        value={divYield !== undefined ? fmtPct(divYield) : null} format="raw" />
      <MetricBadge label="月營收 YoY"   value={revYoY   !== undefined ? fmtPct(revYoY)  : null}
        trend={revYoY > 0 ? 'up' : revYoY < 0 ? 'down' : 'flat'} format="raw" />
      <MetricBadge label="最新收盤"      value={report?.latest_close !== undefined ? fmt(report.latest_close) : null} format="raw" />
    </div>
  )
}

// ── Bull vs Bear Debate ───────────────────────────────────────────────────────

function DebateSide({ side, data, isLeft }) {
  if (!data) return null
  const color = isLeft ? C_UP : C_DOWN
  const thesis     = data.thesis     ?? data.summary    ?? data.argument   ?? ''
  const catalysts  = data.catalysts  ?? data.risks      ?? data.points     ?? []
  const confidence = data.confidence ?? null

  return (
    <div
      className="flex-1 min-w-0 rounded-sm border p-3 space-y-2"
      style={{ borderColor: color, backgroundColor: `${color}0d` }}
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="text-xs font-bold tracking-widest uppercase"
          style={{ fontFamily: 'var(--font-mono)', color }}
        >
          {isLeft ? '多方' : '空方'}
        </span>
        {confidence !== null && (
          <span className="text-xs tabular-nums" style={{ fontFamily: 'var(--font-data)', color }}>
            {fmtPct(confidence)}
          </span>
        )}
      </div>

      {thesis && (
        <p className="text-xs leading-relaxed" style={{ fontFamily: 'var(--font-ui)', color: C_TEXT }}>
          {thesis}
        </p>
      )}

      {Array.isArray(catalysts) && catalysts.length > 0 && (
        <ul className="space-y-1">
          {catalysts.slice(0, 3).map((c, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs" style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>
              <span style={{ color, flexShrink: 0, marginTop: '1px' }}>{isLeft ? '▲' : '▼'}</span>
              <span>{typeof c === 'string' ? c : c.text ?? c.point ?? JSON.stringify(c)}</span>
            </li>
          ))}
        </ul>
      )}

      {confidence !== null && (
        <ConfidenceBar value={confidence} color={color} />
      )}
    </div>
  )
}

function ArbiterPanel({ arbiter, recommendation, confidence }) {
  if (!arbiter && !recommendation) return null
  const verdict = arbiter?.verdict ?? arbiter?.summary ?? arbiter?.decision ?? recommendation ?? ''
  const rationale = arbiter?.rationale ?? arbiter?.reasoning ?? ''
  const sentiment = recToSentiment(verdict || recommendation)
  const conf = arbiter?.confidence ?? confidence ?? null
  const color = sentiment === 'bullish' ? C_UP : sentiment === 'bearish' ? C_DOWN : C_WARN

  return (
    <div
      className="rounded-sm border p-3 space-y-2 mt-3"
      style={{ borderColor: `${C_ACCENT}55`, backgroundColor: `${C_ACCENT}08` }}
    >
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <span
          className="text-xs font-bold tracking-widest uppercase"
          style={{ fontFamily: 'var(--font-mono)', color: C_ACCENT }}
        >
          仲裁裁決
        </span>
        <SentimentIndicator sentiment={sentiment} />
      </div>

      {verdict && (
        <p className="text-xs font-medium" style={{ fontFamily: 'var(--font-ui)', color }}>
          {verdict}
        </p>
      )}

      {rationale && (
        <p className="text-xs leading-relaxed" style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>
          {rationale}
        </p>
      )}

      {conf !== null && (
        <div className="space-y-1">
          <div className="flex justify-between text-xs" style={{ fontFamily: 'var(--font-data)', color: C_MUTED }}>
            <span>信心度</span>
            <span>{fmtPct(conf)}</span>
          </div>
          <ConfidenceBar value={conf} color={color} />
        </div>
      )}
    </div>
  )
}

// ── AI Synthesis block ────────────────────────────────────────────────────────

function AiSynthesisPanel({ report, historyFirst }) {
  const synthesis  = report?.llm_synthesis_json ?? {}
  const entry      = report?.entry_price
  const stopLoss   = report?.stop_loss
  const target     = report?.target_price
  const rationale  = synthesis.rationale ?? synthesis.summary ?? report?.report_markdown ?? ''
  const prevConf   = historyFirst?.confidence
  const currConf   = report?.confidence

  const hasRisk    = stopLoss !== null && stopLoss !== undefined
  const hasTarget  = target   !== null && target   !== undefined

  return (
    <div className="space-y-3">
      {/* Price targets row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-1 rounded-sm border p-2" style={{ borderColor: `${C_ACCENT}44` }}>
          <span className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: C_MUTED, fontSize: '10px' }}>
            進場價
          </span>
          <span className="text-base tabular-nums font-bold" style={{ fontFamily: 'var(--font-data)', color: C_ACCENT }}>
            {entry !== null && entry !== undefined ? fmt(entry) : '—'}
          </span>
        </div>
        <div className="flex flex-col gap-1 rounded-sm border p-2" style={{ borderColor: `${C_DOWN}44` }}>
          <span className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: C_MUTED, fontSize: '10px' }}>
            停損價
          </span>
          <span className="text-base tabular-nums font-bold" style={{ fontFamily: 'var(--font-data)', color: C_DOWN }}>
            {hasRisk ? fmt(stopLoss) : '—'}
          </span>
        </div>
        <div className="flex flex-col gap-1 rounded-sm border p-2" style={{ borderColor: `${C_UP}44` }}>
          <span className="text-xs" style={{ fontFamily: 'var(--font-mono)', color: C_MUTED, fontSize: '10px' }}>
            目標價
          </span>
          <span className="text-base tabular-nums font-bold" style={{ fontFamily: 'var(--font-data)', color: C_UP }}>
            {hasTarget ? fmt(target) : '—'}
          </span>
        </div>
      </div>

      {/* Score delta */}
      {prevConf !== undefined && currConf !== undefined && (
        <div className="flex items-center gap-3 text-xs" style={{ fontFamily: 'var(--font-data)' }}>
          <span style={{ color: C_MUTED }}>評分變化</span>
          <span style={{ color: C_MUTED }}>{aiScore(prevConf)}</span>
          <span style={{ color: C_MUTED }}>→</span>
          <span style={{ color: Number(currConf) >= Number(prevConf) ? C_UP : C_DOWN }}>
            {aiScore(currConf)}
          </span>
          <span style={{ color: Number(currConf) >= Number(prevConf) ? C_UP : C_DOWN }}>
            {Number(currConf) >= Number(prevConf) ? '▲' : '▼'}
          </span>
        </div>
      )}

      {/* Rationale */}
      {rationale && (
        <p className="text-xs leading-relaxed" style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>
          {String(rationale).slice(0, 500)}
          {String(rationale).length > 500 && '…'}
        </p>
      )}
    </div>
  )
}

// ── Symbol Selector ───────────────────────────────────────────────────────────

function SymbolSelector({ currentSymbol, watchlist, onSelect }) {
  const symbols = Array.isArray(watchlist)
    ? watchlist
    : (watchlist?.stocks ?? watchlist?.symbols ?? [])

  const options = symbols.map((s) =>
    typeof s === 'string' ? { symbol: s, name: '' } : s
  )

  return (
    <select
      value={currentSymbol}
      onChange={(e) => onSelect(e.target.value)}
      className="h-8 px-2 rounded-sm border text-xs focus:outline-none focus:ring-1"
      style={{
        fontFamily: 'var(--font-data)',
        backgroundColor: 'rgb(var(--card, 13 19 30))',
        borderColor: 'rgb(var(--border, 51 65 85))',
        color: C_TEXT,
        minWidth: '120px',
      }}
    >
      {currentSymbol && !options.find((o) => o.symbol === currentSymbol) && (
        <option value={currentSymbol}>{currentSymbol}</option>
      )}
      {options.map((o) => (
        <option key={o.symbol} value={o.symbol}>
          {o.symbol}{o.name ? ` - ${o.name}` : ''}
        </option>
      ))}
      {options.length === 0 && (
        <option value="" disabled>（無自選股）</option>
      )}
    </select>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function StockResearch() {
  const [searchParams, setSearchParams] = useSearchParams()
  const symbolParam = (searchParams.get('symbol') ?? '').toUpperCase()
  const [symbol, setSymbol] = useState(symbolParam || '')

  const navigate = useNavigate()

  const handleSelect = useCallback((sym) => {
    if (!sym) return
    const upper = sym.toUpperCase()
    setSymbol(upper)
    setSearchParams({ symbol: upper }, { replace: true })
  }, [setSearchParams])

  // ── Queries ─────────────────────────────────────────────────────────────────
  const { data: watchlist } = useQuery({
    queryKey: ['research', 'watchlist'],
    queryFn: fetchWatchlist,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const { data: report, isLoading: reportLoading, error: reportError } = useQuery({
    queryKey: ['research', 'stock', symbol],
    queryFn: () => fetchStockReport(symbol),
    enabled: !!symbol,
    staleTime: 2 * 60 * 1000,
    retry: 1,
  })

  const { data: debate, isLoading: debateLoading, error: debateError } = useQuery({
    queryKey: ['research', 'debate', symbol],
    queryFn: () => fetchDebate(symbol),
    enabled: !!symbol,
    staleTime: 2 * 60 * 1000,
    retry: 1,
  })

  const { data: portfolioSummary } = useQuery({
    queryKey: ['portfolio', 'summary'],
    queryFn: fetchPortfolioSummary,
    staleTime: 60 * 1000,
    retry: 1,
  })

  const { data: positionDetail, isLoading: klineLoading } = useQuery({
    queryKey: ['portfolio', 'position-detail', symbol],
    queryFn: () => fetchPositionDetail(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const { data: history } = useQuery({
    queryKey: ['research', 'stock-history', symbol],
    queryFn: () => fetchStockHistory(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  // ── Derived data ─────────────────────────────────────────────────────────────
  const ohlcv = extractOhlcv(positionDetail)
  const synthesis = report?.llm_synthesis_json ?? {}
  const radarData = buildRadarData(synthesis)

  // Previous report for score comparison (history[1] if history is an array)
  const historyList = Array.isArray(history) ? history : (history?.reports ?? [])
  const historyFirst = historyList?.[1] ?? null // index 0 = current, 1 = previous

  const debateData = debate ?? {}
  const bullThesis   = debateData.bull_thesis_json
  const bearThesis   = debateData.bear_thesis_json
  const arbiter      = debateData.arbiter_decision_json
  const recommendation = debateData.recommendation

  const stockName = report?.name ?? report?.company_name ?? report?.stock_name ?? ''
  const confidence = report?.confidence
  const rating     = report?.rating

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4 px-0 sm:px-1">

      {/* ── Top bar ── */}
      <div className="flex flex-wrap items-center gap-3 pb-2 border-b border-th-border">
        {/* Symbol selector */}
        <SymbolSelector
          currentSymbol={symbol}
          watchlist={watchlist}
          onSelect={handleSelect}
        />

        {/* Current stock info */}
        {symbol && (
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-xl font-bold tracking-wide"
              style={{ fontFamily: 'var(--font-data)', color: C_ACCENT }}
            >
              {symbol}
            </span>
            {stockName && (
              <span
                className="text-sm"
                style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}
              >
                {stockName}
              </span>
            )}
            {confidence !== undefined && confidence !== null && (
              <AiScoreBadge confidence={confidence} />
            )}
            {rating && <RatingBadge rating={rating} />}
          </div>
        )}

        {/* Fallback prompt */}
        {!symbol && (
          <span
            className="text-sm"
            style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}
          >
            請選擇或輸入股票代碼開始分析
          </span>
        )}
      </div>

      {/* ── Portfolio cross-reference ── */}
      {symbol && portfolioSummary && (
        <PortfolioCrossRef symbol={symbol} summary={portfolioSummary} />
      )}

      {/* ── K-line hero (full width) ── */}
      {symbol && (
        <DataCard
          title={`K 線圖  ${symbol}`}
          loading={klineLoading}
          empty={!klineLoading && ohlcv.length === 0 ? '尚無 K 線資料' : undefined}
          accentColor={C_ACCENT}
        >
          {ohlcv.length > 0 && (
            <div className="-mx-3 -mb-3">
              <PriceChart data={ohlcv} symbol={symbol} height={360} />
            </div>
          )}
        </DataCard>
      )}

      {/* ── Radar + Fundamentals (side by side) ── */}
      {symbol && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* AI Scoring Radar */}
          <DataCard
            title="AI 評分雷達"
            loading={reportLoading}
            error={reportError}
            accentColor={C_ACCENT}
          >
            <div className="space-y-2">
              <AiRadar synthesis={synthesis} />
              {/* Dimension breakdown */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1">
                {radarData.map((d) => (
                  <div key={d.subject} className="flex items-center justify-between text-xs">
                    <span style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>{d.subject}</span>
                    <span style={{ fontFamily: 'var(--font-data)', color: C_ACCENT }}>
                      {d.value > 0 ? d.value.toFixed(1) : '—'}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-2 text-xs pt-1 border-t border-th-border">
                <span style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>綜合評分</span>
                <span style={{ fontFamily: 'var(--font-data)', color: C_ACCENT, fontSize: '14px', fontWeight: 'bold' }}>
                  {aiScore(confidence)}
                </span>
                {rating && <RatingBadge rating={rating} />}
              </div>
            </div>
          </DataCard>

          {/* Fundamental metrics */}
          <DataCard
            title="基本面指標"
            loading={reportLoading}
            error={reportError}
            accentColor={C_GOLD}
          >
            <FundamentalsPanel report={report} />
          </DataCard>
        </div>
      )}

      {/* ── Bull vs Bear Debate (full width) ── */}
      {symbol && (
        <DataCard
          title="多空辯論"
          loading={debateLoading}
          error={debateError}
          accentColor={C_WARN}
          empty={!debateLoading && !debateError && !bullThesis && !bearThesis ? '尚無辯論資料' : undefined}
        >
          {(bullThesis || bearThesis) && (
            <div className="space-y-3">
              {/* Two sides */}
              <div className="flex flex-col sm:flex-row gap-3">
                <DebateSide side="bull" data={bullThesis} isLeft={true} />
                <DebateSide side="bear" data={bearThesis} isLeft={false} />
              </div>
              {/* Arbiter */}
              <ArbiterPanel
                arbiter={arbiter}
                recommendation={recommendation}
                confidence={debateData.confidence}
              />
            </div>
          )}
        </DataCard>
      )}

      {/* ── AI Synthesis ── */}
      {symbol && (
        <DataCard
          title="AI 綜合研判"
          loading={reportLoading}
          error={reportError}
          empty={!reportLoading && !reportError && !report ? '尚無研究報告' : undefined}
          accentColor={C_ACCENT}
        >
          {report && (
            <AiSynthesisPanel report={report} historyFirst={historyFirst} />
          )}
        </DataCard>
      )}

      {/* Empty state — no symbol selected */}
      {!symbol && (
        <DataCard
          title="個股分析"
          empty="請從上方選擇股票代碼，或在 URL 加上 ?symbol=2382"
        />
      )}
    </div>
  )
}
