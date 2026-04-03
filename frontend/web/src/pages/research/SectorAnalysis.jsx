import React, { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  PieChart,
  Pie,
  Cell,
  Tooltip as ReTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from 'recharts'
import { DataCard } from '../../components/ui/DataCard'
import { MetricBadge } from '../../components/ui/MetricBadge'
import { SentimentIndicator } from '../../components/ui/SentimentIndicator'
import { authFetch, getApiBase } from '../../lib/auth'

// ---------------------------------------------------------------------------
// BattleTheme colour refs
// ---------------------------------------------------------------------------
const C_UP     = 'rgb(var(--up, 34 197 94))'
const C_DOWN   = 'rgb(var(--down, 239 68 68))'
const C_MUTED  = 'rgb(var(--muted, 120 120 120))'
const C_ACCENT = 'rgb(var(--accent, 56 189 248))'
const C_WARN   = 'rgb(var(--warn, 234 179 8))'

// PieChart palette（最多 12 色，其餘歸入「其他」）
const PIE_COLORS = [
  '#38bdf8', '#34d399', '#fb923c', '#a78bfa',
  '#f472b6', '#facc15', '#4ade80', '#f87171',
  '#818cf8', '#2dd4bf', '#e879f9', '#94a3b8',
]

const MERGE_THRESHOLD = 0.05   // 市值佔比 < 5% 歸入「其他」

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtBn(v) {
  // 格式化億元
  if (v == null) return '—'
  const b = v / 1e8
  return b >= 1000 ? `${(b / 1000).toFixed(1)}千億` : `${b.toFixed(0)}億`
}

function fmtPct(v, showPlus = true) {
  if (v == null) return '—'
  const s = Number(v).toFixed(2)
  return showPlus && v > 0 ? `+${s}%` : `${s}%`
}

function fmtFlow(v) {
  if (v == null) return '—'
  const b = v / 1e8
  return `${b >= 0 ? '+' : ''}${b.toFixed(1)}億`
}

function changeTrend(v) {
  if (v == null) return 'flat'
  return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'
}

/**
 * 將市值小於 threshold 的產業合併成「其他」
 */
function mergePieData(sectors) {
  const total = sectors.reduce((s, d) => s + (d.market_cap || 0), 0)
  if (total === 0) return sectors.map((d, i) => ({ ...d, color: PIE_COLORS[i % PIE_COLORS.length] }))

  const main = []
  let otherCap = 0
  let otherCount = 0

  sectors.forEach((d, i) => {
    const ratio = (d.market_cap || 0) / total
    if (ratio >= MERGE_THRESHOLD && main.length < 11) {
      main.push({ ...d, ratio, color: PIE_COLORS[main.length % PIE_COLORS.length] })
    } else {
      otherCap += d.market_cap || 0
      otherCount += 1
    }
  })

  if (otherCap > 0) {
    main.push({
      sector_code: '__other__',
      sector_name: `其他 (${otherCount} 產業)`,
      market_cap: otherCap,
      ratio: otherCap / total,
      color: '#475569',
    })
  }
  return main
}

// ---------------------------------------------------------------------------
// Tooltip components
// ---------------------------------------------------------------------------

function PieTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div className="bg-th-card border border-th-border rounded-sm shadow-panel px-3 py-2 text-xs"
      style={{ fontFamily: 'var(--font-mono)', minWidth: 140 }}>
      <div className="font-medium text-th-text mb-1">{d.sector_name}</div>
      <div className="text-th-muted">市值：<span className="text-th-text">{fmtBn(d.market_cap)}</span></div>
      <div className="text-th-muted">佔比：<span className="text-th-text">{(d.ratio * 100).toFixed(1)}%</span></div>
      {d.change_pct != null && (
        <div className="text-th-muted">漲跌：
          <span style={{ color: d.change_pct >= 0 ? C_UP : C_DOWN }}>
            {fmtPct(d.change_pct)}
          </span>
        </div>
      )}
    </div>
  )
}

function BarFlowTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-th-card border border-th-border rounded-sm shadow-panel px-3 py-2 text-xs"
      style={{ fontFamily: 'var(--font-mono)', minWidth: 160 }}>
      <div className="font-medium text-th-text mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.fill }} className="flex justify-between gap-3">
          <span>{p.name}</span>
          <span>{fmtFlow(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Detail slide-in panel
// ---------------------------------------------------------------------------

function DetailPanel({ sector, onClose }) {
  const navigate = useNavigate()
  const { data: raw, isLoading } = useQuery({
    queryKey: ['sector', 'detail', sector?.sector_code],
    queryFn: () =>
      authFetch(`${getApiBase()}/api/sector/${encodeURIComponent(sector.sector_code)}/detail`).then((r) => r.json()),
    enabled: !!sector,
    staleTime: 5 * 60 * 1000,
  })

  const detail = raw?.data || {}
  const stocks = detail.stock_list || []

  return (
    <div
      className="fixed inset-y-0 right-0 w-full md:w-96 bg-th-card border-l border-th-border shadow-2xl z-50 flex flex-col"
      style={{ transition: 'transform 0.2s' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-th-border">
        <div>
          <div className="font-medium text-th-text text-sm" style={{ fontFamily: 'var(--font-ui)' }}>
            {sector?.sector_name}
          </div>
          <div className="text-xs text-th-muted mt-0.5" style={{ fontFamily: 'var(--font-mono)' }}>
            {sector?.sector_code}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-th-muted hover:text-th-text text-lg leading-none px-2"
          aria-label="關閉"
        >
          ✕
        </button>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 px-4 py-3 border-b border-th-border">
        <MetricBadge
          label="市值"
          value={detail.market_cap != null ? (detail.market_cap / 1e8).toFixed(0) : null}
          format="raw"
        />
        <MetricBadge
          label="漲跌"
          value={detail.change_pct}
          format="percent"
          trend={changeTrend(detail.change_pct)}
        />
        <MetricBadge
          label="外資淨買"
          value={detail.fund_flow_foreign != null ? (detail.fund_flow_foreign / 1e8).toFixed(1) : null}
          format="raw"
          trend={changeTrend(detail.fund_flow_foreign)}
        />
        <MetricBadge
          label="投信淨買"
          value={detail.fund_flow_trust != null ? (detail.fund_flow_trust / 1e8).toFixed(1) : null}
          format="raw"
          trend={changeTrend(detail.fund_flow_trust)}
        />
      </div>

      {/* Stock list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center items-center py-8">
            <div className="w-4 h-4 border-2 border-th-border border-t-th-accent rounded-full animate-spin" />
          </div>
        ) : stocks.length === 0 ? (
          <div className="text-xs text-th-muted text-center py-8" style={{ fontFamily: 'var(--font-ui)' }}>
            無股票資料
          </div>
        ) : (
          <table className="w-full text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
            <thead>
              <tr className="border-b border-th-border">
                <th className="px-4 py-2 text-left text-th-muted font-medium" style={{ fontFamily: 'var(--font-ui)', fontSize: 10 }}>
                  代碼
                </th>
                <th className="px-4 py-2 text-left text-th-muted font-medium" style={{ fontFamily: 'var(--font-ui)', fontSize: 10 }}>
                  子產業
                </th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((s) => (
                <tr
                  key={s.symbol}
                  className="border-b border-th-border/40 hover:bg-th-accent/5 cursor-pointer transition-colors"
                  onClick={() => navigate(`/research/stock?symbol=${s.symbol}`)}
                >
                  <td className="px-4 py-2 text-th-accent">{s.symbol}</td>
                  <td className="px-4 py-2 text-th-muted">{s.sub_sector || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SectorAnalysis() {
  const [selectedSector, setSelectedSector] = useState(null)

  // ── Overview data
  const { data: overviewRaw, isLoading: ovLoading, error: ovError } = useQuery({
    queryKey: ['sector', 'overview'],
    queryFn: () => authFetch(`${getApiBase()}/api/sector/overview`).then((r) => r.json()),
    staleTime: 5 * 60 * 1000,
  })

  // ── Fund flow data (5 days)
  const { data: flowRaw, isLoading: flowLoading, error: flowError } = useQuery({
    queryKey: ['sector', 'flow', 5],
    queryFn: () => authFetch(`${getApiBase()}/api/sector/flow?days=5`).then((r) => r.json()),
    staleTime: 5 * 60 * 1000,
  })

  const sectors = Array.isArray(overviewRaw?.data) ? overviewRaw.data : []
  const flowRows = Array.isArray(flowRaw?.data) ? flowRaw.data : []

  // ── KPI computation
  const totalSectors = sectors.length
  const topGainer = sectors.reduce(
    (best, s) => (!best || (s.change_pct ?? -999) > (best.change_pct ?? -999) ? s : best),
    null,
  )
  const topInflow = sectors.reduce(
    (best, s) => (!best || (s.fund_flow_net ?? -Infinity) > (best.fund_flow_net ?? -Infinity) ? s : best),
    null,
  )

  // ── Pie data
  const pieData = mergePieData([...sectors].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0)))

  // ── BarChart: latest date, top 10 by |fund_flow_net|
  const latestDate = flowRows.length
    ? flowRows.reduce((m, r) => (r.trade_date > m ? r.trade_date : m), '')
    : null
  const barData = latestDate
    ? [...flowRows.filter((r) => r.trade_date === latestDate)]
        .sort((a, b) => Math.abs(b.fund_flow_net ?? 0) - Math.abs(a.fund_flow_net ?? 0))
        .slice(0, 10)
        .map((r) => ({
          name: r.sector_name.length > 6 ? r.sector_name.slice(0, 6) + '…' : r.sector_name,
          fullName: r.sector_name,
          sector_code: r.sector_code,
          foreign: r.fund_flow_foreign != null ? +(r.fund_flow_foreign / 1e8).toFixed(2) : 0,
          trust: r.fund_flow_trust != null ? +(r.fund_flow_trust / 1e8).toFixed(2) : 0,
        }))
    : []

  // ── Table sorted by market_cap desc
  const tableData = [...sectors].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0))

  const handleRowClick = useCallback((sector) => {
    setSelectedSector(sector)
  }, [])

  const overviewErr = ovError ? (ovError.message || '資料載入失敗') : null
  const flowErr = flowError ? (flowError.message || '資料載入失敗') : null

  return (
    <div className="space-y-4">
      {/* Page title */}
      <h1 className="text-lg font-medium text-th-text" style={{ fontFamily: 'var(--font-ui)' }}>
        產業賽道分析
      </h1>

      {/* ── KPI Summary row ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <DataCard title="產業數量" loading={ovLoading} error={overviewErr}>
          <MetricBadge value={totalSectors} format="number" />
        </DataCard>

        <DataCard title="領漲產業" loading={ovLoading} error={overviewErr}>
          {topGainer ? (
            <div className="space-y-1">
              <div className="text-sm font-medium text-th-text" style={{ fontFamily: 'var(--font-ui)' }}>
                {topGainer.sector_name}
              </div>
              <MetricBadge
                value={topGainer.change_pct}
                format="percent"
                trend={changeTrend(topGainer.change_pct)}
              />
            </div>
          ) : null}
        </DataCard>

        <DataCard title="最大淨流入" loading={ovLoading} error={overviewErr}>
          {topInflow ? (
            <div className="space-y-1">
              <div className="text-sm font-medium text-th-text" style={{ fontFamily: 'var(--font-ui)' }}>
                {topInflow.sector_name}
              </div>
              <span
                className="text-base tabular-nums"
                style={{ color: (topInflow.fund_flow_net ?? 0) >= 0 ? C_UP : C_DOWN, fontFamily: 'var(--font-data)' }}
              >
                {fmtFlow(topInflow.fund_flow_net)}
              </span>
            </div>
          ) : null}
        </DataCard>
      </div>

      {/* ── Charts row ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* PieChart — 市值分布 */}
        <DataCard
          title="市值分布（億元）"
          loading={ovLoading}
          error={overviewErr}
          empty={!ovLoading && !overviewErr && pieData.length === 0 ? '尚無產業資料' : undefined}
        >
          {!ovLoading && !overviewErr && pieData.length > 0 && (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    dataKey="market_cap"
                    nameKey="sector_name"
                    cx="50%"
                    cy="50%"
                    innerRadius="45%"
                    outerRadius="75%"
                    paddingAngle={2}
                    isAnimationActive={false}
                  >
                    {pieData.map((entry) => (
                      <Cell
                        key={entry.sector_code}
                        fill={entry.color}
                        stroke="transparent"
                        style={{ cursor: entry.sector_code !== '__other__' ? 'pointer' : 'default' }}
                        onClick={() => entry.sector_code !== '__other__' && handleRowClick(entry)}
                      />
                    ))}
                  </Pie>
                  <ReTooltip content={<PieTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
          {/* Legend */}
          {!ovLoading && !overviewErr && pieData.length > 0 && (
            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
              {pieData.map((d) => (
                <div
                  key={d.sector_code}
                  className="flex items-center gap-1 text-xs cursor-pointer"
                  style={{ fontFamily: 'var(--font-ui)' }}
                  onClick={() => d.sector_code !== '__other__' && handleRowClick(d)}
                >
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ background: d.color }}
                  />
                  <span className="text-th-muted truncate max-w-[5rem]">{d.sector_name}</span>
                </div>
              ))}
            </div>
          )}
        </DataCard>

        {/* BarChart — 法人資金流向 */}
        <DataCard
          title="法人資金流向（億元，前10產業）"
          loading={flowLoading}
          error={flowErr}
          empty={!flowLoading && !flowErr && barData.length === 0 ? '尚無流向資料' : undefined}
        >
          {!flowLoading && !flowErr && barData.length > 0 && (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={barData} margin={{ top: 8, right: 8, bottom: 32, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(var(--border, 60 60 60), 0.3)" />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 9, fontFamily: 'var(--font-mono)', fill: C_MUTED }}
                    angle={-30}
                    textAnchor="end"
                    interval={0}
                  />
                  <YAxis
                    tick={{ fontSize: 9, fontFamily: 'var(--font-mono)', fill: C_MUTED }}
                    tickFormatter={(v) => `${v}億`}
                  />
                  <ReTooltip content={<BarFlowTooltip />} />
                  <Legend
                    wrapperStyle={{ fontSize: 10, fontFamily: 'var(--font-ui)', paddingTop: 4 }}
                  />
                  <Bar dataKey="foreign" name="外資" fill="#38bdf8" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="trust" name="投信" fill="#fb923c" radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </DataCard>
      </div>

      {/* ── Sector table ── */}
      <DataCard
        title="產業概況"
        loading={ovLoading}
        error={overviewErr}
        empty={!ovLoading && !overviewErr && tableData.length === 0 ? '尚無產業資料' : undefined}
      >
        {!ovLoading && !overviewErr && tableData.length > 0 && (
          <>
            {/* Desktop table */}
            <div className="hidden md:block overflow-x-auto -mx-3 -mb-3">
              <table className="w-full text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
                <thead>
                  <tr className="border-b border-th-border">
                    {['產業', '漲跌%', '外資(億)', '投信(億)', '法人合計', '成交額', '股票數'].map((h) => (
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
                  {tableData.map((s) => {
                    const changePct = s.change_pct ?? null
                    const pctColor = changePct === null ? C_MUTED : changePct >= 0 ? C_UP : C_DOWN
                    const foreignVal = s.fund_flow_foreign != null ? s.fund_flow_foreign / 1e8 : null
                    const trustVal = s.fund_flow_trust != null ? s.fund_flow_trust / 1e8 : null
                    const netVal = s.fund_flow_net != null ? s.fund_flow_net / 1e8 : null
                    const netColor = netVal === null ? C_MUTED : netVal >= 0 ? C_UP : C_DOWN
                    return (
                      <tr
                        key={s.sector_code}
                        className="border-b border-th-border/50 hover:bg-th-accent/5 cursor-pointer transition-colors"
                        onClick={() => handleRowClick(s)}
                      >
                        <td className="px-3 py-2 font-medium text-th-accent" style={{ fontFamily: 'var(--font-ui)' }}>
                          {s.sector_name}
                        </td>
                        <td className="px-3 py-2 tabular-nums" style={{ color: pctColor }}>
                          {changePct !== null ? fmtPct(changePct) : '—'}
                        </td>
                        <td
                          className="px-3 py-2 tabular-nums"
                          style={{ color: foreignVal === null ? C_MUTED : foreignVal >= 0 ? C_UP : C_DOWN }}
                        >
                          {foreignVal !== null ? `${foreignVal >= 0 ? '+' : ''}${foreignVal.toFixed(1)}` : '—'}
                        </td>
                        <td
                          className="px-3 py-2 tabular-nums"
                          style={{ color: trustVal === null ? C_MUTED : trustVal >= 0 ? C_UP : C_DOWN }}
                        >
                          {trustVal !== null ? `${trustVal >= 0 ? '+' : ''}${trustVal.toFixed(1)}` : '—'}
                        </td>
                        <td className="px-3 py-2 tabular-nums" style={{ color: netColor }}>
                          {netVal !== null ? `${netVal >= 0 ? '+' : ''}${netVal.toFixed(1)}` : '—'}
                        </td>
                        <td className="px-3 py-2 tabular-nums text-th-muted">
                          {fmtBn(s.turnover)}
                        </td>
                        <td className="px-3 py-2 tabular-nums text-th-muted">
                          {s.stock_count ?? '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile card list */}
            <div className="md:hidden space-y-2">
              {tableData.map((s) => {
                const pctColor = s.change_pct == null ? C_MUTED : s.change_pct >= 0 ? C_UP : C_DOWN
                const netColor = s.fund_flow_net == null ? C_MUTED : s.fund_flow_net >= 0 ? C_UP : C_DOWN
                return (
                  <div
                    key={s.sector_code}
                    className="border border-th-border rounded-sm p-3 hover:border-th-accent/50 cursor-pointer transition-colors"
                    onClick={() => handleRowClick(s)}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-th-accent" style={{ fontFamily: 'var(--font-ui)' }}>
                        {s.sector_name}
                      </span>
                      <span
                        className="text-xs tabular-nums"
                        style={{ color: pctColor, fontFamily: 'var(--font-mono)' }}
                      >
                        {s.change_pct != null ? fmtPct(s.change_pct) : '—'}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-xs" style={{ fontFamily: 'var(--font-mono)' }}>
                      <div>
                        <div className="text-th-muted text-[10px]" style={{ fontFamily: 'var(--font-ui)' }}>外資</div>
                        <div style={{ color: (s.fund_flow_foreign ?? 0) >= 0 ? C_UP : C_DOWN }}>
                          {fmtFlow(s.fund_flow_foreign)}
                        </div>
                      </div>
                      <div>
                        <div className="text-th-muted text-[10px]" style={{ fontFamily: 'var(--font-ui)' }}>投信</div>
                        <div style={{ color: (s.fund_flow_trust ?? 0) >= 0 ? C_UP : C_DOWN }}>
                          {fmtFlow(s.fund_flow_trust)}
                        </div>
                      </div>
                      <div>
                        <div className="text-th-muted text-[10px]" style={{ fontFamily: 'var(--font-ui)' }}>成交</div>
                        <div className="text-th-muted">{fmtBn(s.turnover)}</div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </DataCard>

      {/* ── Detail panel overlay ── */}
      {selectedSector && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => setSelectedSector(null)}
          />
          <DetailPanel
            sector={selectedSector}
            onClose={() => setSelectedSector(null)}
          />
        </>
      )}
    </div>
  )
}
