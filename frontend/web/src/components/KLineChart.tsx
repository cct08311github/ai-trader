/**
 * KLineChart.tsx — Kyo Nakamura
 * SVG K-line / OHLC chart with artistic neon treatment.
 *
 * Props:
 *   symbol     — ticker symbol for display
 *   data       — { date, open, high, low, close, volume }[]
 *   width      — optional SVG width (default: 100%)
 *   height     — optional SVG height (default: 320)
 *   animate    — trigger K-line zap animation on new data
 */

import { useEffect, useMemo, useRef, useState } from 'react'

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

// ── Helpers ──────────────────────────────────────────────────────────────────
function isUp(open: number, close: number) { return close >= open }
function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)) }

const PADDING = { top: 16, right: 72, bottom: 40, left: 12 }

export default function KLineChart({
  symbol,
  data = [],
  width: widthProp,
  height = 320,
  animate = false,
}: Props) {
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
    setContainerWidth(containerRef.current.contentRect.width)
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

  const W = widthProp ?? containerWidth
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

  if (!data.length) {
    return (
      <div ref={containerRef} className="relative w-full" style={{ height: H }}>
        <div className="flex h-full items-center justify-center">
          <p className="text-sm text-[rgb(var(--muted))]">K線資料載入中…</p>
        </div>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative w-full select-none" style={{ height: H }}>
      <svg
        width={W}
        height={H}
        className="overflow-visible"
        aria-label={`${symbol ?? ''} K線圖`}
      >
        {/* ── Volume bars (background) ──────────────────────────── */}
        {data.map((d, i) => {
          const x = scaleX(i)
          const up = isUp(d.open, d.close)
          const barH = ((d.volume ?? 0) / maxVol) * innerH * 0.22
          const barY = H - PADDING.bottom - barH
          const col = up ? 'rgba(var(--up), 0.45)' : 'rgba(var(--down), 0.45)'
          return (
            <rect
              key={`vol-${i}`}
              x={x - candleW / 2}
              y={barY}
              width={candleW}
              height={barH}
              fill={col}
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
                stroke="rgba(var(--border), 0.4)" strokeDasharray="4 4"
              />
              <text
                x={W - PADDING.right + 4} y={y + 4}
                fontSize={10}
                fontFamily="var(--font-data)"
                fill="rgb(var(--muted))"
              >
                {price.toFixed(2)}
              </text>
            </g>
          )
        })}

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

          // Body: open → close
          const bodyTop = scaleY(Math.max(d.open, d.close))
          const bodyBot = scaleY(Math.min(d.open, d.close))
          const bodyH = Math.max(1, bodyBot - bodyTop)

          // Wick
          const wickTop = scaleY(d.high)
          const wickBot = scaleY(d.low)

          const upColor    = `rgb(var(--up))`
          const downColor  = `rgb(var(--down))`
          const color      = up ? upColor : downColor
          const glowColor  = up ? 'rgba(var(--up-glow))' : 'rgba(var(--down-glow))'

          // Glow filter ref
          const fid = `glow-${up ? 'up' : 'down'}`

          const animClass = (animate && i === data.length - 1 && zapping)
            ? 'animate-kline-zap'
            : ''

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
                stroke={color}
                strokeWidth={1.2}
                opacity={0.8}
                filter={`url(#${fid})`}
              />

              {/* Body — filled if up, hollow rect if down */}
              {up ? (
                // 實心霓虹綠上漲
                <rect
                  x={x - candleW / 2} y={bodyTop}
                  width={candleW} height={bodyH}
                  fill={upColor}
                  rx={1}
                  className={animClass}
                  filter={`url(#${fid})`}
                />
              ) : (
                // 空心血紅下跌
                <>
                  <rect
                    x={x - candleW / 2} y={bodyTop}
                    width={candleW} height={bodyH}
                    fill="rgba(var(--down), 0.1)"
                    stroke={downColor}
                    strokeWidth={1.5}
                    rx={1}
                    className={animClass}
                    filter={`url(#${fid})`}
                  />
                </>
              )}
            </g>
          )
        })}

        {/* ── Defs: glow filters ───────────────────────────────── */}
        <defs>
          <filter id="glow-up" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glow-down" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
      </svg>

      {/* ── OHLC hover tooltip ─────────────────────────────────── */}
      {hover && (
        <div
          className="pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 z-10
                     rounded-xl border border-[rgb(var(--accent))/0.4] bg-[rgb(var(--bg))]/95
                     px-4 py-2.5 shadow-2xl shadow-black/60 backdrop-blur-sm"
        >
          <div className="mb-1.5 text-center text-xs text-[rgb(var(--muted))]">{hover.date}</div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-0.5 text-[11px] font-mono">
            {([
              ['O', hover.open],
              ['H', hover.high],
              ['L', hover.low],
              ['C', hover.close],
            ] as [string, number][]).map(([label, val]) => (
              <span key={label} className="flex items-center gap-1.5">
                <span className="text-[rgb(var(--muted))]">{label}</span>
                <span className="font-semibold text-[rgb(var(--text))]">{Number(val).toFixed(2)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Symbol watermark ───────────────────────────────────── */}
      {symbol && (
        <div className="pointer-events-none absolute bottom-2 right-20 text-[10px] font-mono
                         text-[rgb(var(--muted))] opacity-40">
          {symbol}
        </div>
      )}
    </div>
  )
}
