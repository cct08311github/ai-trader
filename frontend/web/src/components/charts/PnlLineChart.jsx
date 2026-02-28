import React from 'react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCurrency } from '../../lib/format'

function tooltipFormatter(value) {
  return formatCurrency(Number(value || 0))
}

export default function PnlLineChart({ data }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={300} minHeight={220}>
        <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="rgba(148,163,184,0.25)" strokeDasharray="3 3" />
          <XAxis dataKey="date" tick={{ fontSize: 12 }} minTickGap={24} />
          <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => formatCurrency(v)} width={80} />
          <Tooltip formatter={tooltipFormatter} />
          <Line type="monotone" dataKey="equity" stroke="#38bdf8" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
