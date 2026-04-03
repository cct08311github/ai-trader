/**
 * VariantSwitcher.tsx — Kyo Nakamura
 * Theme variant toggle UI with three distinct battle aesthetics.
 * Drop this anywhere (e.g. header) to let the trader switch visual modes live.
 *
 * Variants:
 *   A — 作戰終端機  (墨戰黑 + 霓虹綠/血紅)  [DEFAULT]
 *   B — 霓虹夜市    (深紫 + 粉綠/金 + 夜市閃爍燈)
 *   C — 廟宇金光    (啞光黑 + 金箔漸層 + 紅色警示)
 */

import { useState } from 'react'
import { useBattleTheme } from './BattleTheme'

const VARIANT_LABELS = {
  A: { short: '終端機', full: '作戰終端機', icon: '⬛', desc: '墨黑 · 霓虹綠/血紅' },
  B: { short: '夜市',   full: '霓虹夜市',   icon: '🌃', desc: '深紫 · 粉綠/金 + 閃爍燈' },
  C: { short: '金光',   full: '廟宇金光',   icon: '🏛️', desc: '啞光黑 · 金箔漸層 + 紅色警示' },
}

// Persist variant choice in sessionStorage
const STORAGE_KEY = 'ai-trader-theme-variant'

export function useVariant() {
  const stored = sessionStorage.getItem(STORAGE_KEY) as 'A' | 'B' | 'C' | null
  const [variant, setVariantState] = useState<'A' | 'B' | 'C'>(stored ?? 'A')
  useBattleTheme(variant)

  function setVariant(v: 'A' | 'B' | 'C') {
    setVariantState(v)
    sessionStorage.setItem(STORAGE_KEY, v)
  }

  return { variant, setVariant }
}

// ── Compact toggle pill (for header) ─────────────────────────────────────────
export default function VariantSwitcher({ className = '' }) {
  const { variant, setVariant } = useVariant()
  const [open, setOpen] = useState(false)

  return (
    <div className={`relative ${className}`}>
      {/* Trigger button */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label="切換主題變體"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.4]
                   px-2.5 py-1.5 text-xs font-medium text-[rgb(var(--text))] transition
                   hover:bg-[rgb(var(--surface))/0.6] hover:border-[rgb(var(--accent))/0.5]"
      >
        <span className="text-base">{VARIANT_LABELS[variant].icon}</span>
        <span className="hidden sm:inline">{VARIANT_LABELS[variant].short}</span>
        <svg className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
             fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 top-full z-50 mt-2 w-52 rounded-xl border border-[rgb(var(--border))]
                           bg-[rgb(var(--bg))] shadow-2xl shadow-black/60 animate-card-explode overflow-hidden">
            <div className="border-b border-[rgb(var(--border))] px-3 py-2">
              <p className="text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">主題變體</p>
            </div>
            {(['A', 'B', 'C'] as const).map(v => (
              <button
                key={v}
                type="button"
                onClick={() => { setVariant(v); setOpen(false) }}
                className={`flex w-full items-start gap-3 px-3 py-2.5 text-left transition
                            ${variant === v
                              ? 'bg-[rgb(var(--accent))/0.12] border-l-2 border-[rgb(var(--accent))]'
                              : 'hover:bg-[rgb(var(--surface))/0.4] border-l-2 border-transparent'
                            }`}
              >
                <span className="mt-0.5 text-lg">{VARIANT_LABELS[v].icon}</span>
                <div>
                  <div className={`text-sm font-semibold ${variant === v ? 'text-[rgb(var(--accent))]' : 'text-[rgb(var(--text))]'}`}>
                    {VARIANT_LABELS[v].full}
                  </div>
                  <div className="text-[10px] text-[rgb(var(--muted))]">{VARIANT_LABELS[v].desc}</div>
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
