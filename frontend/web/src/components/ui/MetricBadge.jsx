import React from 'react'

/**
 * MetricBadge — monospace number display with trend arrow + color
 * trend: 'up' | 'down' | 'flat'
 * format: 'currency' | 'percent' | 'number' | 'raw'
 */
export function MetricBadge({ value, label, trend, format = 'raw' }) {
  const formatValue = (val) => {
    if (val === null || val === undefined) return '—'
    switch (format) {
      case 'currency':
        return new Intl.NumberFormat('zh-TW', {
          style: 'currency',
          currency: 'TWD',
          minimumFractionDigits: 0,
          maximumFractionDigits: 0,
        }).format(val)
      case 'percent':
        return `${Number(val).toFixed(2)}%`
      case 'number':
        return new Intl.NumberFormat('zh-TW').format(val)
      default:
        return String(val)
    }
  }

  const trendArrow = trend === 'up' ? '▲' : trend === 'down' ? '▼' : '─'
  const trendColorVar =
    trend === 'up' ? 'var(--up)' : trend === 'down' ? 'var(--down)' : 'var(--muted)'
  const trendColor = `rgb(${trendColorVar})`

  return (
    <div className="inline-flex flex-col items-start min-w-0">
      {label && (
        <span
          className="text-xs text-th-muted mb-0.5 truncate"
          style={{ fontFamily: 'var(--font-ui)', fontSize: '10px' }}
        >
          {label}
        </span>
      )}
      <div className="flex items-baseline gap-1">
        <span
          className="text-base tabular-nums"
          style={{
            fontFamily: 'var(--font-data)',
            color: trend ? trendColor : 'rgb(var(--text))',
          }}
        >
          {formatValue(value)}
        </span>
        {trend && (
          <span
            className="text-xs"
            style={{ color: trendColor, fontFamily: 'var(--font-mono)' }}
          >
            {trendArrow}
          </span>
        )}
      </div>
    </div>
  )
}

export default MetricBadge
