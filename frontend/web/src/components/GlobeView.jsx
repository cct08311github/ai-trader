/**
 * GlobeView.jsx — 3D Globe component for Geopolitical Dashboard
 *
 * Uses react-globe.gl for WebGL-based 3D globe rendering.
 * Lazy-loaded via React.lazy for code splitting.
 *
 * Props:
 *   events         — array of geopolitical events { lat, lng, impact_score, category, title, id }
 *   selectedEvent  — currently selected event object or null
 *   onSelectEvent  — callback(event) when a marker is clicked
 */

import React, { useRef, useEffect, useCallback } from 'react'
import Globe from 'react-globe.gl'

// ── Category color map ─────────────────────────────────────────────────────────

const CATEGORY_COLOR = {
  conflict:  '#ef4444',
  trade_war: '#f97316',
  sanctions: '#eab308',
  policy:    '#3b82f6',
  election:  '#a855f7',
}

function getCategoryColor(category) {
  return CATEGORY_COLOR[category] ?? '#71717a'
}

// HTML escape to prevent XSS in globe tooltip template literals
function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

// ── GlobeView ──────────────────────────────────────────────────────────────────

function GlobeView({ events = [], selectedEvent, onSelectEvent }) {
  const globeRef = useRef(null)
  const interactedRef = useRef(false)

  // Only render markers with valid coordinates
  const markers = events.filter(ev => ev.lat != null && ev.lng != null)

  // Convert events to globe point data
  const pointsData = markers.map(ev => ({
    lat: ev.lat,
    lng: ev.lng,
    size: Math.max(0.3, Math.min(1.5, (Number(ev.impact_score) || 3) * 0.15)),
    color: getCategoryColor(ev.category),
    event: ev,
  }))

  // Auto-rotate — stop on user interaction
  useEffect(() => {
    const globe = globeRef.current
    if (!globe) return

    const controls = globe.controls()
    if (!controls) return

    controls.autoRotate = true
    controls.autoRotateSpeed = 0.4

    function handleInteraction() {
      if (!interactedRef.current) {
        interactedRef.current = true
        controls.autoRotate = false
      }
    }

    const domEl = globe.renderer()?.domElement
    if (domEl) {
      domEl.addEventListener('pointerdown', handleInteraction, { once: true })
    }

    return () => {
      if (domEl) {
        domEl.removeEventListener('pointerdown', handleInteraction)
      }
    }
  }, [])

  // Re-enable auto-rotate 3 s after last interaction ends
  useEffect(() => {
    const globe = globeRef.current
    if (!globe) return

    const controls = globe.controls()
    if (!controls) return

    let timer
    const domEl = globe.renderer()?.domElement

    function onPointerUp() {
      clearTimeout(timer)
      timer = setTimeout(() => {
        controls.autoRotate = true
        interactedRef.current = false
      }, 3000)
    }

    if (domEl) {
      domEl.addEventListener('pointerup', onPointerUp)
    }

    return () => {
      clearTimeout(timer)
      if (domEl) {
        domEl.removeEventListener('pointerup', onPointerUp)
      }
    }
  }, [])

  // Focus camera on selected event
  useEffect(() => {
    const globe = globeRef.current
    if (!globe || !selectedEvent?.lat || !selectedEvent?.lng) return

    globe.pointOfView(
      { lat: selectedEvent.lat, lng: selectedEvent.lng, altitude: 1.8 },
      600
    )
  }, [selectedEvent])

  const handlePointClick = useCallback(
    point => {
      if (point?.event) onSelectEvent(point.event)
    },
    [onSelectEvent]
  )

  const pointColor = useCallback(point => {
    if (selectedEvent && point?.event?.id === selectedEvent.id) {
      return '#ffffff'
    }
    return point.color
  }, [selectedEvent])

  const pointRadius = useCallback(point => {
    const base = point.size
    return selectedEvent && point?.event?.id === selectedEvent.id
      ? base * 1.6
      : base
  }, [selectedEvent])

  const pointLabel = useCallback(point => {
    const ev = point?.event
    if (!ev) return ''
    return `
      <div style="
        background: rgba(10,10,20,0.88);
        border: 1px solid ${point.color}88;
        border-radius: 4px;
        padding: 6px 10px;
        font-size: 12px;
        color: #e5e7eb;
        max-width: 200px;
        font-family: ui-sans-serif, system-ui, sans-serif;
        pointer-events: none;
      ">
        <div style="font-weight: 600; margin-bottom: 4px; line-height: 1.3;">${esc(ev.title)}</div>
        <div style="color: ${esc(point.color)}; font-size: 11px;">
          衝擊指數: ${esc(ev.impact_score ?? '-')}
        </div>
      </div>
    `
  }, [])

  return (
    <div
      className="rounded-sm border overflow-hidden relative"
      style={{
        backgroundColor: '#060b18',
        borderColor: 'rgb(var(--border))',
        minHeight: 400,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Panel header */}
      <div
        className="px-3 py-2 border-b flex items-center justify-between flex-shrink-0"
        style={{ borderColor: 'rgb(var(--border))' }}
      >
        <span
          className="text-xs font-medium tracking-widest uppercase"
          style={{ fontFamily: 'var(--font-mono)', color: 'rgb(var(--muted))' }}
        >
          全球風險地圖 3D
        </span>
        <div className="flex items-center gap-3">
          {Object.entries(CATEGORY_COLOR).map(([cat, color]) => {
            const labels = {
              conflict: '衝突', trade_war: '貿易戰',
              sanctions: '制裁', policy: '政策', election: '選舉',
            }
            return (
              <span key={cat} className="flex items-center gap-1">
                <span
                  className="inline-block w-2 h-2 rounded-full"
                  style={{ backgroundColor: color }}
                />
                <span
                  style={{
                    color: 'rgb(var(--muted))',
                    fontFamily: 'var(--font-ui)',
                    fontSize: 10,
                  }}
                >
                  {labels[cat]}
                </span>
              </span>
            )
          })}
        </div>
      </div>

      {/* Globe */}
      <div style={{ flex: 1, minHeight: 360 }}>
        <Globe
          ref={globeRef}
          width={undefined}
          height={360}
          backgroundColor="#060b18"
          globeImageUrl="/assets/earth-night.jpg"
          bumpImageUrl="/assets/earth-topology.png"
          atmosphereColor="#1e3a5f"
          atmosphereAltitude={0.15}
          pointsData={pointsData}
          pointLat="lat"
          pointLng="lng"
          pointColor={pointColor}
          pointRadius={pointRadius}
          pointAltitude={0.01}
          pointResolution={6}
          pointLabel={pointLabel}
          onPointClick={handlePointClick}
          pointsMerge={false}
        />
      </div>

      {/* No coordinates notice */}
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

export default GlobeView
