/**
 * Geopolitical.jsx — Geopolitical Dashboard
 *
 * Desktop layout: 60/40 split — World Map (left) + News Feed (right)
 * Mobile (<768px): hide map, show news feed + market impact + category filter
 *
 * Data sources:
 *   GET /api/geopolitical/latest  — latest 20 events (React Query, staleTime 15 min)
 *   GET /api/geopolitical/events  — paginated event list
 */

import React, { useState, useCallback, lazy, Suspense } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
} from 'react-simple-maps'
import { DataCard } from '../components/ui/DataCard'
import { SentimentIndicator } from '../components/ui/SentimentIndicator'
import { AlertBadge } from '../components/ui/AlertBadge'
import { authFetch, getApiBase } from '../lib/auth'

// ── Lazy-loaded 3D Globe (code splitting) ─────────────────────────────────────
const GlobeView = lazy(() => import('../components/GlobeView'))

// ── WebGL / mobile detection ──────────────────────────────────────────────────

function hasWebGL() {
  try { return !!document.createElement('canvas').getContext('webgl') } catch { return false }
}

function isMobile() {
  return window.matchMedia('(pointer: coarse)').matches || window.innerWidth < 768
}

// ── Constants ─────────────────────────────────────────────────────────────────

const GEO_URL = '/assets/countries-110m.json'

const CATEGORY_CONFIG = {
  conflict:  { color: '#ef4444', label: '衝突',   dot: '#ef4444' },
  trade_war: { color: '#f97316', label: '貿易戰', dot: '#f97316' },
  sanctions: { color: '#eab308', label: '制裁',   dot: '#eab308' },
  policy:    { color: '#3b82f6', label: '政策',   dot: '#3b82f6' },
  election:  { color: '#a855f7', label: '選舉',   dot: '#a855f7' },
}

