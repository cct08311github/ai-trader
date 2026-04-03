/**
 * VariantSwitcher.tsx -- Kyo Nakamura
 * Theme variant toggle with three battle aesthetics.
 *
 * Variants:
 *   A -- "Brutalist Dark"     混凝土戰壕 (concrete bunker + raw edges + red warnings)
 *   B -- "Neon Night Market"  霓虹夜市   (electric colors + CRT scanlines + chaos)
 *   C -- "Wabi-Sabi Data"     侘寂數據   (earth tones + ink wash + zen decay)
 *
 * Drop this in the header/toolbar. Persists choice in sessionStorage.
 */

import { useState } from 'react'
import { useBattleTheme } from './BattleTheme'

type Variant = 'A' | 'B' | 'C'

const VARIANT_META: Record<Variant, {
  short: string
  full: string
  icon: string
  desc: string
  accent: string
}> = {
  A: {
    short: '戰壕',
    full: 'Brutalist Dark',
    icon: '////',
    desc: '混凝土 + 銳角 + 紅色警告',
    accent: '#10b981',
  },
  B: {
    short: '夜市',
    full: 'Neon Night Market',
    icon: '||||',
    desc: '霓虹 + CRT掃描線 + 夜市閃爍',
    accent: '#34d399',
  },
  C: {
    short: '侘寂',
    full: 'Wabi-Sabi Data',
    icon: '~~~~',
    desc: '大地色 + 水墨漸層 + 禪意數據',
    accent: '#c4a24d',
  },
}

const STORAGE_KEY = 'ai-trader-theme-variant'

export function useVariant() {
  const stored = sessionStorage.getItem(STORAGE_KEY) as Variant | null
  const [variant, setVariantState] = useState<Variant>(stored ?? 'A')
  useBattleTheme(variant)

  function setVariant(v: Variant) {
    setVariantState(v)
    sessionStorage.setItem(STORAGE_KEY, v)
  }

  return { variant, setVariant }
}

export default function VariantSwitcher({ className = '' }: { className?: string }) {
  const { variant, setVariant } = useVariant()
  const [open, setOpen] = useState(false)
  const meta = VARIANT_META[variant]

  return (
    <div className={`relative ${className}`}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label="切換主題變體"
        aria-expanded={open}
        className="flex items-center gap-2 border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.4]
                   px-3 py-1.5 text-xs font-mono font-medium text-[rgb(var(--text))] transition
                   hover:bg-[rgb(var(--surface))/0.6] hover:border-[rgb(var(--accent))/0.5]"
        style={{ borderRadius: '3px' }}
      >
        <span
          className="text-[10px] font-bold tracking-widest"
          style={{ color: meta.accent }}
        >
          {meta.icon}
        </span>
        <span className="hidden sm:inline">{meta.short}</span>
        <svg
          className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div
            className="absolute right-0 top-full z-50 mt-2 w-56 border border-[rgb(var(--border))]
                       bg-[rgb(var(--bg))] shadow-2xl shadow-black/60 animate-card-explode overflow-hidden"
            style={{ borderRadius: '4px' }}
          >
            <div className="border-b border-[rgb(var(--border))] px-3 py-2">
              <p className="text-[9px] uppercase tracking-[0.2em] font-mono text-[rgb(var(--muted))]">
                THEME VARIANT
              </p>
            </div>
            {(['A', 'B', 'C'] as const).map(v => {
              const m = VARIANT_META[v]
              const isActive = variant === v
              return (
                <button
                  key={v}
                  type="button"
                  onClick={() => { setVariant(v); setOpen(false) }}
                  className={`flex w-full items-start gap-3 px-3 py-3 text-left transition-all
                              ${isActive
                                ? 'bg-[rgb(var(--accent))/0.1] border-l-2'
                                : 'hover:bg-[rgb(var(--surface))/0.4] border-l-2 border-transparent'
                              }`}
                  style={{
                    borderLeftColor: isActive ? m.accent : 'transparent',
                  }}
                >
                  <span
                    className="mt-0.5 text-[11px] font-mono font-bold tracking-widest"
                    style={{ color: m.accent }}
                  >
                    {m.icon}
                  </span>
                  <div className="min-w-0">
                    <div className={`text-sm font-semibold ${isActive ? 'text-[rgb(var(--accent))]' : 'text-[rgb(var(--text))]'}`}>
                      {m.full}
                    </div>
                    <div className="text-[10px] text-[rgb(var(--muted))] mt-0.5">{m.desc}</div>
                  </div>
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
