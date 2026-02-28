import React from 'react'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { formatCurrency, formatPercent } from '../../lib/format'

const COLORS = ['#10b981', '#38bdf8', '#a78bfa', '#f59e0b', '#fb7185', '#22c55e', '#60a5fa']

function tooltipFormatter(value, name, props) {
  const payload = props?.payload
  const pct = Number(payload?.weight)
  return [formatCurrency(Number(value || 0)), `${name} (${formatPercent(pct)})`]
}

export default function AllocationDonut({ data }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={300} minHeight={220}>
        <PieChart>
          <Tooltip formatter={tooltipFormatter} />
          <Legend verticalAlign="bottom" height={36} />
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={60}
            outerRadius={90}
            paddingAngle={2}
            stroke="rgba(0,0,0,0.1)"
          >
            {(data || []).map((_, idx) => (
              <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
