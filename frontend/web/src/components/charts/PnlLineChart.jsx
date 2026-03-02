import React from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCurrency } from '../../lib/format'

function tooltipFormatter(value) {
  return formatCurrency(Number(value || 0))
}

// Placeholder data: flat zero line spanning today ± 5 days, for visual scaffolding only
function buildPlaceholderData() {
  const today = new Date()
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(today)
    d.setDate(today.getDate() - 3 + i)
    return { date: `${d.getMonth() + 1}/${d.getDate()}`, equity: 0 }
  })
}

export default function PnlLineChart({ data }) {
  const isEmpty = !data || data.length === 0

  return (
    <div className="relative h-64 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={300} minHeight={220}>
        <LineChart
          data={isEmpty ? buildPlaceholderData() : data}
          margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
        >
          <CartesianGrid stroke="rgba(148,163,184,0.25)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={24} />
          <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => formatCurrency(v)} width={80} />
          {!isEmpty && <Tooltip formatter={tooltipFormatter} />}
          <ReferenceLine y={0} stroke="rgba(148,163,184,0.5)" strokeDasharray="6 3" />
          <Line
            type="monotone"
            dataKey="equity"
            stroke={isEmpty ? 'rgba(148,163,184,0.3)' : '#38bdf8'}
            strokeWidth={isEmpty ? 1.5 : 2}
            strokeDasharray={isEmpty ? '6 4' : undefined}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* Empty state overlay */}
      {isEmpty && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--bg))]/80 px-4 py-2.5 text-center backdrop-blur-sm">
            <div className="text-xs font-medium text-[rgb(var(--muted))]">💡 首次平倉後將顯示損益曲線</div>
          </div>
        </div>
      )}
    </div>
  )
}
