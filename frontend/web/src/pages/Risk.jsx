import React, { useEffect, useState, useCallback } from 'react'
import {
  Treemap,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
} from 'recharts'
import { DataCard } from '../components/ui/DataCard'
import { MetricBadge } from '../components/ui/MetricBadge'
import { AlertBadge } from '../components/ui/AlertBadge'
import { authFetch, getApiBase } from '../lib/auth'

// ── BattleTheme colour palette ──────────────────────────────────────────────
const SECTOR_COLORS = [
  'rgb(var(--accent))',
  '#4ade80',
  '#60a5fa',
  '#f59e0b',
  '#a78bfa',
  '#f87171',
  '#34d399',
  '#fb923c',
  '#38bdf8',
]

// ── Data fetching helpers ────────────────────────────────────────────────────
async function fetchRiskSnapshot(signal) {
  const res = await authFetch(`${getApiBase()}/api/risk/snapshot`, { signal })
  if (!res.ok) throw new Error(`風險快照載入失敗 (${res.status})`)
  return res.json()
}

async function fetchStressTest(signal) {
  const res = await authFetch(`${getApiBase()}/api/risk/stress-test`, { signal })
  if (!res.ok) throw new Error(`壓力測試載入失敗 (${res.status})`)
  return res.json()
}

// ── KPI Card ─────────────────────────────────────────────────────────────────
function KpiCard({ label, value, subtext, accentColor, warn }) {
  return (
    <div
      className="flex flex-col gap-1 px-4 py-3 rounded-sm border border-th-border border-l-2 bg-th-card shadow-panel"
      style={{ borderLeftColor: accentColor || 'rgb(var(--accent))' }}
    >
      <span
        className="text-xs tracking-widest uppercase text-th-muted"
        style={{ fontFamily: 'var(--font-mono)', fontSize: '10px' }}
      >
        {label}
      </span>
      <span
        className="text-2xl tabular-nums font-semibold"
        style={{
          fontFamily: 'var(--font-data)',
          color: warn ? 'rgb(var(--danger))' : 'rgb(var(--text))',
        }}
      >
        {value}
      </span>
      {subtext && (
        <span
          className="text-xs text-th-muted"
          style={{ fontFamily: 'var(--font-ui)' }}
        >
          {subtext}
        </span>
      )}
    </div>
  )
}

// ── Treemap custom content ────────────────────────────────────────────────────
function TreemapContent({ x, y, width, height, name, weight_pct }) {
  if (width < 30 || height < 20) return null
  return (
    <g>
      <rect
        x={x + 1}
        y={y + 1}
        width={width - 2}
        height={height - 2}
        rx={2}
        fill="rgba(var(--accent), 0.15)"
        stroke="rgb(var(--accent))"
        strokeWidth={1}
      />
      {width > 50 && height > 30 && (
        <>
          <text
            x={x + width / 2}
            y={y + height / 2 - 6}
            textAnchor="middle"
            fill="rgb(var(--text))"
            fontSize={Math.min(12, width / 6)}
            fontFamily="var(--font-mono)"
          >
            {name}
          </text>
          <text
            x={x + width / 2}
            y={y + height / 2 + 10}
            textAnchor="middle"
            fill="rgb(var(--muted))"
            fontSize={Math.min(10, width / 7)}
            fontFamily="var(--font-data)"
          >
            {weight_pct != null ? `${weight_pct}%` : ''}
          </text>
        </>
      )}
    </g>
  )
}

// ── Sector Pie tooltip ────────────────────────────────────────────────────────
function SectorTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div
      className="px-3 py-2 rounded-sm border border-th-border bg-th-card shadow-panel text-xs"
      style={{ fontFamily: 'var(--font-ui)' }}
    >
      <div className="font-medium text-th-text">{d.sector}</div>
      <div className="text-th-muted mt-0.5">{d.weight_pct}%</div>
    </div>
  )
}

