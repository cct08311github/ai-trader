/**
 * EconomicCalendar.jsx — Upcoming economic events from /api/macro/calendar.
 *
 * Used in MacroAnalysis (Analysis page) and Dashboard page.
 *
 * Props:
 *   maxItems   — max events to display (default: 8)
 *   className  — extra CSS classes for the outer wrapper
 */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { authFetch, getApiBase } from '../lib/auth'

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchCalendar() {
  const res = await authFetch(`${getApiBase()}/api/macro/calendar`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return Array.isArray(json?.data) ? json.data : []
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const IMPORTANCE_COLORS = {
  critical: { bg: 'rgba(220,38,38,0.12)', text: 'rgb(239,68,68)',  border: 'rgba(220,38,38,0.4)' },
  high:     { bg: 'rgba(202,138,4,0.12)', text: 'rgb(234,179,8)',  border: 'rgba(202,138,4,0.4)' },
  medium:   { bg: 'rgba(99,102,241,0.10)',text: 'rgb(129,140,248)',border: 'rgba(99,102,241,0.3)' },
  low:      { bg: 'rgba(100,116,139,0.10)',text:'rgb(148,163,184)',border: 'rgba(100,116,139,0.2)' },
}

const COUNTRY_FLAGS = {
  US: '🇺🇸',
  TW: '🇹🇼',
  EU: '🇪🇺',
  JP: '🇯🇵',
  CN: '🇨🇳',
  GB: '🇬🇧',
}

function ImportanceBadge({ importance }) {
  const level = importance || 'low'
  const colors = IMPORTANCE_COLORS[level] || IMPORTANCE_COLORS.low
  return (
    <span
      style={{
        display: 'inline-block',
        background: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.border}`,
        borderRadius: '2px',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.6rem',
        letterSpacing: '0.08em',
        padding: '1px 5px',
        whiteSpace: 'nowrap',
        textTransform: 'uppercase',
        flexShrink: 0,
      }}
    >
      {level}
    </span>
  )
}

function getWeekBounds() {
  const today = new Date()
  const dayOfWeek = today.getDay()        // 0=Sun, 6=Sat
  const startOfWeek = new Date(today)
  startOfWeek.setDate(today.getDate() - dayOfWeek)
  const endOfWeek = new Date(startOfWeek)
  endOfWeek.setDate(startOfWeek.getDate() + 6)
  return {
    start: startOfWeek.toISOString().slice(0, 10),
    end:   endOfWeek.toISOString().slice(0, 10),
  }
}

function classifyDate(dateStr) {
  const todayStr = new Date().toISOString().slice(0, 10)
  if (dateStr === todayStr) return 'today'
  const { start, end } = getWeekBounds()
  if (dateStr >= start && dateStr <= end) return 'this_week'
  return 'future'
}

// ---------------------------------------------------------------------------
// Single event row
// ---------------------------------------------------------------------------

function EventRow({ event }) {
  const dateClass = classifyDate(event.date)
  const flag      = COUNTRY_FLAGS[event.country] || '🌐'
  const isToday   = dateClass === 'today'
  const isWeek    = dateClass === 'this_week'

  const rowBg = isToday
    ? 'rgba(var(--accent-raw, 34 197 94), 0.06)'
    : 'transparent'

  const dateFontColor = isToday
    ? 'rgb(var(--accent))'
    : isWeek
    ? 'rgb(var(--text))'
    : 'rgb(var(--muted))'

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        padding: '0.35rem 0.6rem',
        background: rowBg,
        borderRadius: '2px',
        borderLeft: isToday
          ? '2px solid rgb(var(--accent))'
          : isWeek
          ? '2px solid rgba(var(--accent-raw, 34 197 94), 0.3)'
          : '2px solid transparent',
        transition: 'background 0.1s ease',
      }}
    >
      {/* Date */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.7rem',
          color: dateFontColor,
          whiteSpace: 'nowrap',
          minWidth: '5rem',
          fontWeight: isToday ? 700 : 400,
        }}
      >
        {isToday ? '▶ 今日' : event.date}
      </span>

      {/* Flag */}
      <span style={{ fontSize: '0.85rem', flexShrink: 0 }} title={event.country}>
        {flag}
      </span>

      {/* Event name */}
      <span
        style={{
          fontFamily: 'var(--font-ui)',
          fontSize: '0.78rem',
          color: 'rgb(var(--text))',
          flex: 1,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={event.event}
      >
        {event.event}
      </span>

      {/* Importance badge */}
      <ImportanceBadge importance={event.importance} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function CalendarSkeleton({ rows = 5 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          style={{
            height: '1.6rem',
            borderRadius: '2px',
            background: 'rgb(var(--border))',
            opacity: 0.3 + (i % 3) * 0.1,
            animation: 'pulse 1.4s ease-in-out infinite',
            animationDelay: `${i * 0.1}s`,
          }}
        />
      ))}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.25; }
          50%       { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// EconomicCalendar
// ---------------------------------------------------------------------------

export default function EconomicCalendar({ maxItems = 8, className = '' }) {
  const { data: events = [], isLoading, isError } = useQuery({
    queryKey: ['economic-calendar'],
    queryFn: fetchCalendar,
    staleTime: 30 * 60 * 1000,    // 30 min — calendar changes infrequently
    refetchInterval: 60 * 60 * 1000, // 1 hour
    retry: 1,
  })

  const visibleEvents = events.slice(0, maxItems)

  return (
    <div
      className={className}
      style={{
        background: 'rgb(var(--card))',
        border: '1px solid rgb(var(--border))',
        borderRadius: '2px',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.5rem 0.75rem',
          borderBottom: '1px solid rgb(var(--border))',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-ui)',
            fontSize: '0.78rem',
            fontWeight: 600,
            color: 'rgb(var(--text))',
            letterSpacing: '0.02em',
          }}
        >
          經濟日曆
        </span>
        {events.length > 0 && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.65rem',
              color: 'rgb(var(--muted))',
            }}
          >
            近期 {visibleEvents.length} 筆
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '0.4rem 0.2rem' }}>
        {isLoading && <CalendarSkeleton rows={4} />}

        {isError && !isLoading && (
          <p
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: '0.78rem',
              color: 'rgb(var(--danger, 239 68 68))',
              padding: '0.5rem 0.6rem',
              margin: 0,
            }}
          >
            無法載入經濟日曆
          </p>
        )}

        {!isLoading && !isError && visibleEvents.length === 0 && (
          <p
            style={{
              fontFamily: 'var(--font-ui)',
              fontSize: '0.78rem',
              color: 'rgb(var(--muted))',
              padding: '0.5rem 0.6rem',
              margin: 0,
            }}
          >
            近期無重大經濟事件
          </p>
        )}

        {!isLoading && !isError && visibleEvents.map((evt, idx) => (
          <EventRow key={`${evt.date}-${idx}`} event={evt} />
        ))}
      </div>
    </div>
  )
}
