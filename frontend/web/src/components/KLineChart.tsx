/**
 * KLineChart.tsx -- Kyo Nakamura
 * Artistic SVG candlestick chart with neon glow, volume terrain,
 * and chromatic aberration on the latest bar.
 *
 * This is not a chart inside a card. This is the centerpiece --
 * the heartbeat monitor of the entire portfolio.
 *
 * Props:
 *   symbol   -- ticker symbol watermark
 *   data     -- { date, open, high, low, close, volume }[]
 *   width    -- optional SVG width (default: responsive)
 *   height   -- optional SVG height (default: 340)
 *   animate  -- trigger zap animation on new data
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'

interface KBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface Props {
  symbol?: string
  data: KBar[]
  width?: number | string
  height?: number
  animate?: boolean
}

function isUp(open: number, close: number) { return close >= open }

const PADDING = { top: 20, right: 72, bottom: 44, left: 12 }

export default function KLineChart({
  symbol,
  data = [],
  width: widthProp,
  height = 340,
  animate = false,
}: Props) {
  const chartId = React.useId?.() || useRef(Math.random().toString(36).slice(2, 8)).current
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(600)
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const [zapping, setZapping] = useState(false)
  const prevLengthRef = useRef(data.length)

  // Responsive width
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      setContainerWidth(entries[0].contentRect.width)
    })
    ro.observe(containerRef.current)
    if (containerRef.current.getBoundingClientRect) {
      setContainerWidth(containerRef.current.getBoundingClientRect().width)
    }
    return () => ro.disconnect()
  }, [])

  // Zap animation on new bars
  useEffect(() => {
    if (animate && data.length > prevLengthRef.current) {
      setZapping(true)
      setTimeout(() => setZapping(false), 600)
    }
    prevLengthRef.current = data.length
  }, [data.length, animate])

  const W = typeof widthProp === 'number' ? widthProp : containerWidth
  const H = height
  const innerW = W - PADDING.left - PADDING.right
  const innerH = H - PADDING.top - PADDING.bottom

  // Compute price domain
  const { minPrice, maxPrice } = useMemo(() => {
    if (!data.length) return { minPrice: 0, maxPrice: 100 }
    const prices = data.flatMap(d => [d.high, d.low])
    const lo = Math.min(...prices)
    const hi = Math.max(...prices)
    const pad = (hi - lo) * 0.08 || 1
    return { minPrice: lo - pad, maxPrice: hi + pad }
  }, [data])

  const maxVol = useMemo(() => Math.max(...(data.map(d => d.volume ?? 0))) || 1, [data])

  const scaleX = (i: number) => PADDING.left + (i + 0.5) * (innerW / (data.length || 1))
  const scaleY = (p: number) =>
    PADDING.top + innerH - ((p - minPrice) / (maxPrice - minPrice)) * innerH

  // Candle half-width
  const candleW = Math.max(3, Math.min(14, (innerW / (data.length || 1)) * 0.55))

  // Hover bar
  const hover = hoveredIdx != null ? data[hoveredIdx] : null
  const hoverX = hoveredIdx != null ? scaleX(hoveredIdx) : null

  // Moving average (simple 10-period)
  const maLine = useMemo(() => {
    if (data.length < 10) return ''
    const pts: string[] = []
    for (let i = 9; i < data.length; i++) {
      let sum = 0
      for (let j = i - 9; j <= i; j++) sum += data[j].close
      const avg = sum / 10
      pts.push(`${scaleX(i)},${scaleY(avg)}`)
    }
    return pts.join(' L ')
  }, [data, innerW, innerH, minPrice, maxPrice])

  if (!data.length) {
    return (
      <div ref={containerRef} className="relative w-full" style={{ height: H }}>
        <div className="flex h-full items-center justify-center">
          <p className="text-sm font-mono text-[rgb(var(--muted))] animate-neon-breathe">
            K線資料載入中...
          </p>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative w-full select-none" style={{ height: H }}>
      {/* Symbol watermark -- large, rotated, behind everything */}
      {symbol && (
        <div
          className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden"
          aria-hidden="true"
        >
          <span
            className="font-mono text-[120px] font-black leading-none
                       text-[rgb(var(--border))] opacity-[0.06]
                       select-none"
            style={{ transform: 'rotate(-12deg) translateY(-10px)' }}
          >
            {symbol}
          </span>
        </div>
      )}

      <svg
        width={W}
        height={H}
        className="overflow-visible"
        aria-label={`${symbol ?? ''} K線圖`}
      >
        <defs>
          {/* Glow filters */}
          <filter id={`glow-up-${chartId}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id={`glow-down-${chartId}`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          {/* Volume gradient */}
          <linearGradient id={`vol-up-${chartId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--up))" stopOpacity="0.5" />
            <stop offset="100%" stopColor="rgb(var(--up))" stopOpacity="0.08" />
          </linearGradient>
          <linearGradient id={`vol-down-${chartId}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgb(var(--down))" stopOpacity="0.5" />
            <stop offset="100%" stopColor="rgb(var(--down))" stopOpacity="0.08" />
          </linearGradient>
        </defs>

        {/* ── Volume terrain (background) ──────────────────────── */}
        {data.map((d, i) => {
          const x = scaleX(i)
          const up = isUp(d.open, d.close)
          const barH = ((d.volume ?? 0) / maxVol) * innerH * 0.25
          const barY = H - PADDING.bottom - barH
          return (
            <rect
              key={`vol-${i}`}
              x={x - candleW / 2}
              y={barY}
              width={candleW}
              height={barH}
              fill={`url(#vol-${up ? 'up' : 'down'}-${chartId})`}
              rx={1}
            />
          )
        })}

        {/* ── Horizontal grid lines ─────────────────────────────── */}
        {Array.from({ length: 5 }).map((_, i) => {
          const y = PADDING.top + (i / 4) * innerH
          const price = maxPrice - (i / 4) * (maxPrice - minPrice)
          return (
            <g key={`grid-${i}`}>
              <line
                x1={PADDING.left} y1={y} x2={W - PADDING.right} y2={y}
                stroke="rgba(var(--border), 0.3)" strokeDasharray="2 6"
              />
              <text
                x={W - PADDING.right + 6} y={y + 4}
                fontSize={10}
                fontFamily="var(--font-data)"
                fill="rgb(var(--muted))"
              >
                {price.toFixed(2)}
              </text>
            </g>
          )
        })}

        {/* ── MA10 line ──────────────────────────────────────────── */}
        {maLine && (
          <path
            d={`M ${maLine}`}
            fill="none"
            stroke="rgba(var(--info), 0.5)"
            strokeWidth={1.2}
            strokeDasharray="4 3"
          />
        )}

        {/* ── Vertical hover line ───────────────────────────────── */}
        {hoverX != null && (
          <line
            x1={hoverX} y1={PADDING.top}
            x2={hoverX} y2={H - PADDING.bottom}
            stroke="rgba(var(--accent), 0.6)"
            strokeWidth={1}
            strokeDasharray="4 2"
          />
        )}

        {/* ── Candles ───────────────────────────────────────────── */}
        {data.map((d, i) => {
          const x = scaleX(i)
          const up = isUp(d.open, d.close)
          const bodyTop = scaleY(Math.max(d.open, d.close))
          const bodyBot = scaleY(Math.min(d.open, d.close))
          const bodyH = Math.max(1, bodyBot - bodyTop)
          const wickTop = scaleY(d.high)
          const wickBot = scaleY(d.low)

          const upColor   = 'rgb(var(--up))'
          const downColor = 'rgb(var(--down))'
          const color     = up ? upColor : downColor
          const fid = `glow-${up ? 'up' : 'down'}-${chartId}`

          const isLast = i === data.length - 1
          const animClass = (animate && isLast && zapping) ? 'animate-kline-zap' : ''

          return (
            <g
              key={`bar-${i}`}
              onMouseEnter={() => setHoveredIdx(i)}
              onMouseLeave={() => setHoveredIdx(null)}
              className="cursor-crosshair"
            >
              {/* Wick */}
              <line
                x1={x} y1={wickTop} x2={x} y2={wickBot}
                stroke={color} strokeWidth={1.2} opacity={0.8}
                filter={isLast ? `url(#${fid})` : undefined}
              />
              {/* Body */}
              {up ? (
                <rect
                  x={x - candleW / 2} y={bodyTop}
                  width={candleW} height={bodyH}
                  fill={upColor} rx={1}
                  className={animClass}
                  filter={isLast ? `url(#${fid})` : undefined}
                />
              ) : (
                <rect
                  x={x - candleW / 2} y={bodyTop}
                  width={candleW} height={bodyH}
                  fill="rgba(var(--down), 0.15)"
                  stroke={downColor} strokeWidth={1.5} rx={1}
                  className={animClass}
                  filter={isLast ? `url(#${fid})` : undefined}
                />
              )}
              {/* Latest bar: horizontal price line extending to right */}
              {isLast && (
                <>
                  <line
                    x1={x + candleW / 2 + 2} y1={scaleY(d.close)}
                    x2={W - PADDING.right} y2={scaleY(d.close)}
                    stroke={color} strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5}
                  />
                  <rect
                    x={W - PADDING.right + 1} y={scaleY(d.close) - 9}
                    width={58} height={18} rx={3}
                    fill={color} opacity={0.9}
                  />
                  <text
                    x={W - PADDING.right + 4} y={scaleY(d.close) + 4}
                    fontSize={11} fontWeight="bold"
                    fontFamily="var(--font-data)"
                    fill="rgb(var(--bg))"
                  >
                    {d.close.toFixed(2)}
                  </text>
                </>
              )}
            </g>
          )
        })}

        {/* ── Date labels along bottom ─────────────────────────── */}
        {data.filter((_, i) => i % Math.max(1, Math.floor(data.length / 6)) === 0).map((d, i) => {
          const origIdx = data.indexOf(d)
          return (
            <text
              key={`date-${i}`}
              x={scaleX(origIdx)}
              y={H - PADDING.bottom + 16}
              textAnchor="middle"
              fontSize={9}
              fontFamily="var(--font-data)"
              fill="rgb(var(--muted))"
              opacity={0.6}
            >
              {d.date}
            </text>
          )
        })}
      </svg>

      {/* ── OHLC hover tooltip ─────────────────────────────────── */}
      {hover && (
        <div
          className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-10
                     rounded-lg border border-[rgb(var(--accent))/0.3] bg-[rgb(var(--bg))]/95
                     px-4 py-2.5 shadow-2xl shadow-black/60 backdrop-blur-sm"
        >
          <div className="mb-1.5 text-center text-xs text-[rgb(var(--muted))] font-mono">{hover.date}</div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-[11px] font-mono">
            {([
              ['O', hover.open],
              ['H', hover.high],
              ['L', hover.low],
              ['C', hover.close],
            ] as [string, number][]).map(([label, val]) => {
              const up = isUp(hover.open, hover.close)
              return (
                <span key={label} className="flex items-center gap-1.5">
                  <span className="text-[rgb(var(--muted))]">{label}</span>
                  <span className={`font-semibold ${up ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}`}>
                    {Number(val).toFixed(2)}
                  </span>
                </span>
              )
            })}
          </div>
          {hover.volume != null && (
            <div className="mt-1 text-center text-[10px] text-[rgb(var(--muted))]">
              VOL {hover.volume.toLocaleString()}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
