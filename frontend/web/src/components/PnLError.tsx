/**
 * PnLError.tsx -- Kyo Nakamura
 * ECG-style equity curve with neon glow, pulsing endpoint,
 * cardiac flatline warnings, and breathing ambient animation.
 *
 * Named "PnLError" because in Kyo's philosophy, every loss
 * is a system error that must be visible and felt.
 *
 * Visual features:
 *   - Segmented polyline: up=neon-green / down=ember-red
 *   - Right-edge pulsing ball (like cardiac monitor)
 *   - Large floating P&L number with chromatic glitch
 *   - Gradient area fill under the curve
 *   - Drawdown threshold warnings (ECG flatline zone)
 *   - Breathing ambient glow on the entire component
 */

import { useMemo, useRef, useState, useEffect } from 'react'

interface EquityPoint {
  date: string
  equity: number
}

interface Props {
  data: EquityPoint[]
  dailyPnl?: number
  height?: number
  animate?: boolean
}

function formatPnl(v: number) {
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

const PADDING = { top: 36, right: 80, bottom: 32, left: 12 }

export default function PnLError({
  data = [],
  dailyPnl,
  height = 240,
  animate = false,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(500)
  const [animEntry, setAnimEntry] = useState(false)
  const [glitching, setGlitching] = useState(false)
  const prevPnlRef = useRef(dailyPnl)

  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      setW(entries[0].contentRect.width)
    })
    ro.observe(containerRef.current)
    if (containerRef.current.getBoundingClientRect) {
      setW(containerRef.current.getBoundingClientRect().width)
    }
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (animate) {
      setAnimEntry(true)
      setTimeout(() => setAnimEntry(false), 800)
    }
  }, [animate, data.length])

  // Chromatic glitch on P&L change
  useEffect(() => {
    if (dailyPnl != null && prevPnlRef.current != null && prevPnlRef.current !== dailyPnl) {
      setGlitching(true)
      const t = setTimeout(() => setGlitching(false), 350)
      return () => clearTimeout(t)
    }
    prevPnlRef.current = dailyPnl
  }, [dailyPnl])

  const H = height
  const innerW = W - PADDING.left - PADDING.right
  const innerH = H - PADDING.top - PADDING.bottom

  const { points, segments, minY, maxY, drawdownPct } = useMemo(() => {
    if (data.length < 2) {
      return { points: '', segments: [], minY: 0, maxY: 100, drawdownPct: 0 }
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

    // Segment by direction
    const segs: { up: boolean; pts: { x: number; y: number }[] }[] = []
    let current: { up: boolean; pts: { x: number; y: number }[] } | null = null

    for (let i = 0; i < pts.length; i++) {
      const up = i === 0 ? true : data[i].equity >= data[i - 1].equity
      if (!current || current.up !== up) {
        // Bridge: carry the previous endpoint into the new segment
        if (current) {
          segs.push(current)
          current = { up, pts: [pts[i - 1], pts[i]] }
        } else {
          current = { up, pts: [pts[i]] }
        }
      } else {
        current.pts.push(pts[i])
      }
    }
    if (current) segs.push(current)

    const pointsStr = pts.map(p => `${p.x},${p.y}`).join(' L ')

    // Calculate max drawdown
    let peak = prices[0]
    let maxDD = 0
    for (const p of prices) {
      if (p > peak) peak = p
      const dd = (peak - p) / peak
      if (dd > maxDD) maxDD = dd
    }

    return { points: pointsStr, segments: segs, minY: loP, maxY: hiP, drawdownPct: maxDD * 100 }
  }, [data, innerW, innerH])

  const lastPt = data.length > 0 ? data[data.length - 1] : null
  const lastX = PADDING.left + innerW
  const lastY = data.length >= 2
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

  const isUp = lastPt
    ? data.length < 2 || lastPt.equity >= (data[data.length - 2]?.equity ?? lastPt.equity)
    : true

  const ballColor = isUp ? 'var(--ecg-up)' : 'var(--ecg-down)'

  // Drawdown severity
  const ddSeverity = drawdownPct > 10 ? 'critical' : drawdownPct > 5 ? 'warning' : 'normal'

  return (
    <div
      ref={containerRef}
      className="relative w-full"
      style={{
        height: H,
        // Ambient breathing glow around the entire ECG
        boxShadow: ddSeverity === 'critical'
          ? '0 0 30px rgba(var(--down), 0.15)'
          : ddSeverity === 'warning'
            ? '0 0 20px rgba(var(--warn), 0.08)'
            : 'none',
        transition: 'box-shadow 1s ease-in-out',
      }}
    >
      <svg width={W} height={H} className="overflow-visible" aria-label="損益ECG曲線">
        <defs>
          <filter id="ecg-glow-up" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="ecg-glow-down" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="ball-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Area gradient */}
          <linearGradient id="ecg-area-up" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--up))" stopOpacity="0.2" />
            <stop offset="100%" stopColor="rgb(var(--up))" stopOpacity="0.01" />
          </linearGradient>
          <linearGradient id="ecg-area-down" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--down))" stopOpacity="0.2" />
            <stop offset="100%" stopColor="rgb(var(--down))" stopOpacity="0.01" />
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
                stroke="rgba(var(--border), 0.25)"
                strokeDasharray="2 6"
              />
              <text
                x={W - PADDING.right + 6} y={y + 4}
                fontSize={10} fontFamily="var(--font-data)"
                fill="rgb(var(--muted))"
              >
                {`$${(val / 1000).toFixed(0)}K`}
              </text>
            </g>
          )
        })}

        {/* ── Area fill ─────────────────────────────────────────── */}
        {data.length >= 2 && (
          <path
            d={`M ${PADDING.left} ${PADDING.top + innerH}
                L ${points}
                L ${lastX} ${PADDING.top + innerH} Z`}
            fill={`url(#ecg-area-${isUp ? 'up' : 'down'})`}
          />
        )}

        {/* ── Drawdown danger zone ─────────────────────────────── */}
        {ddSeverity !== 'normal' && data.length >= 2 && (() => {
          const prices = data.map(d => d.equity)
          const peak = Math.max(...prices)
          const thresholdY = PADDING.top + innerH - ((peak * 0.95 - (Math.min(...prices) - (Math.max(...prices) - Math.min(...prices)) * 0.15)) / ((Math.max(...prices) - Math.min(...prices)) * 1.3 || 1)) * innerH
          return (
            <rect
              x={PADDING.left} y={Math.max(thresholdY, PADDING.top)}
              width={innerW} height={innerH - Math.max(thresholdY - PADDING.top, 0)}
              fill="rgba(var(--down), 0.04)"
              stroke="rgba(var(--down), 0.15)"
              strokeDasharray="8 4"
              strokeWidth={0.5}
            />
          )
        })()}

        {/* ── Segmented polyline ──────────────────────────────── */}
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

        {/* ── Right-edge pulsing ball ───────────────────────────── */}
        {data.length >= 2 && (
          <g>
            {/* Outer pulse rings */}
            <circle cx={lastX} cy={lastY} r={14}
              fill="none" stroke={ballColor} strokeWidth={1} opacity={0.2}
              className="animate-ecg-pulse"
            />
            <circle cx={lastX} cy={lastY} r={8}
              fill="none" stroke={ballColor} strokeWidth={1} opacity={0.4}
              className="animate-ecg-pulse"
              style={{ animationDelay: '0.3s' }}
            />
            {/* Core ball */}
            <circle cx={lastX} cy={lastY} r={4}
              fill={ballColor} filter="url(#ball-glow)"
            />
            {/* Horizontal price line from ball to right edge */}
            <line
              x1={lastX} y1={lastY} x2={W - 4} y2={lastY}
              stroke={ballColor} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.4}
            />
          </g>
        )}
      </svg>

      {/* ── Large floating P&L text ────────────────────────────── */}
      {dailyPnl != null && (
        <div
          className={`pointer-events-none absolute right-20 top-2
                      text-right font-mono font-bold tabular-nums
                      ${isUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}
                      ${animEntry ? 'animate-pnl-float' : 'opacity-90'}
                      ${glitching ? 'animate-chromatic-glitch' : ''}`}
          style={{ fontSize: Math.min(32, W * 0.065) }}
          aria-label={`今日損益: ${formatPnl(dailyPnl)}`}
        >
          <div className="text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] mb-0.5 font-normal">
            DAILY P&L
          </div>
          <div style={{
            filter: `drop-shadow(0 0 ${Math.abs(dailyPnl) > 10000 ? '12px' : '6px'} currentColor)`,
          }}>
            {formatPnl(dailyPnl)}
          </div>
        </div>
      )}

      {/* ── Drawdown warning badge ─────────────────────────────── */}
      {ddSeverity !== 'normal' && (
        <div className={`absolute left-3 top-2 flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-mono
                        ${ddSeverity === 'critical'
                          ? 'bg-rose-900/30 text-rose-300 border border-rose-700/40 animate-pulse'
                          : 'bg-amber-900/20 text-amber-300 border border-amber-700/30'
                        }`}>
          DD {drawdownPct.toFixed(1)}%
        </div>
      )}

      {/* ── Empty state ─────────────────────────────────────────── */}
      {data.length < 2 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="border border-[rgb(var(--border))] bg-[rgb(var(--bg))]/80 px-4 py-2.5 text-center backdrop-blur-sm"
               style={{ borderRadius: '2px' }}>
            <div className="text-xs font-medium text-[rgb(var(--muted))] font-mono">
              AWAITING FIRST TRADE CLOSE
            </div>
            <div className="text-[10px] text-[rgb(var(--muted))] opacity-60 mt-1">
              首次平倉後將顯示損益曲線
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
