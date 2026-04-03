import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { DataCard } from '../../components/ui/DataCard'
import { MetricBadge } from '../../components/ui/MetricBadge'

// BattleTheme colour references — matches CSS variables in the design system
const COLOR_UP = 'rgb(var(--up, 34 197 94))'
const COLOR_DOWN = 'rgb(var(--down, 239 68 68))'
const COLOR_MUTED = 'rgb(var(--muted, 120 120 120))'
const COLOR_ACCENT = 'rgb(var(--accent, 56 189 248))'

const MAX_SCATTER_POINTS = 300

const DEFAULT_FILTERS = {
  rsiMin: 0,
  rsiMax: 100,
  volumeRatioMin: 0,
  foreignDaysMin: 0,
  label: 'all',
}

function applyFilters(item, filters) {
  const { rsiMin, rsiMax, volumeRatioMin, foreignDaysMin, label } = filters
  if (label !== 'all' && item.label !== label) return false
  if (item.rsi14 !== null && item.rsi14 !== undefined) {
    if (item.rsi14 < rsiMin || item.rsi14 > rsiMax) return false
  }
  if (volumeRatioMin > 0 && (item.volume_ratio ?? 0) < volumeRatioMin) return false
  if (foreignDaysMin > 0 && (item.foreign_consecutive ?? 0) < foreignDaysMin) return false
  return true
}

function ScatterTooltipContent({ active, payload }) {
  if (!active || !payload || !payload.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div
      className="bg-th-card border border-th-border rounded-sm shadow-panel p-2 text-xs"
      style={{ fontFamily: 'var(--font-mono)', minWidth: 160 }}
    >
      <div className="font-medium text-th-text mb-1">
        {d.symbol} <span className="text-th-muted font-normal">{d.name}</span>
      </div>
      <div className="space-y-0.5 text-th-muted">
        <div>RSI14: <span className="text-th-text">{d.rsi14 ?? '—'}</span></div>
        <div>量比: <span className="text-th-text">{d.volume_ratio != null ? `${d.volume_ratio}x` : '—'}</span></div>
        <div>外資連買: <span className="text-th-text">{d.foreign_consecutive ?? 0} 日</span></div>
        <div>
          5日漲跌:{' '}
          <span style={{ color: (d.change_5d ?? 0) >= 0 ? COLOR_UP : COLOR_DOWN }}>
            {d.change_5d != null ? `${d.change_5d > 0 ? '+' : ''}${d.change_5d}%` : '—'}
          </span>
        </div>
        <div>評分: <span className="text-th-text">{d.score}</span></div>
        {d.sector && <div>板塊: <span className="text-th-text">{d.sector}</span></div>}
      </div>
    </div>
  )
}

function FilterBtn({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={[
        'px-2 py-1 text-xs rounded-sm border transition-colors',
        active
          ? 'border-th-accent bg-th-accent/10 text-th-accent'
          : 'border-th-border text-th-muted hover:border-th-accent/50 hover:text-th-text',
      ].join(' ')}
      style={{ fontFamily: 'var(--font-ui)' }}
    >
      {children}
    </button>
  )
}

