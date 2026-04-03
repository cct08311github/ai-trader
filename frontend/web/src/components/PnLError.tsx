/**
 * PnLError.tsx — Kyo Nakamura
 * Real-time P&L ECG (equity curve) with neon glow treatment.
 *
 * Shows:
 *   • SVG polyline with up=neon-green glow / down=ember-red glow
 *   • Right-edge pulsing ball
 *   • Large floating P&L number
 *   • ECG ambient pulse animation
 */

import { useMemo, useRef, useState, useEffect } from 'react'

interface EquityPoint {
  date: string
  equity: number
}

interface Props {
  data: EquityPoint[]
  dailyPnl?: number   // standalone daily P&L shown large
  height?: number
  animate?: boolean   // trigger entry animation
}

function formatPnl(v: number) {
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const PADDING = { top: 32, right: 72, bottom: 32, left: 12 }

export default function PnLError({
  data = [],
  dailyPnl,
  height = 220,
  animate = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(500)
  const [animEntry, setAnimEntry] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      setW(entries[0].contentRect.width)
    })
    ro.observe(containerRef.current)
    setW(containerRef.current.contentRect.width)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (animate) {
      setAnimEntry(true)
      setTimeout(() => setAnimEntry(false), 800)
    }
  }, [animate, data.length])

  const H = height
  const innerW = W - PADDING.left - PADDING.right
  const innerH = H - PADDING.top - PADDING.bottom

  const { points, segments, minY, maxY } = useMemo(() => {
    if (data.length < 2) {
      return { points: '', segments: [], minY: 0, maxY: 100 }
    }

    const prices = data.map(d => d.equity)
    const lo = Math.min(...prices)
    const hi = Math.max(...prices)
    const pad = (hi - lo) * 0.15 || 1
    const loP = lo - pad
    const hiP = hi + pad

    const scaleX = (i: number) => PADDING.left + (i / (data.length - 1)) * innerW
    const scaleY = (p: number) =>
      PADDING.top + innerH - ((p - loP) / (hiP - loP)) * innerH

    const pts = data.map((d, i) => ({ x: scaleX(i), y: scaleY(d.equity) }))

    // Split polyline into up/down segments
    const segs: { up: boolean; pts: { x: number; y: number }[] }[] = []
    let current: { up: boolean; pts: { x: number; y: number }[] } | null = null

    for (let i = 0; i < pts.length; i++) {
      const up = i === 0 ? true : data[i].equity >= data[i - 1].equity
      if (!current || current.up !== up) {
        if (current) segs.push(current)
        current = { up, pts: [pts[i]] }
      } else {
        current.pts.push(pts[i])
      }
    }
    if (current) segs.push(current)

    const points = pts.map(p => `${p.x},${p.y}`).join(' L ')

    return { points, segments: segs, minY: loP, maxY: hiP }
  }, [data, innerW, innerH])

  const lastPt = data.length > 0 ? data[data.length - 1] : null
  const lastX = data.length > 0
    ? PADDING.left + innerW
    : PADDING.left
  const lastY = data.length > 0
    ? (() => {
        const prices = data.map(d => d.equity)
        const lo = Math.min(...prices)
        const hi = Math.max(...prices)
        const pad = (hi - lo) * 0.15 || 1
        const loP = lo - pad
        const hiP = hi + pad
        return PADDING.top + innerH - ((lastPt!.equity - loP) / (hiP - loP)) * innerH
      })()
    : PADDING.top + innerH / 2

  // Is today up or down?
  const isUp = lastPt ? data.length < 2 || lastPt.equity >= (data[data.length - 2]?.equity ?? lastPt.equity) : true

  const strokeColor = isUp ? 'rgb(var(--ecg-up))' : 'rgb(var(--ecg-down))'
  const glowColor   = isUp ? 'rgba(var(--up-glow))' : 'rgba(var(--down-glow))'
  const ballColor   = isUp ? 'rgb(var(--ecg-up))'    : 'rgb(var(--ecg-down))'

  return (
    <div ref={containerRef} className="relative w-full" style={{ height: H }}>
      <svg width={W} height={H} className="overflow-visible" aria-label="損益ECG曲線">
        <defs>
          {/* Up glow */}
          <filter id="ecg-glow-up" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Down glow */}
          <filter id="ecg-glow-down" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Ball glow */}
          <filter id="ball-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Gradient for line glow */}
          <linearGradient id="ecg-gradient-up" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(var(--up-glow))" />
            <stop offset="100%" stopColor="rgba(var(--up-glow)) 0%" />
          </linearGradient>
          <linearGradient id="ecg-gradient-down" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(var(--down-glow))" />
            <stop offset="100%" stopColor="rgba(var(--down-glow)) 0%" />
          </linearGradient>
        </defs>

        {/* ── Y-axis grid ──────────────────────────────────────── */}
        {Array.from({ length: 4 }).map((_, i) => {
          const y = PADDING.top + (i / 3) * innerH
          const val = maxY - (i / 3) * (maxY - minY)
          return (
            <g key={i}>
              <line
                x1={PADDING.left} y1={y}
                x2={W - PADDING.right} y2={y}
                stroke="rgba(var(--border), 0.35)"
                strokeDasharray="3 5"
              />
              <text
                x={W - PADDING.right + 4} y={y + 4}
                fontSize={10} fontFamily="var(--font-data)"
                fill="rgb(var(--muted))"
              >
                {`$${(val / 1000).toFixed(0)}K`}
              </text>
            </g>
          )
        })}

        {/* ── Zero reference ────────────────────────────────────── */}
        {minY < 0 && maxY > 0 && (() => {
          const zeroY = PADDING.top + innerH - ((0 - minY) / (maxY - minY)) * innerH
          return (
            <line
              x1={PADDING.left} y1={zeroY}
              x2={W - PADDING.right} y2={zeroY}
              stroke="rgba(var(--muted), 0.4)"
              strokeDasharray="6 3"
            />
          )
        })()}

        {/* ── Area fill ─────────────────────────────────────────── */}
        {data.length >= 2 && (
          <path
            d={`M ${PADDING.left} ${PADDING.top + innerH}
                L ${points}
                L ${lastX} ${PADDING.top + innerH} Z`}
            fill={isUp ? 'rgba(var(--up-glow))' : 'rgba(var(--down-glow))'}
            opacity={0.15}
          />
        )}

        {/* ── Segmented polyline (up=neon-green / down=ember-red) ── */}
        {segments.map((seg, si) => (
          <polyline
            key={si}
            points={seg.pts.map(p => `${p.x},${p.y}`).join(' ')}
            fill="none"
            stroke={seg.up ? 'rgb(var(--ecg-up))' : 'rgb(var(--ecg-down))'}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            filter={`url(#ecg-glow-${seg.up ? 'up' : 'down'})`}
            className={animEntry ? 'animate-kline-zap' : ''}
          />
        ))}

        {/* ── Start dot ────────────────────────────────────────── */}
        {data.length >= 2 && (
          <circle
            cx={PADDING.left}
            cy={lastY}
            r={3}
            fill="rgb(var(--border))"
          />
        )}

        {/* ── Right-edge pulsing ball ───────────────────────────── */}
        {data.length >= 2 && (
          <g>
            {/* Ambient pulse rings */}
            <circle
              cx={lastX} cy={lastY}
              r={12}
              fill="none"
              stroke={ballColor}
              strokeWidth={1}
              opacity={0.3}
              className="animate-ecg-pulse"
            />
            {/* Core ball */}
            <circle
              cx={lastX} cy={lastY}
              r={5}
              fill={ballColor}
              filter="url(#ball-glow)"
              className="animate-ecg-pulse"
            />
          </g>
        )}
      </svg>

      {/* ── Large floating P&L text ────────────────────────────── */}
      {dailyPnl != null && (
        <div
          className={`pointer-events-none absolute right-16 top-2
                      text-right font-mono font-bold tabular-nums
                      ${isUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}
                      ${animEntry ? 'animate-pnl-float' : 'opacity-90'}`}
          style={{ fontSize: Math.min(28, W * 0.06) }}
          aria-label={`今日損益: ${formatPnl(dailyPnl)}`}
        >
          <div className="text-[10px] uppercase tracking-widest text-[rgb(var(--muted))] mb-0.5">
            日損益
          </div>
          <div className="drop-shadow-[0_0_8px_currentColor]">
            {formatPnl(dailyPnl)}
          </div>
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────── */}
      {data.length < 2 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--bg))]/80 px-4 py-2.5 text-center backdrop-blur-sm">
            <div className="text-xs font-medium text-[rgb(var(--muted))]">
              💡 首次平倉後將顯示損益曲線
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
