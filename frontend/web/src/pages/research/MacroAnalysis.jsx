import React, { useState, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

import { DataCard } from '../../components/ui/DataCard'
import { MetricBadge } from '../../components/ui/MetricBadge'
import { authFetch, getApiBase } from '../../lib/auth'

// ── BattleTheme colour references ─────────────────────────────────────────────
const C_UP     = 'rgb(var(--up,    34 197 94))'
const C_DOWN   = 'rgb(var(--down,  239 68 68))'
const C_ACCENT = 'rgb(var(--accent, 56 189 248))'
const C_WARN   = 'rgb(var(--warn,  251 146 60))'
const C_MUTED  = 'rgb(var(--muted, 100 116 139))'
const C_TEXT   = 'rgb(var(--text,  226 232 240))'
const C_GOLD   = 'rgb(var(--gold,  161 138 90))'
const C_CARD   = 'rgb(var(--card,  13 19 30))'
const C_BORDER = 'rgb(var(--border, 51 65 85))'

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(url) {
  const res = await authFetch(`${getApiBase()}${url}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

const fetchDashboard    = (country) => apiFetch(`/api/macro/dashboard${country ? `?country=${country}` : ''}`)
const fetchHistory      = (id)      => apiFetch(`/api/macro/indicator/${encodeURIComponent(id)}/history?months=24`)
const fetchCalendar     = (country) => apiFetch(`/api/macro/calendar${country ? `?country=${country}` : ''}`)

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, decimals = 2) {
  if (n === null || n === undefined) return '—'
  return Number(n).toFixed(decimals)
}

function fmtDate(str) {
  if (!str) return '—'
  return str.slice(0, 7) // YYYY-MM
}

function trendColor(trend) {
  if (trend === 'up')   return C_UP
  if (trend === 'down') return C_DOWN
  return C_MUTED
}

function trendArrow(trend) {
  if (trend === 'up')   return '▲'
  if (trend === 'down') return '▼'
  return '—'
}

// Map indicator_id → decimal places
const DECIMALS = {
  A191RL1Q225SBEA: 2,
  CPIAUCSL:        1,
  PCEPILFE:        1,
  FEDFUNDS:        2,
  UNRATE:          1,
  MANBUSINDX:      1,
  DGS10:           2,
  DGS2:            2,
  DTWEXBGS:        2,
  SPREAD_10Y_2Y:   2,
}

// 4 primary KPI cards
const KPI_CARD_IDS = ['A191RL1Q225SBEA', 'CPIAUCSL', 'FEDFUNDS', 'UNRATE']
const KPI_LABELS   = {
  A191RL1Q225SBEA: 'GDP Growth',
  CPIAUCSL:        'CPI Index',
  FEDFUNDS:        'Fed Rate',
  UNRATE:          'Unemployment',
}
const KPI_UNITS    = {
  A191RL1Q225SBEA: '%',
  CPIAUCSL:        '',
  FEDFUNDS:        '%',
  UNRATE:          '%',
}

// ── Country tab ───────────────────────────────────────────────────────────────

function CountryTab({ current, onChange }) {
  const tabs = ['US', 'TW']
  return (
    <div className="flex gap-1">
      {tabs.map((c) => (
        <button
          key={c}
          onClick={() => onChange(c)}
          className="px-3 py-1 text-xs rounded-sm border transition-colors"
          style={{
            fontFamily: 'var(--font-mono)',
            borderColor: current === c ? C_ACCENT : C_BORDER,
            backgroundColor: current === c ? `${C_ACCENT}22` : 'transparent',
            color: current === c ? C_ACCENT : C_MUTED,
          }}
        >
          {c}
        </button>
      ))}
    </div>
  )
}

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({ kpi, isSelected, onClick }) {
  if (!kpi) return null
  const dec   = DECIMALS[kpi.indicator_id] ?? 2
  const color = trendColor(kpi.trend)
  const label = KPI_LABELS[kpi.indicator_id] ?? kpi.indicator_name
  const unit  = KPI_UNITS[kpi.indicator_id] ?? ''

  return (
    <button
      onClick={onClick}
      className="flex flex-col gap-1 rounded-sm border p-3 text-left transition-colors w-full"
      style={{
        borderColor:     isSelected ? C_ACCENT : C_BORDER,
        backgroundColor: isSelected ? `${C_ACCENT}0f` : `${C_CARD}cc`,
        cursor: 'pointer',
      }}
    >
      <span
        className="text-xs uppercase tracking-widest"
        style={{ fontFamily: 'var(--font-mono)', color: C_MUTED, fontSize: '10px' }}
      >
        {label}
      </span>
      <span
        className="text-xl font-bold tabular-nums"
        style={{ fontFamily: 'var(--font-data)', color: C_TEXT }}
      >
        {fmt(kpi.latest_value, dec)}{unit}
      </span>
      <div className="flex items-center gap-1 text-xs tabular-nums" style={{ color }}>
        <span>{trendArrow(kpi.trend)}</span>
        {kpi.change !== null && kpi.change !== undefined && (
          <span>{kpi.change > 0 ? '+' : ''}{fmt(kpi.change, dec)}</span>
        )}
        <span style={{ color: C_MUTED, marginLeft: 'auto' }}>{fmtDate(kpi.date)}</span>
      </div>
    </button>
  )
}

// ── Indicator chart ───────────────────────────────────────────────────────────

function IndicatorChart({ indicatorId, kpis, isMobile }) {
  const kpi = kpis?.find((k) => k.indicator_id === indicatorId)

  const { data, isLoading, error } = useQuery({
    queryKey:  ['macro', 'history', indicatorId],
    queryFn:   () => fetchHistory(indicatorId),
    staleTime: 10 * 60 * 1000,
    retry:     1,
    enabled:   !!indicatorId,
  })

  const points = data?.data ?? []
  const dec    = DECIMALS[indicatorId] ?? 2

  return (
    <DataCard
      title={kpi?.indicator_name ?? indicatorId}
      loading={isLoading}
      error={error}
      empty={!isLoading && !error && points.length === 0 ? '尚無歷史資料' : undefined}
      accentColor={C_ACCENT}
    >
      {points.length > 0 && (
        <ResponsiveContainer width="100%" height={isMobile ? 200 : 280}>
          <LineChart data={points} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={`${C_BORDER}55`} />
            <XAxis
              dataKey="date"
              tick={{ fill: C_MUTED, fontSize: 10, fontFamily: 'var(--font-data)' }}
              tickFormatter={(v) => v?.slice(0, 7)}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: C_MUTED, fontSize: 10, fontFamily: 'var(--font-data)' }}
              tickFormatter={(v) => Number(v).toFixed(dec)}
              width={48}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: C_CARD,
                border: `1px solid ${C_BORDER}`,
                borderRadius: '2px',
                fontFamily: 'var(--font-data)',
                fontSize: '11px',
                color: C_TEXT,
              }}
              formatter={(v) => [Number(v).toFixed(dec), kpi?.indicator_name ?? indicatorId]}
              labelFormatter={(l) => l}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={C_ACCENT}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3, fill: C_ACCENT }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </DataCard>
  )
}

// ── Yield Curve ───────────────────────────────────────────────────────────────

function YieldCurveSection({ dashboardData, isMobile }) {
  const yieldCurve = dashboardData?.data?.yield_curve

  const { data: histData, isLoading } = useQuery({
    queryKey:  ['macro', 'history', 'SPREAD_10Y_2Y'],
    queryFn:   () => fetchHistory('SPREAD_10Y_2Y'),
    staleTime: 10 * 60 * 1000,
    retry:     1,
  })

  const points = histData?.data ?? []
  const spread = yieldCurve?.spread_10y_2y
  const inverted = yieldCurve?.inverted

  return (
    <DataCard
      title="殖利率曲線 (10Y - 2Y Spread)"
      loading={isLoading}
      accentColor={inverted ? C_DOWN : C_UP}
    >
      {/* Spread status badge */}
      <div className="flex items-center gap-3 mb-3">
        <MetricBadge
          label="10Y-2Y Spread"
          value={spread !== null && spread !== undefined ? `${fmt(spread, 2)}%` : null}
          format="raw"
          trend={inverted ? 'down' : spread > 0 ? 'up' : 'flat'}
        />
        {inverted !== undefined && (
          <span
            className="text-xs px-2 py-0.5 rounded-sm border"
            style={{
              fontFamily: 'var(--font-mono)',
              borderColor: inverted ? C_DOWN : C_UP,
              color:        inverted ? C_DOWN : C_UP,
              backgroundColor: inverted ? `${C_DOWN}1a` : `${C_UP}1a`,
            }}
          >
            {inverted ? 'INVERTED' : 'NORMAL'}
          </span>
        )}
        {yieldCurve?.data && (
          <span className="text-xs" style={{ fontFamily: 'var(--font-data)', color: C_MUTED }}>
            2Y {fmt(yieldCurve.data.find(d => d.maturity === '2Y')?.yield, 2)}%&nbsp;
            /&nbsp;10Y {fmt(yieldCurve.data.find(d => d.maturity === '10Y')?.yield, 2)}%
          </span>
        )}
      </div>

      {/* Historical spread chart */}
      {points.length > 0 && (
        <ResponsiveContainer width="100%" height={isMobile ? 200 : 240}>
          <LineChart data={points} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={`${C_BORDER}55`} />
            <XAxis
              dataKey="date"
              tick={{ fill: C_MUTED, fontSize: 10, fontFamily: 'var(--font-data)' }}
              tickFormatter={(v) => v?.slice(0, 7)}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={{ fill: C_MUTED, fontSize: 10, fontFamily: 'var(--font-data)' }}
              tickFormatter={(v) => `${Number(v).toFixed(2)}%`}
              width={52}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: C_CARD,
                border: `1px solid ${C_BORDER}`,
                borderRadius: '2px',
                fontFamily: 'var(--font-data)',
                fontSize: '11px',
                color: C_TEXT,
              }}
              formatter={(v) => [`${Number(v).toFixed(2)}%`, '10Y-2Y Spread']}
              labelFormatter={(l) => l}
            />
            {/* Zero line — inversion boundary */}
            <ReferenceLine
              y={0}
              stroke={C_DOWN}
              strokeDasharray="4 2"
              strokeWidth={1}
              label={{ value: '0%', fill: C_DOWN, fontSize: 9, fontFamily: 'var(--font-mono)' }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={inverted ? C_DOWN : C_UP}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 3 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </DataCard>
  )
}

// ── Economic Calendar ─────────────────────────────────────────────────────────

const IMPORTANCE_COLOR = {
  critical: C_DOWN,
  high:     C_WARN,
  medium:   C_ACCENT,
  low:      C_MUTED,
}

function EconomicCalendar({ country }) {
  const { data, isLoading, error } = useQuery({
    queryKey:  ['macro', 'calendar', country],
    queryFn:   () => fetchCalendar(country),
    staleTime: 60 * 60 * 1000,
    retry:     1,
  })

  const events = data?.data ?? []

  return (
    <DataCard
      title="經濟日曆"
      loading={isLoading}
      error={error}
      empty={!isLoading && !error && events.length === 0 ? '暫無即將到來的事件' : undefined}
      accentColor={C_GOLD}
    >
      <ul className="space-y-2">
        {events.slice(0, 10).map((ev) => {
          const color = IMPORTANCE_COLOR[ev.importance] ?? C_MUTED
          return (
            <li
              key={`${ev.date}-${ev.event}`}
              className="flex items-start gap-3 pb-2 border-b last:border-b-0"
              style={{ borderColor: `${C_BORDER}55` }}
            >
              {/* Date pill */}
              <span
                className="shrink-0 text-xs tabular-nums px-1.5 py-0.5 rounded-sm border"
                style={{
                  fontFamily: 'var(--font-data)',
                  borderColor: `${color}66`,
                  color,
                  backgroundColor: `${color}11`,
                  minWidth: '74px',
                  textAlign: 'center',
                }}
              >
                {ev.date}
              </span>

              {/* Event info */}
              <div className="flex-1 min-w-0">
                <span
                  className="text-xs"
                  style={{ fontFamily: 'var(--font-ui)', color: C_TEXT }}
                >
                  {ev.event}
                </span>
                <div className="flex items-center gap-2 mt-0.5">
                  <span
                    className="text-xs uppercase"
                    style={{ fontFamily: 'var(--font-mono)', color: C_MUTED, fontSize: '9px' }}
                  >
                    {ev.country}
                  </span>
                  <span
                    className="text-xs uppercase"
                    style={{ fontFamily: 'var(--font-mono)', color, fontSize: '9px' }}
                  >
                    {ev.importance}
                  </span>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </DataCard>
  )
}

// ── All indicators list (non-KPI) ─────────────────────────────────────────────

function IndicatorTable({ kpis, selectedId, onSelect }) {
  return (
    <DataCard title="全部指標" accentColor={C_MUTED}>
      <ul className="space-y-1">
        {kpis.map((kpi) => {
          const dec   = DECIMALS[kpi.indicator_id] ?? 2
          const color = trendColor(kpi.trend)
          const isSelected = kpi.indicator_id === selectedId
          return (
            <li key={kpi.indicator_id}>
              <button
                onClick={() => onSelect(kpi.indicator_id)}
                className="w-full flex items-center justify-between px-2 py-1.5 rounded-sm text-left transition-colors"
                style={{
                  backgroundColor: isSelected ? `${C_ACCENT}15` : 'transparent',
                  borderLeft: isSelected ? `2px solid ${C_ACCENT}` : '2px solid transparent',
                }}
              >
                <span className="text-xs" style={{ fontFamily: 'var(--font-ui)', color: C_TEXT }}>
                  {kpi.indicator_name}
                </span>
                <div className="flex items-center gap-2 shrink-0">
                  <span
                    className="text-xs tabular-nums"
                    style={{ fontFamily: 'var(--font-data)', color: C_TEXT }}
                  >
                    {fmt(kpi.latest_value, dec)}
                  </span>
                  <span className="text-xs" style={{ color }}>
                    {trendArrow(kpi.trend)}
                  </span>
                </div>
              </button>
            </li>
          )
        })}
        {kpis.length === 0 && (
          <li className="text-xs py-2 text-center" style={{ color: C_MUTED }}>
            無資料
          </li>
        )}
      </ul>
    </DataCard>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MacroAnalysis() {
  const [country, setCountry]           = useState('US')
  const [selectedId, setSelectedId]     = useState(KPI_CARD_IDS[2]) // default: FEDFUNDS

  // Detect mobile via window width — use state + resize listener so it updates on resize
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < 640
  )
  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < 640)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const { data: dashboardData, isLoading: dashLoading, error: dashError } = useQuery({
    queryKey:  ['macro', 'dashboard', country],
    queryFn:   () => fetchDashboard(country),
    staleTime: 5 * 60 * 1000,
    retry:     1,
  })

  const kpis   = dashboardData?.data?.kpis   ?? []
  const kpiIds = KPI_CARD_IDS.filter((id) => kpis.some((k) => k.indicator_id === id))

  const handleKpiClick = useCallback((id) => {
    setSelectedId(id)
  }, [])

  return (
    <div data-testid="macro-analysis" className="space-y-4 px-0 sm:px-1">

      {/* ── Header ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-2 border-b border-th-border">
        <div>
          <h1
            className="text-base font-bold tracking-wide"
            style={{ fontFamily: 'var(--font-data)', color: C_ACCENT }}
          >
            宏觀經濟分析
          </h1>
          <p className="text-xs mt-0.5" style={{ fontFamily: 'var(--font-ui)', color: C_MUTED }}>
            FRED API + 台灣數據 · 每週一 08:00 TWN 更新
          </p>
        </div>
        <CountryTab current={country} onChange={(c) => { setCountry(c); setSelectedId(null) }} />
      </div>

      {/* ── 4 KPI Cards ── */}
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 140px), 1fr))' }}
      >
        {dashLoading
          ? KPI_CARD_IDS.map((id) => (
              <div
                key={id}
                className="rounded-sm border p-3 animate-pulse"
                style={{ borderColor: C_BORDER, backgroundColor: `${C_BORDER}22`, minHeight: '80px' }}
              />
            ))
          : dashError
          ? (
            <div
              className="col-span-full text-xs py-4 text-center rounded-sm border"
              style={{ borderColor: C_DOWN, color: C_DOWN }}
            >
              無法載入宏觀指標：{dashError.message}
            </div>
          )
          : KPI_CARD_IDS.map((id) => {
              const kpi = kpis.find((k) => k.indicator_id === id)
              return (
                <KpiCard
                  key={id}
                  kpi={kpi ?? { indicator_id: id, indicator_name: KPI_LABELS[id], latest_value: null, trend: 'flat', date: null, change: null }}
                  isSelected={selectedId === id}
                  onClick={() => handleKpiClick(id)}
                />
              )
            })
        }
      </div>

      {/* ── Selected Indicator History Chart ── */}
      {selectedId && (
        <IndicatorChart
          indicatorId={selectedId}
          kpis={kpis}
          isMobile={isMobile}
        />
      )}

      {/* ── Yield Curve section ── */}
      <YieldCurveSection dashboardData={dashboardData} isMobile={isMobile} />

      {/* ── Bottom: Indicator table + Calendar side by side ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* All Indicators list */}
        <IndicatorTable
          kpis={kpis}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />

        {/* Economic Calendar */}
        <EconomicCalendar country={country} />

      </div>

    </div>
  )
}
