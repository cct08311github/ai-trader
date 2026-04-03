import React, { useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'

// ---------------------------------------------------------------------------
// API fetch
// ---------------------------------------------------------------------------

const API_BASE = (import.meta?.env?.VITE_API_BASE ?? 'http://localhost:8080').replace(/\/$/, '')

async function fetchLatestIndices() {
  const res = await fetch(`${API_BASE}/api/indices/latest`, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem('auth_token') || ''}`,
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${body}`)
  }
  const json = await res.json()
  // Unwrap unified envelope
  return Array.isArray(json?.data) ? json.data : []
}

// ---------------------------------------------------------------------------
// Symbol → display label map (short names for the ticker bar)
// ---------------------------------------------------------------------------

const SHORT_NAMES = {
  '^TWII':    'TAIEX',
  '^GSPC':    'S&P 500',
  '^IXIC':    'NASDAQ',
  '^SOX':     'SOX',
  '^VIX':     'VIX',
  'DX-Y.NYB': 'DXY',
  '^N225':    'Nikkei',
  '^HSI':     'HSI',
  'GC=F':     'Gold',
  'CL=F':     'Oil',
  '^TNX':     '10Y UST',
  'USDTWD=X': 'USD/TWD',
  'BTC-USD':  'BTC',
  '^KS11':    'KOSPI',
}

// ---------------------------------------------------------------------------
// Single ticker item
// ---------------------------------------------------------------------------

function TickerItem({ symbol, name, closePrice, changePct }) {
  const isUp    = changePct > 0
  const isDown  = changePct < 0
  const isFlat  = changePct === 0 || changePct == null

  const changeColor = isUp
    ? 'rgb(var(--up))'
    : isDown
    ? 'rgb(var(--down))'
    : 'rgb(var(--muted))'

  const arrow = isUp ? '▲' : isDown ? '▼' : '▬'

  const priceStr = closePrice != null
    ? closePrice.toLocaleString('en-US', { maximumFractionDigits: 4 })
    : '—'

  const changeStr = changePct != null
    ? `${isUp ? '+' : ''}${changePct.toFixed(2)}%`
    : '—'

  const label = SHORT_NAMES[symbol] || name || symbol

  return (
    <span
      className="inline-flex items-center gap-1.5 px-4 whitespace-nowrap select-none"
      style={{ fontFamily: 'var(--font-mono)' }}
    >
      <span
        className="text-[11px] font-semibold tracking-widest uppercase"
        style={{ color: 'rgb(var(--muted))' }}
      >
        {label}
      </span>
      <span
        className="text-[12px] font-bold"
        style={{ color: 'rgb(var(--text))' }}
      >
        {priceStr}
      </span>
      <span
        className="text-[11px] font-semibold"
        style={{ color: changeColor }}
      >
        {arrow} {changeStr}
      </span>
      {/* separator */}
      <span
        className="text-[10px] opacity-25 ml-2"
        style={{ color: 'rgb(var(--border))' }}
      >
        |
      </span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Ticker track (duplicated for seamless loop)
// ---------------------------------------------------------------------------

function TickerTrack({ items }) {
  if (!items.length) return null

  const itemEls = items.map((row) => (
    <TickerItem
      key={row.symbol}
      symbol={row.symbol}
      name={row.name}
      closePrice={row.close_price}
      changePct={row.change_pct}
    />
  ))

  // Duplicate the list so the CSS marquee loops seamlessly
  return (
    <div className="global-ticker__track" aria-hidden="false">
      <span className="global-ticker__inner">
        {itemEls}
        {/* Duplicate for infinite scroll illusion */}
        {itemEls}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function TickerSkeleton() {
  return (
    <div
      className="global-ticker__skeleton flex items-center gap-6 px-4 overflow-hidden"
      aria-label="市場指數載入中"
    >
      {Array.from({ length: 7 }).map((_, i) => (
        <span
          key={i}
          className="inline-block h-3 rounded animate-pulse"
          style={{
            width: `${60 + (i % 3) * 20}px`,
            background: 'rgb(var(--border))',
            opacity: 0.4,
          }}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// GlobalTicker
// ---------------------------------------------------------------------------

/**
 * GlobalTicker — horizontal scrolling bar showing live global market indices.
 *
 * Props:
 *   className   — extra CSS classes for the wrapper
 *   pauseOnHover — pause animation on hover (default true)
 */
export default function GlobalTicker({ className = '', pauseOnHover = true }) {
  const trackRef = useRef(null)

  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['market-indices-latest'],
    queryFn: fetchLatestIndices,
    staleTime: 60 * 1000,        // 60 s — matches backend cache TTL
    refetchInterval: 60 * 1000,  // auto-refresh every 60 s
    retry: 1,
  })

  // Pause/resume scroll animation on hover (CSS var trick)
  useEffect(() => {
    if (!pauseOnHover || !trackRef.current) return
    const el = trackRef.current
    const pause = () => el.style.setProperty('--ticker-play-state', 'paused')
    const resume = () => el.style.setProperty('--ticker-play-state', 'running')
    el.addEventListener('mouseenter', pause)
    el.addEventListener('mouseleave', resume)
    return () => {
      el.removeEventListener('mouseenter', pause)
      el.removeEventListener('mouseleave', resume)
    }
  }, [pauseOnHover])

  return (
    <>
      {/* Scoped keyframe + ticker CSS — injected once per mount */}
      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .global-ticker__track {
          overflow: hidden;
          width: 100%;
          cursor: default;
        }
        .global-ticker__inner {
          display: inline-flex;
          align-items: center;
          white-space: nowrap;
          animation: ticker-scroll 60s linear infinite;
          animation-play-state: var(--ticker-play-state, running);
        }
        /* Mobile: slower + smaller text */
        @media (max-width: 640px) {
          .global-ticker__inner {
            animation-duration: 90s;
            font-size: 10px;
          }
        }
      `}</style>

      <div
        ref={trackRef}
        className={`
          global-ticker
          w-full flex items-center
          border-b border-[rgb(var(--border))]
          bg-[rgb(var(--surface))]
          h-8 min-h-[2rem]
          overflow-hidden
          ${className}
        `}
        role="marquee"
        aria-label="全球市場指數即時行情"
        style={{ '--ticker-play-state': 'running' }}
      >
        {isLoading && <TickerSkeleton />}

        {isError && !isLoading && (
          <span
            className="text-[11px] px-4"
            style={{ color: 'rgb(var(--danger))', fontFamily: 'var(--font-mono)' }}
          >
            市場資料暫時無法取得
          </span>
        )}

        {!isLoading && !isError && rows.length === 0 && (
          <span
            className="text-[11px] px-4"
            style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-mono)' }}
          >
            尚無市場資料 — 請執行 market_index_fetcher
          </span>
        )}

        {!isLoading && !isError && rows.length > 0 && (
          <TickerTrack items={rows} />
        )}
      </div>
    </>
  )
}