export default function Screener() {
  const navigate = useNavigate()
  const [scatterData, setScatterData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch('/api/screener/scatter')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((json) => {
        if (cancelled) return
        setScatterData(Array.isArray(json.data) ? json.data : [])
        setLoading(false)
      })
      .catch((e) => {
        if (cancelled) return
        setError(e.message || '資料載入失敗')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const handleSymbolClick = useCallback(
    (symbol) => navigate(`/research/stock?symbol=${symbol}`),
    [navigate],
  )

  const filtered = scatterData.filter((item) => applyFilters(item, filters))
  const truncated = filtered.length > MAX_SCATTER_POINTS
  const displayData = truncated ? filtered.slice(0, MAX_SCATTER_POINTS) : filtered
  const tableData = [...filtered].sort((a, b) => b.score - a.score)

  const setRsiRange = (min, max) => setFilters((f) => ({ ...f, rsiMin: min, rsiMax: max }))
  const setVolumeThreshold = (v) => setFilters((f) => ({ ...f, volumeRatioMin: v }))
  const setForeignDays = (d) => setFilters((f) => ({ ...f, foreignDaysMin: d }))
  const setLabel = (l) => setFilters((f) => ({ ...f, label: l }))
  const resetFilters = () => setFilters(DEFAULT_FILTERS)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-medium text-th-text" style={{ fontFamily: 'var(--font-ui)' }}>
        市場選股器
      </h1>

      {/* Filter bar */}
      <DataCard title="條件篩選">
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs text-th-muted mr-1" style={{ fontFamily: 'var(--font-ui)' }}>類型</span>
          {[
            { key: 'all', label: '全部' },
            { key: 'short_term', label: '短線' },
            { key: 'long_term', label: '長線' },
          ].map(({ key, label }) => (
            <FilterBtn key={key} active={filters.label === key} onClick={() => setLabel(key)}>
              {label}
            </FilterBtn>
          ))}

          <div className="w-px h-4 bg-th-border mx-1" />

          <span className="text-xs text-th-muted mr-1" style={{ fontFamily: 'var(--font-ui)' }}>RSI14</span>
          {[
            { label: '超賣 ≤30', min: 0, max: 30 },
            { label: '30–50', min: 30, max: 50 },
            { label: '50–70', min: 50, max: 70 },
            { label: '超買 ≥70', min: 70, max: 100 },
          ].map(({ label, min, max }) => (
            <FilterBtn
              key={label}
              active={filters.rsiMin === min && filters.rsiMax === max}
              onClick={() =>
                filters.rsiMin === min && filters.rsiMax === max
                  ? setRsiRange(0, 100)
                  : setRsiRange(min, max)
              }
            >
              {label}
            </FilterBtn>
          ))}

          <div className="w-px h-4 bg-th-border mx-1" />

          <span className="text-xs text-th-muted mr-1" style={{ fontFamily: 'var(--font-ui)' }}>量比</span>
          {[1.5, 2, 3].map((v) => (
            <FilterBtn
              key={v}
              active={filters.volumeRatioMin === v}
              onClick={() =>
                filters.volumeRatioMin === v ? setVolumeThreshold(0) : setVolumeThreshold(v)
              }
            >
              {`≥${v}x`}
            </FilterBtn>
          ))}

          <div className="w-px h-4 bg-th-border mx-1" />

          <span className="text-xs text-th-muted mr-1" style={{ fontFamily: 'var(--font-ui)' }}>外資連買</span>
          {[2, 3, 5].map((d) => (
            <FilterBtn
              key={d}
              active={filters.foreignDaysMin === d}
              onClick={() =>
                filters.foreignDaysMin === d ? setForeignDays(0) : setForeignDays(d)
              }
            >
              {`≥${d}日`}
            </FilterBtn>
          ))}

          <div className="flex-1" />

          <button
            onClick={resetFilters}
            className="text-xs text-th-muted hover:text-th-text transition-colors"
            style={{ fontFamily: 'var(--font-ui)' }}
          >
            重置
          </button>

          <span className="text-xs text-th-muted tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>
            {filtered.length} 檔
          </span>
        </div>
      </DataCard>

      {/* Scatter chart — hidden on mobile */}
      <div className="hidden md:block">
        <DataCard
          title="散佈圖 — RSI14 vs 量比（點大小 = 評分）"
          loading={loading}
          error={error}
          empty={!loading && !error && displayData.length === 0 ? '無符合條件的標的' : undefined}
        >
          {truncated && (
            <div className="text-xs text-th-muted mb-2" style={{ fontFamily: 'var(--font-ui)' }}>
              顯示前 {MAX_SCATTER_POINTS} 筆（共 {filtered.length} 筆）
            </div>
          )}
          {!loading && !error && displayData.length > 0 && (
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(var(--border, 60 60 60), 0.4)" />
                  <XAxis
                    type="number"
                    dataKey="rsi14"
                    name="RSI14"
                    domain={[0, 100]}
                    tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: 'rgb(var(--muted, 120 120 120))' }}
                    label={{ value: 'RSI 14', position: 'insideBottomRight', offset: -4, fontSize: 10, fill: 'rgb(var(--muted))' }}
                  />
                  <YAxis
                    type="number"
                    dataKey="volume_ratio"
                    name="量比"
                    tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: 'rgb(var(--muted, 120 120 120))' }}
                    label={{ value: '量比', angle: -90, position: 'insideLeft', offset: 8, fontSize: 10, fill: 'rgb(var(--muted))' }}
                  />
                  <Tooltip
                    content={<ScatterTooltipContent />}
                    cursor={{ strokeDasharray: '3 3', stroke: COLOR_MUTED }}
                  />
                  <Scatter
                    data={displayData}
                    isAnimationActive={false}
                    onClick={(payload) => {
                      if (payload && payload.symbol) handleSymbolClick(payload.symbol)
                    }}
                    style={{ cursor: 'pointer' }}
                  >
                    {displayData.map((entry, index) => {
                      const positive = (entry.change_5d ?? 0) >= 0
                      const r = Math.max(4, Math.min(16, Math.round((entry.score ?? 0.5) * 16)))
                      return (
                        <Cell
                          key={`cell-${index}`}
                          fill={positive ? COLOR_UP : COLOR_DOWN}
                          fillOpacity={0.75}
                          r={r}
                        />
                      )
                    })}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
        </DataCard>
      </div>

      {/* Ranked table */}
      <DataCard
        title="候選標的排名"
        loading={loading}
        error={error}
        empty={!loading && !error && tableData.length === 0 ? '無符合條件的標的' : undefined}
      >
        {!loading && !error && tableData.length > 0 && (
          <div className="overflow-x-auto -mx-3 -mb-3">
            <table className="w-full text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
              <thead>
                <tr className="border-b border-th-border">
                  {['#', '代碼', '名稱', '類型', '評分', 'RSI14', '量比', '外資連買', '5日漲跌'].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2 text-left text-th-muted font-medium whitespace-nowrap"
                      style={{ fontFamily: 'var(--font-ui)', fontSize: 10 }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableData.map((item, idx) => {
                  const change5d = item.change_5d ?? null
                  const changePositive = change5d !== null && change5d >= 0
                  return (
                    <tr
                      key={`${item.symbol}-${item.label}`}
                      className="border-b border-th-border/50 hover:bg-th-accent/5 cursor-pointer transition-colors"
                      onClick={() => handleSymbolClick(item.symbol)}
                    >
                      <td className="px-3 py-2 text-th-muted tabular-nums">{idx + 1}</td>
                      <td className="px-3 py-2 font-medium text-th-accent tabular-nums">{item.symbol}</td>
                      <td className="px-3 py-2 text-th-text max-w-[8rem] truncate" style={{ fontFamily: 'var(--font-ui)' }}>
                        {item.name}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className="px-1.5 py-0.5 rounded-sm text-[10px]"
                          style={{
                            background: item.label === 'short_term'
                              ? 'rgba(var(--accent, 56 189 248), 0.12)'
                              : 'rgba(var(--up, 34 197 94), 0.12)',
                            color: item.label === 'short_term' ? COLOR_ACCENT : COLOR_UP,
                            fontFamily: 'var(--font-ui)',
                          }}
                        >
                          {item.label === 'short_term' ? '短線' : '長線'}
                        </span>
                      </td>
                      <td className="px-3 py-2 tabular-nums text-th-text">{item.score}</td>
                      <td className="px-3 py-2 tabular-nums text-th-text">{item.rsi14 ?? '—'}</td>
                      <td className="px-3 py-2 tabular-nums text-th-text">
                        {item.volume_ratio != null ? `${item.volume_ratio}x` : '—'}
                      </td>
                      <td className="px-3 py-2 tabular-nums text-th-text">
                        {item.foreign_consecutive > 0 ? `${item.foreign_consecutive}日` : '—'}
                      </td>
                      <td
                        className="px-3 py-2 tabular-nums"
                        style={{ color: change5d === null ? COLOR_MUTED : changePositive ? COLOR_UP : COLOR_DOWN }}
                      >
                        {change5d !== null ? `${change5d > 0 ? '+' : ''}${change5d}%` : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </DataCard>
    </div>
  )
}