// ── Correlation Heatmap ───────────────────────────────────────────────────────
function CorrelationHeatmap({ sectors, matrix }) {
  if (!sectors?.length || !matrix) return null

  function corrColor(v) {
    // v: -1 → 1
    // negative → blue tones, positive → red/amber tones
    const clamped = Math.max(-1, Math.min(1, v))
    if (clamped >= 1.0) return 'rgba(var(--danger), 0.85)'
    if (clamped > 0.7) return 'rgba(var(--danger), 0.55)'
    if (clamped > 0.4) return 'rgba(var(--warn), 0.50)'
    if (clamped > 0.1) return 'rgba(var(--warn), 0.25)'
    if (clamped >= 0) return 'rgba(var(--muted), 0.15)'
    return 'rgba(var(--accent), 0.25)'
  }

  const cellSize = Math.min(48, Math.floor(260 / sectors.length))

  return (
    <div className="overflow-x-auto">
      <div
        className="inline-grid gap-px"
        style={{
          gridTemplateColumns: `auto repeat(${sectors.length}, ${cellSize}px)`,
        }}
      >
        {/* Header row */}
        <div style={{ width: cellSize }} />
        {sectors.map((s) => (
          <div
            key={s}
            className="text-th-muted text-center truncate"
            style={{
              fontSize: '9px',
              fontFamily: 'var(--font-mono)',
              lineHeight: `${cellSize}px`,
              height: cellSize,
              writingMode: 'vertical-rl',
              transform: 'rotate(180deg)',
              paddingBottom: '4px',
            }}
          >
            {s}
          </div>
        ))}

        {/* Data rows */}
        {sectors.map((row) => (
          <React.Fragment key={row}>
            <div
              className="text-th-muted flex items-center justify-end pr-1 truncate"
              style={{ fontSize: '9px', fontFamily: 'var(--font-mono)', height: cellSize }}
            >
              {row}
            </div>
            {sectors.map((col) => {
              const v = matrix[row]?.[col] ?? 0
              return (
                <div
                  key={col}
                  title={`${row} × ${col}: ${v.toFixed(2)}`}
                  className="flex items-center justify-center rounded-sm"
                  style={{
                    width: cellSize,
                    height: cellSize,
                    backgroundColor: corrColor(v),
                    fontSize: '9px',
                    fontFamily: 'var(--font-data)',
                    color: 'rgb(var(--text))',
                  }}
                >
                  {v.toFixed(2)}
                </div>
              )
            })}
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

// ── Stop-loss Table ───────────────────────────────────────────────────────────
function StopLossTable({ rows }) {
  if (!rows?.length) return (
    <p className="text-xs text-th-muted py-4 text-center" style={{ fontFamily: 'var(--font-ui)' }}>
      無持倉資料
    </p>
  )

  const sorted = [...rows].sort((a, b) => a.distance_pct - b.distance_pct)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr className="border-b border-th-border text-th-muted">
            <th className="text-left py-1.5 pr-3">代號</th>
            <th className="text-right py-1.5 pr-3">現價</th>
            <th className="text-right py-1.5 pr-3">停損價</th>
            <th className="text-right py-1.5">距停損</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const danger = r.breached
            const warn = !r.breached && r.distance_pct < 3
            const textColor = danger
              ? 'rgb(var(--danger))'
              : warn
              ? 'rgb(var(--warn))'
              : 'rgb(var(--text))'

            return (
              <tr key={r.symbol} className="border-b border-th-border/40">
                <td className="py-1.5 pr-3 font-medium" style={{ color: textColor }}>
                  {r.symbol}
                  {danger && (
                    <span
                      className="ml-1 text-xs animate-lava-pulse"
                      style={{ color: 'rgb(var(--danger))' }}
                    >
                      ✕
                    </span>
                  )}
                </td>
                <td className="text-right py-1.5 pr-3 tabular-nums" style={{ color: 'rgb(var(--text))' }}>
                  {r.current_price?.toLocaleString('zh-TW')}
                </td>
                <td className="text-right py-1.5 pr-3 tabular-nums" style={{ color: 'rgb(var(--muted))' }}>
                  {r.stop_loss_price?.toLocaleString('zh-TW')}
                </td>
                <td
                  className="text-right py-1.5 tabular-nums font-medium"
                  style={{ color: textColor }}
                >
                  {danger ? '已觸發' : `${r.distance_pct?.toFixed(2)}%`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── Stress Test Cards ─────────────────────────────────────────────────────────
function StressCard({ scenario }) {
  const positive = scenario.impact_twd >= 0
  const color = positive ? 'rgb(var(--up))' : 'rgb(var(--danger))'
  const borderColor = positive ? 'rgba(var(--up), 0.4)' : 'rgba(var(--danger), 0.4)'
  const bg = positive ? 'rgba(var(--up), 0.06)' : 'rgba(var(--danger), 0.06)'

  const formatted = new Intl.NumberFormat('zh-TW', {
    style: 'currency',
    currency: 'TWD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.abs(scenario.impact_twd))

  return (
    <div
      className="rounded-sm border p-3 flex flex-col gap-1.5"
      style={{ borderColor, backgroundColor: bg }}
    >
      <div
        className="text-xs font-medium"
        style={{ fontFamily: 'var(--font-ui)', color: 'rgb(var(--text))' }}
      >
        {scenario.name}
      </div>
      <div
        className="text-xs text-th-muted leading-relaxed"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        {scenario.description}
      </div>
      <div className="flex items-baseline gap-2 mt-1">
        <span
          className="text-lg tabular-nums font-semibold"
          style={{ fontFamily: 'var(--font-data)', color }}
        >
          {positive ? '+' : '-'}{formatted}
        </span>
        <span
          className="text-xs tabular-nums"
          style={{ fontFamily: 'var(--font-data)', color }}
        >
          ({positive ? '+' : ''}{scenario.impact_pct?.toFixed(2)}%)
        </span>
      </div>
    </div>
  )
}

// ── Main Risk Page ────────────────────────────────────────────────────────────
export default function Risk() {
  const [snapshot, setSnapshot] = useState(null)
  const [stress, setStress] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    const ctrl = new AbortController()
    try {
      const [snap, st] = await Promise.all([
        fetchRiskSnapshot(ctrl.signal),
        fetchStressTest(ctrl.signal),
      ])
      setSnapshot(snap)
      setStress(st)
    } catch (e) {
      if (e?.name !== 'AbortError') setError(e?.message || '載入失敗')
    } finally {
      setLoading(false)
    }
    return () => ctrl.abort()
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // ── Derived data ─────────────────────────────────────────────────────────
  const kpis = snapshot?.kpis ?? {}
  const positions = snapshot?.positions ?? []
  const sectorAlloc = snapshot?.sector_allocation ?? []
  const corrData = snapshot?.correlation_matrix ?? {}
  const stopLosses = snapshot?.stop_losses ?? []
  const scenarios = stress?.scenarios ?? []

  const treemapData = positions.map((p) => ({
    name: p.symbol,
    size: p.notional,
    weight_pct: p.weight_pct,
  }))

  const sectorPieData = sectorAlloc.map((s, i) => ({
    ...s,
    fill: SECTOR_COLORS[i % SECTOR_COLORS.length],
  }))

  const breachedCount = stopLosses.filter((s) => s.breached).length
  const nearStopCount = stopLosses.filter((s) => !s.breached && s.distance_pct < 3).length

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4 p-4">
      {/* Page title */}
      <h1
        className="text-lg font-medium text-th-text"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        風險管理
      </h1>

      {/* Alerts */}
      {!loading && !error && breachedCount > 0 && (
        <AlertBadge
          level="red"
          message={`${breachedCount} 個持倉已觸發停損 — 請立即檢視`}
        />
      )}
      {!loading && !error && nearStopCount > 0 && breachedCount === 0 && (
        <AlertBadge
          level="yellow"
          message={`${nearStopCount} 個持倉距停損不足 3% — 注意風險`}
        />
      )}

      {/* ── Top KPI row ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <KpiCard
          label="VaR 95% (日)"
          value={
            loading ? '—'
            : kpis.var_95_twd != null
            ? new Intl.NumberFormat('zh-TW', {
                style: 'currency',
                currency: 'TWD',
                minimumFractionDigits: 0,
                maximumFractionDigits: 0,
              }).format(kpis.var_95_twd)
            : '—'
          }
          subtext={kpis.var_95_pct != null ? `${kpis.var_95_pct}% of notional` : undefined}
          accentColor="rgb(var(--danger))"
          warn={kpis.var_95_pct > 5}
        />
        <KpiCard
          label="最大回撤"
          value={loading ? '—' : kpis.max_drawdown_pct != null ? `${kpis.max_drawdown_pct}%` : '—'}
          subtext="歷史峰值至谷值"
          accentColor="rgb(var(--warn))"
          warn={kpis.max_drawdown_pct > 15}
        />
        <KpiCard
          label="集中度分數"
          value={loading ? '—' : kpis.concentration_score != null ? `${kpis.concentration_score}` : '—'}
          subtext={
            kpis.concentration_score == null ? undefined
            : kpis.concentration_score >= 70 ? '高集中 — 建議分散'
            : kpis.concentration_score >= 40 ? '中等集中'
            : '分散良好'
          }
          accentColor={
            kpis.concentration_score >= 70
              ? 'rgb(var(--danger))'
              : kpis.concentration_score >= 40
              ? 'rgb(var(--warn))'
              : 'rgb(var(--up))'
          }
          warn={kpis.concentration_score >= 70}
        />
      </div>

      {/* ── Treemap + Sector Pie row ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Treemap */}
        <DataCard title="持倉權重 Treemap" loading={loading} error={error} empty={!loading && !error && !positions.length ? '無持倉資料' : undefined}>
          {positions.length > 0 && (
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <Treemap
                  data={treemapData}
                  dataKey="size"
                  aspectRatio={4 / 3}
                  content={<TreemapContent />}
                />
              </ResponsiveContainer>
            </div>
          )}
        </DataCard>

        {/* Sector pie */}
        <DataCard title="板塊配置" loading={loading} error={error} empty={!loading && !error && !sectorAlloc.length ? '無配置資料' : undefined}>
          {sectorAlloc.length > 0 && (
            <div style={{ height: 260 }}>
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sectorPieData}
                    dataKey="weight_pct"
                    nameKey="sector"
                    cx="50%"
                    cy="50%"
                    outerRadius={90}
                    innerRadius={45}
                    paddingAngle={2}
                    label={({ sector, weight_pct }) =>
                      weight_pct > 5 ? `${sector} ${weight_pct}%` : ''
                    }
                    labelLine={false}
                  >
                    {sectorPieData.map((entry, i) => (
                      <Cell key={entry.sector} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip content={<SectorTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </DataCard>
      </div>

      {/* ── Correlation heatmap ────────────────────────────────────────────── */}
      <DataCard
        title="板塊相關性矩陣"
        loading={loading}
        error={error}
        empty={!loading && !error && !corrData.sectors?.length ? '無相關性資料' : undefined}
      >
        {corrData.sectors?.length > 0 && (
          <CorrelationHeatmap
            sectors={corrData.sectors}
            matrix={corrData.matrix}
          />
        )}
      </DataCard>

      {/* ── Stop-loss tracking ─────────────────────────────────────────────── */}
      <DataCard
        title="停損追蹤"
        loading={loading}
        error={error}
        empty={!loading && !error && !stopLosses.length ? '無持倉資料' : undefined}
      >
        <StopLossTable rows={stopLosses} />
      </DataCard>

      {/* ── Stress test scenarios ──────────────────────────────────────────── */}
      <DataCard
        title="壓力測試情境"
        loading={loading}
        error={error}
        empty={!loading && !error && !scenarios.length ? '無情境資料' : undefined}
      >
        {scenarios.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {scenarios.map((s) => (
              <StressCard key={s.id} scenario={s} />
            ))}
          </div>
        )}
      </DataCard>

      {/* Refresh hint */}
      {!loading && !error && (
        <p
          className="text-xs text-th-muted text-right"
          style={{ fontFamily: 'var(--font-mono)' }}
        >
          快取 5 分鐘 ·{' '}
          <button
            onClick={load}
            className="underline hover:opacity-70 transition-opacity"
            style={{ color: 'rgb(var(--accent))' }}
          >
            重新整理
          </button>
        </p>
      )}
    </div>
  )
}
