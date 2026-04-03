/**
 * EmergencyStopButton.tsx -- Kyo Nakamura
 *
 * NUCLEAR DETONATION button for emergency position close-out.
 * This button must be impossible to miss and impossible to
 * accidentally trigger.
 *
 * Idle:        Pulsing border with dark blood-red seepage glow
 * Hover:       Intensified glow + contamination ring expands
 * Holding:     Progress bar fills with lava, screen border tints red
 * Detonation:  Full-screen blood-red overlay + screen shake + icon pulse
 * Done:        Brief emerald confirmation before reset
 *
 * Hold duration: 1.8s -- long enough to be intentional, short enough
 * in a panic. Mobile: touch-hold works identically.
 */

import { useEffect, useRef, useState } from 'react'
import { AlertOctagon, Skull } from 'lucide-react'

interface Props {
  onTrigger: () => void | Promise<void>
  disabled?: boolean
  label?: string
}

type Phase = 'idle' | 'arming' | 'detonating' | 'done' | 'error'

export default function EmergencyStopButton({
  onTrigger,
  disabled = false,
  label = '緊急止損',
}: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [holdTime, setHoldTime] = useState(0)
  const holdInterval = useRef<ReturnType<typeof setInterval> | null>(null)
  const detonateTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const resetTimeoutRef = useRef<ReturnType<typeof setTimeout>>()
  const HOLD_DURATION = 1800

  // C-4: Clear all timers on unmount
  useEffect(() => {
    return () => {
      if (holdInterval.current) clearInterval(holdInterval.current)
      if (detonateTimeoutRef.current) clearTimeout(detonateTimeoutRef.current)
      if (resetTimeoutRef.current) clearTimeout(resetTimeoutRef.current)
    }
  }, [])

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
          detonateTimeoutRef.current = setTimeout(async () => {
            try {
              await onTrigger()
              setPhase('done')
              resetTimeoutRef.current = setTimeout(() => setPhase('idle'), 3000)
            } catch (e) {
              console.error('[EmergencyStop] FAILED:', e)
              setPhase('error')
              resetTimeoutRef.current = setTimeout(() => setPhase('idle'), 5000)
            }
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
            background: `radial-gradient(
              ellipse at center,
              rgba(185,28,28,0.95) 0%,
              rgba(127,29,29,0.85) 40%,
              rgba(80,10,10,0.90) 70%,
              rgba(0,0,0,0.95) 100%
            )`,
          }}
        >
          <div className="flex h-full flex-col items-center justify-center gap-6">
            <div className="relative">
              <Skull className="h-28 w-28 text-red-200 animate-pulse" />
              {/* Contamination rings */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-40 w-40 rounded-full border-2 border-red-400/30 animate-contamination" />
              </div>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="h-56 w-56 rounded-full border border-red-400/15 animate-contamination"
                     style={{ animationDelay: '0.5s' }} />
              </div>
            </div>
            <div className="text-center">
              <div className="text-5xl font-black tracking-[0.3em] text-red-200"
                   style={{ textShadow: '0 0 40px rgba(225,29,72,0.8), 0 0 80px rgba(225,29,72,0.4)' }}>
                核 爆 觸 發
              </div>
              <div className="mt-4 text-lg font-mono tracking-widest text-red-300/80">
                EMERGENCY LIQUIDATION IN PROGRESS
              </div>
              <div className="mt-2 text-sm text-red-400/60 animate-pulse">
                緊急平倉執行中...
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Screen shake wrapper ───────────────────────────────── */}
      {phase === 'detonating' && (
        <div className="fixed inset-0 z-[9997] animate-nuclear-shake pointer-events-none" />
      )}

      {/* ── Screen edge tint during arming ─────────────────────── */}
      {isHolding && (
        <div
          className="fixed inset-0 z-[9996] pointer-events-none transition-opacity"
          style={{
            opacity: holdPct / 200,
            boxShadow: `inset 0 0 ${40 + holdPct}px rgba(185,28,28,${holdPct / 150})`,
          }}
        />
      )}

      {/* ── Button ─────────────────────────────────────────────── */}
      <button
        type="button"
        onMouseDown={startHold}
        onMouseUp={cancelHold}
        onMouseLeave={cancelHold}
        onTouchStart={startHold}
        onTouchEnd={cancelHold}
        disabled={disabled || phase === 'detonating' || phase === 'done' || phase === 'error'}
        role="button"
        aria-label={
          phase === 'arming' ? '緊急止損 — 持續按住中'
          : phase === 'detonating' ? '緊急止損 — 執行中'
          : phase === 'done' ? '緊急止損 — 已完成'
          : phase === 'error' ? '緊急止損 — 執行失敗，請手動確認倉位'
          : '緊急止損 — 按住1.8秒觸發'
        }
        className={`
          relative flex items-center gap-2.5 px-6 py-3
          font-mono text-sm font-black tracking-widest uppercase select-none
          transition-all duration-200 overflow-hidden
          ${disabled
            ? 'rounded-xl border border-slate-700 bg-slate-900/50 text-slate-600 cursor-not-allowed'
            : phase === 'done'
              ? 'rounded-xl border-2 border-emerald-500/50 bg-emerald-900/20 text-emerald-400'
              : phase === 'error'
                ? 'rounded-xl border-2 border-red-600 bg-red-900/40 text-red-200 cursor-pointer'
                : 'border-2 border-rose-700 bg-rose-950/60 text-rose-300 cursor-pointer'
          }
        `}
        style={{
          // Brutalist: no border-radius when not disabled/done/error
          borderRadius: disabled || phase === 'done' || phase === 'error' ? '0.75rem' : '4px',
          // Progress bar fill
          background: disabled ? undefined
            : phase === 'done'
              ? 'rgba(16,185,129,0.1)'
              : phase === 'error'
                ? 'rgba(220,38,38,0.15)'
                : `linear-gradient(to right,
                  rgba(185,28,28,${isHolding ? 0.7 : 0.4}) ${holdPct}%,
                  rgba(13,13,13,0.8) ${holdPct}%)`,
          // Glow intensity scales with hold
          boxShadow: disabled ? 'none'
            : phase === 'error'
              ? '0 0 16px rgba(220,38,38,0.6)'
              : phase === 'done'
                ? '0 0 12px rgba(16,185,129,0.4)'
              : isHolding
                ? `0 0 ${20 + holdPct * 0.3}px rgba(185,28,28,0.6),
                   0 0 ${40 + holdPct * 0.5}px rgba(185,28,28,0.3),
                   inset 0 0 20px rgba(185,28,28,0.2)`
                : '0 0 6px rgba(185,28,28,0.3), 0 0 20px rgba(185,28,28,0.1)',
          transition: 'box-shadow 0.3s, background 0.05s',
        }}
      >
        {/* Pulsing lava animation behind text */}
        {!disabled && phase === 'idle' && (
          <div
            aria-hidden="true"
            className="absolute inset-0 opacity-0 hover:opacity-100 transition-opacity duration-500 animate-lava-pulse"
            style={{
              background: 'radial-gradient(ellipse at 50% 100%, rgba(185,28,28,0.2) 0%, transparent 70%)',
              borderRadius: 'inherit',
            }}
          />
        )}

        {/* Hold progress bar overlay */}
        {isHolding && (
          <div
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `linear-gradient(90deg,
                rgba(225,29,72,0.3) 0%,
                rgba(185,28,28,0.5) ${holdPct}%,
                transparent ${holdPct}%)`,
            }}
          />
        )}

        <AlertOctagon
          className={`relative h-5 w-5 flex-shrink-0 ${
            phase === 'done' ? 'text-emerald-400'
            : isHolding ? 'text-rose-300 animate-pulse'
            : 'text-rose-400'
          }`}
        />
        <span className="relative whitespace-nowrap">
          {phase === 'error'
            ? '⚠️ 止損失敗 — 請手動確認倉位'
            : phase === 'done'
              ? '>>> 已觸發'
              : phase === 'detonating'
                ? '執行中...'
                : label}
        </span>
        {!disabled && phase === 'idle' && (
          <span className="relative text-[9px] text-rose-500/50 ml-1 tracking-normal lowercase">
            hold 1.8s
          </span>
        )}
        {isHolding && (
          <span className="relative text-[10px] text-rose-200 font-mono ml-1">
            {Math.ceil((HOLD_DURATION - holdTime) / 1000)}s
          </span>
        )}
      </button>
    </>
  )
}