const ALL_CATEGORIES = ['conflict', 'trade_war', 'sanctions', 'policy', 'election']

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchLatest() {
  const base = getApiBase()
  const res = await authFetch(`${base}/api/geopolitical/latest`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  if (!json.ok) throw new Error('API returned ok=false')
  return json.data ?? []
}

// ── Utility helpers ───────────────────────────────────────────────────────────

/** Validate external URL — only allow http/https to prevent javascript: XSS */
function safeHref(url) {
  return typeof url === 'string' && url.startsWith('http') ? url : '#'
}

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '剛剛'
  if (mins < 60) return `${mins} 分鐘前`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs} 小時前`
  const days = Math.floor(hrs / 24)
  return `${days} 天前`
}

function truncate(str, len = 100) {
  if (!str) return ''
  return str.length > len ? str.slice(0, len) + '…' : str
}

function impactColor(score) {
  if (score >= 8) return '#ef4444'
  if (score >= 5) return '#f97316'
  return '#eab308'
}

/** Derive market impact summary cards from top events.
 *  Handles both legacy {sector: number} and structured
 *  {sectors: [...], assets: [...], direction: "...", note: "..."} formats.
 */
function buildMarketImpact(events) {
  const impacts = []
  for (const ev of events.slice(0, 5)) {
    let mi = ev.market_impact
    if (!mi) continue
    // Parse if stored as JSON string
    if (typeof mi === 'string') {
      try { mi = JSON.parse(mi) } catch { continue }
    }
    if (typeof mi !== 'object') continue

    // Structured backend format: { sectors: [...], direction: "bullish"|"bearish"|"neutral", ... }
    if (Array.isArray(mi.sectors)) {
      mi.sectors.forEach(s => {
        impacts.push({
          sector: s,
          val: mi.direction === 'bearish' ? -1 : 1,
          category: ev.category,
          direction: mi.direction || 'neutral',
          score: ev.impact_score,
        })
      })
    } else {
      // Legacy format: { sector: number, ... }
      Object.entries(mi).forEach(([sector, val]) => {
        if (typeof val === 'number') {
          impacts.push({ sector, val, category: ev.category })
        }
      })
    }
  }
  return impacts.slice(0, 6)
}

// ── Sub-components ────────────────────────────────────────────────────────────

/** Category badge — colored dot + label */
function CategoryBadge({ category }) {
  const cfg = CATEGORY_CONFIG[category] || { dot: '#71717a', label: category }
  return (
    <span className="inline-flex items-center gap-1">
      <span
        className="inline-block w-2 h-2 rounded-full flex-shrink-0"
        style={{ backgroundColor: cfg.dot }}
      />
      <span
        className="text-xs"
        style={{ color: cfg.dot, fontFamily: 'var(--font-ui)' }}
      >
        {cfg.label}
      </span>
    </span>
  )
}

/** Impact score badge */
function ImpactBadge({ score }) {
  if (score == null) return null
  const color = impactColor(score)
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs font-mono"
      style={{
        backgroundColor: `${color}22`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {score}
    </span>
  )
}

/** Tooltip overlay for map markers */
function MapTooltip({ event, x, y }) {
  if (!event) return null
  return (
    <div
      className="absolute z-50 pointer-events-none"
      style={{ left: x + 10, top: y - 10 }}
    >
      <div
        className="rounded-sm shadow-lg px-3 py-2 text-xs max-w-[200px]"
        style={{
          backgroundColor: 'rgb(var(--card))',
          border: '1px solid rgb(var(--border))',
          fontFamily: 'var(--font-ui)',
          color: 'rgb(var(--text))',
        }}
      >
        <div className="font-medium mb-1 leading-snug">{event.title}</div>
        <div className="flex items-center gap-2">
          <CategoryBadge category={event.category} />
          <ImpactBadge score={event.impact_score} />
        </div>
      </div>
    </div>
  )
}

function deriveSentiment(event) {
  let mi = event.market_impact
  if (!mi) return 'neutral'
  if (typeof mi === 'string') {
    try { mi = JSON.parse(mi) } catch { return 'neutral' }
  }
  return mi?.direction || 'neutral'
}

/** Single news feed item */
function NewsFeedItem({ event, isSelected, onClick }) {
  const [expanded, setExpanded] = useState(false)
  const cfg = CATEGORY_CONFIG[event.category] || { dot: '#71717a' }

  function handleClick() {
    onClick(event)
    setExpanded(prev => !prev)
  }

  const links = Array.isArray(event.source_links)
    ? event.source_links
    : typeof event.source_links === 'string'
    ? [event.source_links]
    : []

  return (
    <div
      className="cursor-pointer rounded-sm transition-colors"
      style={{
        borderLeft: `2px solid ${isSelected ? cfg.dot : 'transparent'}`,
        backgroundColor: isSelected ? `${cfg.dot}11` : 'transparent',
        paddingLeft: 8,
        paddingRight: 8,
        paddingTop: 8,
        paddingBottom: 8,
      }}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={e => e.key === 'Enter' && handleClick()}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="flex items-center gap-2 flex-wrap">
          <CategoryBadge category={event.category} />
          <ImpactBadge score={event.impact_score} />
          <SentimentIndicator sentiment={deriveSentiment(event)} />
        </div>
        <span
          className="text-xs text-th-muted flex-shrink-0"
          style={{ fontFamily: 'var(--font-mono)', color: 'rgb(var(--muted))' }}
        >
          {timeAgo(event.event_date)}
        </span>
      </div>

      {/* Title */}
      <div
        className="text-sm font-medium leading-snug mb-1"
        style={{ fontFamily: 'var(--font-ui)', color: 'rgb(var(--text))' }}
      >
        {event.title}
      </div>

      {/* Summary — truncated or full */}
      <div
        className="text-xs leading-relaxed"
        style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-ui)' }}
      >
        {expanded ? event.summary : truncate(event.summary, 100)}
      </div>

      {/* Source links when expanded */}
      {expanded && links.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {links.map((link, i) => (
            <a
              key={i}
              href={safeHref(link)}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs underline"
              style={{ color: 'rgb(var(--accent))' }}
              onClick={e => e.stopPropagation()}
            >
              來源 {i + 1}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

/** Market impact summary card strip */
function MarketImpactStrip({ events }) {
  const impacts = buildMarketImpact(events)
  if (impacts.length === 0) return null

  return (
    <div
      className="rounded-sm border p-3"
      style={{
        backgroundColor: 'rgb(var(--card))',
        borderColor: 'rgb(var(--border))',
      }}
    >
      <div
        className="text-xs font-medium tracking-widest uppercase mb-3"
        style={{
          fontFamily: 'var(--font-mono)',
          color: 'rgb(var(--muted))',
        }}
      >
        市場影響概況
      </div>
      <div className="flex flex-wrap gap-2">
        {impacts.map((item, i) => {
          const val = parseFloat(item.val)
          const isPositive = !isNaN(val) ? val >= 0 : item.direction !== 'bearish'
          const color = isPositive ? 'rgb(var(--up))' : 'rgb(var(--danger))'
          return (
            <div
              key={i}
              className="px-3 py-2 rounded-sm text-xs flex items-center gap-2"
              style={{
                backgroundColor: isPositive
                  ? 'rgba(var(--up), 0.08)'
                  : 'rgba(var(--danger), 0.08)',
                border: `1px solid ${isPositive ? 'rgba(var(--up),0.2)' : 'rgba(var(--danger),0.2)'}`,
                fontFamily: 'var(--font-ui)',
                color: 'rgb(var(--text))',
              }}
            >
              <span>最受影響板塊: {item.sector}</span>
              <span style={{ color, fontFamily: 'var(--font-mono)' }}>
                {isPositive ? '▲' : '▼'}
                {!isNaN(val) ? `${Math.abs(val).toFixed(1)}%` : (item.direction || '')}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Category filter tabs (mobile) */
function CategoryFilterTabs({ active, onChange }) {
  return (
    <div className="flex overflow-x-auto gap-1 pb-1">
      <button
        className="px-3 py-1.5 rounded-sm text-xs flex-shrink-0 transition-colors"
        style={{
          fontFamily: 'var(--font-ui)',
          backgroundColor: active === null ? 'rgb(var(--accent))' : 'rgb(var(--card))',
          color: active === null ? '#000' : 'rgb(var(--muted))',
          border: '1px solid rgb(var(--border))',
        }}
        onClick={() => onChange(null)}
      >
        全部
      </button>
      {ALL_CATEGORIES.map(cat => {
        const cfg = CATEGORY_CONFIG[cat]
        const isActive = active === cat
        return (
          <button
            key={cat}
            className="px-3 py-1.5 rounded-sm text-xs flex-shrink-0 transition-colors"
            style={{
              fontFamily: 'var(--font-ui)',
              backgroundColor: isActive ? cfg.dot : 'rgb(var(--card))',
              color: isActive ? '#fff' : 'rgb(var(--muted))',
              border: `1px solid ${isActive ? cfg.dot : 'rgb(var(--border))'}`,
            }}
            onClick={() => onChange(cat)}
          >
            {cfg.label}
          </button>
        )
      })}
    </div>
  )
}

// ── World Map panel ───────────────────────────────────────────────────────────

function WorldMapPanel({ events, selectedEvent, onSelectEvent }) {
  const [tooltip, setTooltip] = useState({ event: null, x: 0, y: 0 })

  // Only events with coordinates
  const markers = events.filter(
    ev => ev.lat != null && ev.lng != null
  )

  function markerRadius(score) {
    const s = Number(score) || 3
    return Math.max(4, Math.min(16, s * 1.4))
  }

  return (
    <div
      className="rounded-sm border overflow-hidden relative"
      style={{
        backgroundColor: 'rgb(var(--card))',
        borderColor: 'rgb(var(--border))',
        minHeight: 340,
      }}
    >
      {/* Panel header */}
      <div
        className="px-3 py-2 border-b flex items-center justify-between"
        style={{ borderColor: 'rgb(var(--border))' }}
      >
        <span
          className="text-xs font-medium tracking-widest uppercase"
          style={{ fontFamily: 'var(--font-mono)', color: 'rgb(var(--muted))' }}
        >
          全球風險地圖
        </span>
        <div className="flex items-center gap-3">
          {ALL_CATEGORIES.map(cat => (
            <span key={cat} className="flex items-center gap-1">
              <span
                className="inline-block w-2 h-2 rounded-full"
                style={{ backgroundColor: CATEGORY_CONFIG[cat].dot }}
              />
              <span
                className="text-xs"
                style={{
                  color: 'rgb(var(--muted))',
                  fontFamily: 'var(--font-ui)',
                  fontSize: 10,
                }}
              >
                {CATEGORY_CONFIG[cat].label}
              </span>
            </span>
          ))}
        </div>
      </div>

      {/* Map */}
      <div className="relative">
        <ComposableMap
          projectionConfig={{ scale: 130, center: [10, 10] }}
          style={{ width: '100%', height: 'auto' }}
        >
          <Geographies geography={GEO_URL}>
            {({ geographies }) =>
              geographies.map(geo => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  style={{
                    default: {
                      fill: 'rgba(var(--grid), 0.15)',
                      stroke: 'rgb(var(--border))',
                      strokeWidth: 0.4,
                      outline: 'none',
                    },
                    hover: {
                      fill: 'rgba(var(--grid), 0.25)',
                      stroke: 'rgb(var(--border))',
                      strokeWidth: 0.4,
                      outline: 'none',
                    },
                    pressed: { outline: 'none' },
                  }}
                />
              ))
            }
          </Geographies>

          {markers.map(ev => {
            const cfg = CATEGORY_CONFIG[ev.category] || { color: '#71717a' }
            const r = markerRadius(ev.impact_score)
            const isSelected = selectedEvent?.id === ev.id
            return (
              <Marker
                key={ev.id}
                coordinates={[ev.lng, ev.lat]}
                onClick={() => onSelectEvent(ev)}
                onMouseEnter={e => {
                  const rect = e.currentTarget.closest('svg')?.getBoundingClientRect()
                  const svgX = e.clientX - (rect?.left ?? 0)
                  const svgY = e.clientY - (rect?.top ?? 0)
                  setTooltip({ event: ev, x: svgX, y: svgY })
                }}
                onMouseLeave={() => setTooltip({ event: null, x: 0, y: 0 })}
                style={{ cursor: 'pointer' }}
              >
                <circle
                  r={r}
                  fill={cfg.color}
                  fillOpacity={isSelected ? 0.95 : 0.65}
                  stroke={isSelected ? '#fff' : cfg.color}
                  strokeWidth={isSelected ? 2 : 0.8}
                  style={{
                    filter: isSelected
                      ? `drop-shadow(0 0 6px ${cfg.color})`
                      : undefined,
                    transition: 'all 0.15s ease',
                  }}
                />
              </Marker>
            )
          })}
        </ComposableMap>

        {/* Tooltip */}
        <MapTooltip {...tooltip} />
      </div>

      {/* No-coordinates notice */}
      {markers.length === 0 && events.length > 0 && (
        <div
          className="px-3 pb-3 text-xs"
          style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-ui)' }}
        >
          目前事件無座標資料，地圖標記暫無顯示
        </div>
      )}
    </div>
  )
}

// ── News Feed panel ───────────────────────────────────────────────────────────

function NewsFeedPanel({ events, selectedEvent, onSelectEvent, categoryFilter }) {
  const filtered =
    categoryFilter === null
      ? events
      : events.filter(ev => ev.category === categoryFilter)

  return (
    <div
      className="rounded-sm border flex flex-col"
      style={{
        backgroundColor: 'rgb(var(--card))',
        borderColor: 'rgb(var(--border))',
        maxHeight: 480,
      }}
    >
      <div
        className="px-3 py-2 border-b flex items-center justify-between flex-shrink-0"
        style={{ borderColor: 'rgb(var(--border))' }}
      >
        <span
          className="text-xs font-medium tracking-widest uppercase"
          style={{ fontFamily: 'var(--font-mono)', color: 'rgb(var(--muted))' }}
        >
          地緣政治事件
        </span>
        <span
          className="text-xs"
          style={{ fontFamily: 'var(--font-mono)', color: 'rgb(var(--muted))' }}
        >
          {filtered.length} 則
        </span>
      </div>

      <div className="overflow-y-auto flex-1 divide-y" style={{ divideColor: 'rgb(var(--border))' }}>
        {filtered.length === 0 && (
          <div
            className="flex items-center justify-center py-12 text-xs"
            style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-ui)' }}
          >
            尚無事件資料
          </div>
        )}
        {filtered.map(ev => (
          <NewsFeedItem
            key={ev.id}
            event={ev}
            isSelected={selectedEvent?.id === ev.id}
            onClick={onSelectEvent}
          />
        ))}
      </div>
    </div>
  )
}

// ── 2D/3D toggle button ───────────────────────────────────────────────────────

function MapViewToggle({ use3D, onChange, disabled }) {
  return (
    <div
      className="inline-flex rounded-sm overflow-hidden"
      style={{ border: '1px solid rgb(var(--border))' }}
      role="group"
      aria-label="地圖檢視切換"
    >
      {['2D', '3D'].map(mode => {
        const isActive = mode === '3D' ? use3D : !use3D
        return (
          <button
            key={mode}
            disabled={disabled && mode === '3D'}
            onClick={() => onChange(mode === '3D')}
            className="px-3 py-1 text-xs transition-colors"
            style={{
              fontFamily: 'var(--font-mono)',
              backgroundColor: isActive ? 'rgb(var(--accent))' : 'rgb(var(--card))',
              color: isActive ? '#000' : disabled && mode === '3D' ? 'rgb(var(--muted))' : 'rgb(var(--muted))',
              cursor: disabled && mode === '3D' ? 'not-allowed' : 'pointer',
              borderRight: mode === '2D' ? '1px solid rgb(var(--border))' : 'none',
              opacity: disabled && mode === '3D' ? 0.4 : 1,
            }}
            title={disabled && mode === '3D' ? '此裝置不支援 WebGL 3D 地圖' : undefined}
          >
            {mode}
          </button>
        )
      })}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function Geopolitical() {
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [categoryFilter, setCategoryFilter] = useState(null)

  // 3D toggle — persist in sessionStorage; auto-disable if WebGL or mobile unavailable
  const webglAvailable = hasWebGL() && !isMobile()
  const [use3D, setUse3D] = useState(() => {
    if (!webglAvailable) return false
    try {
      return sessionStorage.getItem('geo_map_3d') !== 'false'
    } catch {
      return true
    }
  })

  const handleToggle3D = useCallback(value => {
    setUse3D(value)
    try { sessionStorage.setItem('geo_map_3d', String(value)) } catch {}
  }, [])

  const { data: events = [], isLoading, error } = useQuery({
    queryKey: ['geopolitical', 'latest'],
    queryFn: fetchLatest,
    staleTime: 15 * 60 * 1000, // 15 minutes
    retry: 2,
  })

  const handleSelectEvent = useCallback(ev => {
    setSelectedEvent(prev => (prev?.id === ev.id ? null : ev))
  }, [])

  // Decide which map to render on desktop
  const showGlobe = use3D && webglAvailable

  return (
    <div data-testid="geopolitical-page" className="space-y-4 p-4">
      {/* Page title */}
      <div className="flex items-center justify-between">
        <h1
          className="text-lg font-medium"
          style={{ fontFamily: 'var(--font-ui)', color: 'rgb(var(--text))' }}
        >
          地緣政治分析
        </h1>
        <div className="flex items-center gap-3">
          {/* 2D/3D toggle — only visible on desktop */}
          <div className="hidden md:block">
            <MapViewToggle
              use3D={use3D}
              onChange={handleToggle3D}
              disabled={!webglAvailable}
            />
          </div>
          {isLoading && (
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-4 border-2 border-th-border border-t-th-accent rounded-full animate-spin"
                style={{ borderTopColor: 'rgb(var(--accent))' }}
              />
              <span
                className="text-xs"
                style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-ui)' }}
              >
                更新中…
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <AlertBadge
          level="red"
          message={`資料載入失敗：${error.message || '請稍後重試'}`}
        />
      )}

      {/* Mobile: category filter tabs */}
      <div className="md:hidden">
        <CategoryFilterTabs active={categoryFilter} onChange={setCategoryFilter} />
      </div>

      {/* Desktop: 60/40 split layout */}
      <div className="hidden md:grid gap-4" style={{ gridTemplateColumns: '60% 1fr' }}>
        {/* Left: World Map (2D) or Globe (3D) */}
        <div data-testid="world-map">
          {isLoading ? (
            <DataCard title="全球風險地圖" loading />
          ) : showGlobe ? (
            <Suspense
              fallback={
                <div
                  className="rounded-sm border flex items-center justify-center"
                  style={{
                    backgroundColor: 'rgb(var(--card))',
                    borderColor: 'rgb(var(--border))',
                    minHeight: 400,
                    color: 'rgb(var(--muted))',
                    fontFamily: 'var(--font-ui)',
                    fontSize: 13,
                  }}
                >
                  載入 3D 地球儀…
                </div>
              }
            >
              <GlobeView
                events={events}
                selectedEvent={selectedEvent}
                onSelectEvent={handleSelectEvent}
              />
            </Suspense>
          ) : (
            <WorldMapPanel
              events={events}
              selectedEvent={selectedEvent}
              onSelectEvent={handleSelectEvent}
            />
          )}
        </div>

        {/* Right: News Feed */}
        <div data-testid="geo-events">
          {isLoading ? (
            <DataCard title="地緣政治事件" loading />
          ) : (
            <NewsFeedPanel
              events={events}
              selectedEvent={selectedEvent}
              onSelectEvent={handleSelectEvent}
              categoryFilter={null}
            />
          )}
        </div>
      </div>

      {/* Mobile: full-width news feed only (always 2D, no globe on mobile) */}
      <div className="md:hidden">
        {isLoading ? (
          <DataCard title="地緣政治事件" loading />
        ) : (
          <NewsFeedPanel
            events={events}
            selectedEvent={selectedEvent}
            onSelectEvent={handleSelectEvent}
            categoryFilter={categoryFilter}
          />
        )}
      </div>

      {/* Bottom: Market Impact Summary */}
      {!isLoading && events.length > 0 && (
        <MarketImpactStrip events={events} />
      )}

      {/* Selected event detail (sidebar card) */}
      {selectedEvent && (
        <DataCard
          title="事件詳情"
          accentColor={CATEGORY_CONFIG[selectedEvent.category]?.color}
        >
          <div className="space-y-3">
            {/* Title + badges */}
            <div className="flex items-start justify-between gap-2">
              <h2
                className="text-sm font-semibold leading-snug"
                style={{ fontFamily: 'var(--font-ui)', color: 'rgb(var(--text))' }}
              >
                {selectedEvent.title}
              </h2>
              <button
                className="text-xs flex-shrink-0 px-2 py-0.5 rounded-sm"
                style={{
                  color: 'rgb(var(--muted))',
                  border: '1px solid rgb(var(--border))',
                  fontFamily: 'var(--font-mono)',
                  background: 'transparent',
                  cursor: 'pointer',
                }}
                onClick={() => setSelectedEvent(null)}
              >
                ✕ 關閉
              </button>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              <CategoryBadge category={selectedEvent.category} />
              <ImpactBadge score={selectedEvent.impact_score} />
              <SentimentIndicator
                sentiment={
                  selectedEvent.impact_score >= 7
                    ? 'bearish'
                    : selectedEvent.impact_score >= 4
                    ? 'neutral'
                    : 'bullish'
                }
              />
              <span
                className="text-xs"
                style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-mono)' }}
              >
                {timeAgo(selectedEvent.event_date)}
              </span>
            </div>

            {/* Full summary */}
            {selectedEvent.summary && (
              <p
                className="text-sm leading-relaxed"
                style={{ color: 'rgb(var(--text))', fontFamily: 'var(--font-ui)' }}
              >
                {selectedEvent.summary}
              </p>
            )}

            {/* Market impact breakdown */}
            {selectedEvent.market_impact &&
              typeof selectedEvent.market_impact === 'object' &&
              Object.keys(selectedEvent.market_impact).length > 0 && (
                <div>
                  <div
                    className="text-xs mb-2 uppercase tracking-widest"
                    style={{ color: 'rgb(var(--muted))', fontFamily: 'var(--font-mono)' }}
                  >
                    市場影響
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(selectedEvent.market_impact).map(([sector, val]) => {
                      const v = parseFloat(val)
                      const isPos = v >= 0
                      const c = isPos ? 'rgb(var(--up))' : 'rgb(var(--danger))'
                      return (
                        <span
                          key={sector}
                          className="text-xs px-2 py-1 rounded-sm"
                          style={{
                            backgroundColor: isPos
                              ? 'rgba(var(--up), 0.1)'
                              : 'rgba(var(--danger), 0.1)',
                            color: c,
                            fontFamily: 'var(--font-mono)',
                          }}
                        >
                          {sector} {isPos ? '▲' : '▼'}
                          {Math.abs(v).toFixed(1)}%
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}

            {/* Tags */}
            {Array.isArray(selectedEvent.tags) && selectedEvent.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {selectedEvent.tags.map(tag => (
                  <span
                    key={tag}
                    className="text-xs px-2 py-0.5 rounded-sm"
                    style={{
                      backgroundColor: 'rgba(var(--grid), 0.15)',
                      color: 'rgb(var(--muted))',
                      fontFamily: 'var(--font-ui)',
                    }}
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            )}

            {/* Source links */}
            {(() => {
              const links = Array.isArray(selectedEvent.source_links)
                ? selectedEvent.source_links
                : typeof selectedEvent.source_links === 'string'
                ? [selectedEvent.source_links]
                : []
              if (links.length === 0) return null
              return (
                <div className="flex flex-wrap gap-2">
                  {links.map((link, i) => (
                    <a
                      key={i}
                      href={safeHref(link)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs underline"
                      style={{ color: 'rgb(var(--accent))', fontFamily: 'var(--font-ui)' }}
                    >
                      來源 {i + 1} →
                    </a>
                  ))}
                </div>
              )
            })()}
          </div>
        </DataCard>
      )}
    </div>
  )
}
