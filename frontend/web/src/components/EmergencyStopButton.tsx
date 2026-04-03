/**
 * EmergencyStopButton.tsx — Kyo Nakamura
 * NUCLEAR DETONATION button for emergency position close-out.
 *
 * Hover:  border pulse + dark blood-red seepage glow
 * Active: full-screen blood-red overlay + screen shake
 *
 * Usage:
 *   <EmergencyStopButton onTrigger={async () => { await closeAll(); }} />
 */

import { useEffect, useRef, useState } from 'react'
import { AlertOctagon } from 'lucide-react'

interface Props {
  onTrigger: () => void | Promise<void>
  disabled?: boolean
  label?: string
}

export default function EmergencyStopButton({
  onTrigger,
  disabled = false,
  label = '緊急止損',
}: Props) {
  const [phase, setPhase] = useState<'idle' | 'arming' | 'detonating' | 'done'>('idle')
  const [holdTime, setHoldTime] = useState(0)
  const holdInterval = useRef<ReturnType<typeof setInterval> | null>(null)
  const HOLD_DURATION = 1800 // ms to hold for detonation

  function startHold() {
    if (disabled || phase !== 'idle') return
    setPhase('arming')
    setHoldTime(0)
    holdInterval.current = setInterval(() => {
      setHoldTime(t => {
        const next = t + 50
        if (next >= HOLD_DURATION) {
          clearInterval(holdInterval.current!)
          setPhase('detonating')
          setTimeout(() => {
            onTrigger().catch(console.error)
            setPhase('done')
            setTimeout(() => setPhase('idle'), 1200)
          }, 100)
          return next
        }
        return next
      })
    }, 50)
  }

  function cancelHold() {
    if (holdInterval.current) clearInterval(holdInterval.current)
    if (phase === 'arming') setPhase('idle')
    setHoldTime(0)
  }

  const holdPct = Math.min(100, (holdTime / HOLD_DURATION) * 100)
  const isHolding = phase === 'arming'

  return (
    <>
      {/* ── Nuclear flash overlay ──────────────────────────────── */}
      {phase === 'detonating' && (
        <div
          aria-live="assertive"
          className="fixed inset-0 z-[9998] animate-nuclear-flash"
          style={{
            background: 'radial-gradient(ellipse at center, rgba(185,28,28,0.95) 0%, rgba(127,29,29,0.85) 60%, rgba(0,0,0,0.9) 100%)',
          }}
        >
          <div className="flex h-full flex-col items-center justify-center">
            <AlertOctagon className="h-24 w-24 text-red-200 animate-pulse" />
            <div className="mt-6 text-4xl font-black tracking-widest text-red-200">
              核 爆 觸 發
            </div>
            <div className="mt-3 text-lg text-red-300">緊急平倉執行中…</div>
          </div>
        </div>
      )}

      {/* ── Screen shake wrapper ───────────────────────────────── */}
      {phase === 'detonating' && (
        <div className="fixed inset-0 z-[9997] animate-nuclear-shake pointer-events-none" />
      )}

      {/* ── Button ─────────────────────────────────────────────── */}
      <button
        type="button"
        onMouseDown={startHold}
        onMouseUp={cancelHold}
        onMouseLeave={cancelHold}
        onTouchStart={startHold}
        onTouchEnd={cancelHold}
        disabled={disabled || phase === 'detonating' || phase === 'done'}
        aria-label="緊急止損 — 按住1.8秒觸發"
        aria-pressed={phase !== 'idle'}
        className={`
          relative flex items-center gap-2 rounded-2xl border-2 px-6 py-3
          font-mono text-sm font-black tracking-widest uppercase select-none
          transition-all duration-200 overflow-hidden
          ${disabled
            ? 'border-slate-700 bg-slate-900/50 text-slate-600 cursor-not-allowed'
            : phase === 'done'
              ? 'border-emerald-500/50 bg-emerald-900/20 text-emerald-400'
              : 'border-rose-700 bg-rose-950/60 text-rose-300 cursor-pointer'
          }
        `}
        style={{
          // Progress bar fill
          background: disabled ? undefined
            : phase === 'done'
              ? 'rgba(16,185,129,0.1)'
              : `linear-gradient(to right, rgba(185,28,28,${isHolding ? 0.7 : 0.4}) ${holdPct}%, rgba(13,13,13,0.8) ${holdPct}%)`,
          // Hover glow
          boxShadow: disabled ? 'none'
            : phase === 'done'
              ? '0 0 12px rgba(16,185,129,0.4)'
              : isHolding
                ? '0 0 20px rgba(185,28,28,0.6), 0 0 40px rgba(185,28,28,0.3), inset 0 0 20px rgba(185,28,28,0.2)'
                : '0 0 6px rgba(185,28,28,0.3)',
          transition: 'box-shadow 0.3s, background 0.05s',
        }}
      >
        {/* Blood seep animation on hover */}
        {!disabled && phase === 'idle' && (
          <div
            aria-hidden="true"
            className="absolute inset-0 rounded-2xl opacity-0 hover:opacity-100 transition-opacity duration-300"
            style={{
              background: 'radial-gradient(ellipse at 50% 100%, rgba(185,28,28,0.15) 0%, transparent 70%)',
              animation: 'lava-pulse 2s ease-in-out infinite',
            }}
          />
        )}

        {/* Progress ring (mobile-friendly) */}
        {isHolding && (
          <svg
            aria-hidden="true"
            className="absolute inset-0 w-full h-full pointer-events-none opacity-30"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <rect
              x="0" y="0"
              width={holdPct + '%'}
              height="100%"
              fill="rgba(185,28,28,0.6)"
            />
          </svg>
        )}

        <AlertOctagon
          className={`relative h-5 w-5 flex-shrink-0 ${
            phase === 'done' ? 'text-emerald-400' : 'text-rose-400'
          }`}
        />
        <span className="relative">
          {phase === 'done' ? '✓ 已觸發' : phase === 'detonating' ? '執行中…' : label}
        </span>

        {!disabled && phase === 'idle' && (
          <span className="relative text-[10px] text-rose-500/60 ml-1">
            HOLD
          </span>
        )}
      </button>
    </>
  )
}
