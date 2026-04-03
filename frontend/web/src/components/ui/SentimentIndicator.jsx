import React from 'react'

/**
 * SentimentIndicator
 * sentiment: 'bullish' | 'bearish' | 'neutral'
 */
export function SentimentIndicator({ sentiment = 'neutral' }) {
  const config = {
    bullish: {
      dot: 'rgb(var(--up))',
      arrow: '▲',
      label: '看多',
      glow: '0 0 6px rgba(var(--up-glow))',
    },
    bearish: {
      dot: 'rgb(var(--down))',
      arrow: '▼',
      label: '看空',
      glow: '0 0 6px rgba(var(--down-glow))',
    },
    neutral: {
      dot: 'rgb(var(--warn))',
      arrow: '─',
      label: '中性',
      glow: 'none',
    },
  }

  const { dot, arrow, label, glow } = config[sentiment] ?? config.neutral

  return (
    <div className="inline-flex items-center gap-1.5">
      <span
        className="inline-block w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: dot, boxShadow: glow }}
      />
      <span
        className="text-xs"
        style={{ color: dot, fontFamily: 'var(--font-mono)' }}
      >
        {arrow}
      </span>
      <span
        className="text-xs text-th-muted"
        style={{ fontFamily: 'var(--font-ui)' }}
      >
        {label}
      </span>
    </div>
  )
}

export default SentimentIndicator
