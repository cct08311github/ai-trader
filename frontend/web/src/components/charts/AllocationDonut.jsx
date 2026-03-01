import React from 'react'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { formatPercent } from '../../lib/format'

const COLORS = ['#10b981', '#38bdf8', '#a78bfa', '#f59e0b', '#fb7185', '#22c55e', '#60a5fa']
// Design doc §4.1: "板塊超過 40% 集中度上限時，對應的圓餅圖區塊顯示警示紅框"
const WARN_COLOR = '#FF4D4F'
const WARN_THRESHOLD = 0.40 // 40%

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  const weight = d?.weight ?? 0
  const isOver = weight > WARN_THRESHOLD
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-xl backdrop-blur-sm">
      <div className="font-semibold text-slate-200">{d?.label || d?.name}</div>
      <div className={`mt-1 ${isOver ? 'text-rose-300 font-bold' : 'text-slate-300'}`}>
        {formatPercent(weight)}
        {isOver && ' ⚠️ 超 40% 上限'}
      </div>
    </div>
  )
}

function CustomLegend({ payload }) {
  if (!payload?.length) return null
  return (
    <ul className="mt-3 flex flex-wrap justify-center gap-x-4 gap-y-1.5">
      {payload.map((entry, i) => {
        const weight = entry.payload?.weight ?? 0
        const isOver = weight > WARN_THRESHOLD
        return (
          <li key={i} className="flex items-center gap-1.5 text-xs">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: entry.color, boxShadow: isOver ? `0 0 0 1.5px ${WARN_COLOR}` : 'none' }}
            />
            <span className={isOver ? 'text-rose-300 font-medium' : 'text-slate-400'}>
              {entry.value} {isOver && '⚠️'}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** AllocationDonut — design doc §4.1
 * - Shows sector allocation as a donut chart
 * - Segments with weight > 40% get a warning red stroke (#FF4D4F)
 * - warnThreshold prop (percentage, e.g. 40) for parent-level override
 */
export default function AllocationDonut({ data, warnThreshold = 40 }) {
  const warnFraction = warnThreshold / 100

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%" minWidth={280} minHeight={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={2}
          >
            {(data || []).map((entry, idx) => {
              const weight = entry.weight ?? 0
              const isOver = weight > warnFraction
              return (
                <Cell
                  key={idx}
                  fill={COLORS[idx % COLORS.length]}
                  stroke={isOver ? WARN_COLOR : 'rgba(0,0,0,0.15)'}
                  strokeWidth={isOver ? 3 : 1}
                />
              )
            })}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend content={<CustomLegend />} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
