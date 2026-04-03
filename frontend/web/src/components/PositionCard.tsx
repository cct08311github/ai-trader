/**
 * PositionCard.tsx -- Kyo Nakamura
 *
 * Intelligence briefing card for a single position.
 *
 * Visual behavior:
 *   - Collapsed: symbol + P&L + chip score thermometer
 *   - Expanded (hover/tap): mini KLine + full KPI grid + close button
 *   - Losing positions emit contamination ring animation
 *   - P&L digits glitch with chromatic aberration on value change
 *   - Brutalist variant: hard edges, no rounded corners
 *   - Night Market variant: neon border glow
 *   - Wabi-Sabi variant: ink-wash fade-in, muted palette
 */

import { useEffect, useRef, useState } from 'react'
import { Lock, TrendingUp, TrendingDown, Zap, AlertTriangle } from 'lucide-react'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'
import KLineChart from './KLineChart'

interface Position {
  symbol: string
  name?: string
  qty?: number
  avgCost?: number
  avg_price?: number
  lastPrice?: number
  last_price?: number
  unrealPnl?: number
  chip_score?: number
  chip_health_score?: number
  weight?: number
  price_source?: string
}

interface Props {
  position: Position
  isLocked?: boolean
  onClose?: () => void
  klineData?: Array<{ date: string; open: number; high: number; low: number; close: number; volume?: number }>
}

// PM confidence thermometer (0-10)
function ConfidenceMeter({ score }: { score: number | null | undefined }) {
  if (score == null) return null
  const pct = Math.min(100, Math.max(0, (score / 10) * 100))
  const color = score >= 7 ? 'emerald' : score >= 4 ? 'amber' : 'rose'
  const cls = {
    emerald: { bar: 'bg-emerald-500', text: 'text-emerald-400', glow: 'shadow-emerald-500/40' },
    amber:   { bar: 'bg-amber-500',   text: 'text-amber-400',   glow: 'shadow-amber-500/30' },
    rose:    { bar: 'bg-rose-500',     text: 'text-rose-400',    glow: 'shadow-rose-500/30' },
  }[color]

  return (
    <div className="flex items-center gap-2">
      <span className="text-[9px] uppercase tracking-wider text-[rgb(var(--muted))]">PM</span>
      <div className="relative h-1 w-16 rounded-full bg-[rgb(var(--border))] overflow-hidden">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${cls.bar} shadow ${cls.glow} transition-all duration-700`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-[11px] font-mono font-bold ${cls.text}`}>{score}</span>
    </div>
  )
}

// Mini sparkline SVG (inline, 60x20)
function MiniSparkline({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null
  const w = 60, h = 18
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const pts = values.map((v, i) =>
    `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * h}`
  ).join(' L ')

  return (
    <svg width={w} height={h} className="inline-block align-middle" aria-hidden="true">
      <path
        d={`M ${pts}`}
        fill="none"
        stroke={up ? 'rgb(var(--up))' : 'rgb(var(--down))'}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={0.7}
      />
    </svg>
  )
}

export default function PositionCard({ position, isLocked = false, onClose, klineData }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [glitching, setGlitching] = useState(false)
  const prevPnlRef = useRef<number | null>(null)

  const qty   = Number(position.qty || 0)
  const last  = Number(position.lastPrice || position.last_price || 0)
  const avg   = Number(position.avgCost || position.avg_price || 0)
  const unreal = Number.isFinite(avg) ? (last - avg) * qty : null
  const pnlUp  = unreal != null && unreal >= 0
  const score  = position.chip_score ?? position.chip_health_score ?? null

  // Chromatic glitch on P&L change
  useEffect(() => {
    if (unreal !== null && prevPnlRef.current !== null && prevPnlRef.current !== unreal) {
      setGlitching(true)
      const t = setTimeout(() => setGlitching(false), 350)
      return () => clearTimeout(t)
    }
    prevPnlRef.current = unreal
  }, [unreal])

  // Generate sparkline from kline data
  const sparkValues = klineData?.slice(-20).map(k => k.close) ?? []

  // Heavy loss threshold: > 5% loss triggers contamination
  const lossRatio = avg > 0 && last > 0 ? (last - avg) / avg : 0
  const isBleeding = lossRatio < -0.05

  return (
    <div
      onClick={() => setExpanded(e => !e)}
      className={`
        relative overflow-hidden cursor-pointer
        transition-all duration-300
        ${pnlUp
          ? 'border-l-[3px] border-l-[rgb(var(--up))] border border-[rgb(var(--up))/15] bg-[rgb(var(--up))/3]'
          : 'border-l-[3px] border-l-[rgb(var(--down))] border border-[rgb(var(--down))/15] bg-[rgb(var(--down))/3]'
        }
        ${expanded ? 'shadow-xl shadow-black/40' : 'shadow shadow-black/20'}
        hover:border-[rgb(var(--accent))/40]
      `}
      style={{
        // Brutalist: sharp corners. Neon: slight round. Wabi-sabi: organic
        borderRadius: '4px',
      }}
    >
      {/* Contamination rings for bleeding positions */}
      {isBleeding && !expanded && (
        <div className="absolute -right-2 -top-2 pointer-events-none" aria-hidden="true">
          <div className="relative">
            <div className="h-8 w-8 rounded-full border border-rose-500/20 animate-contamination" />
            <div className="absolute inset-0 h-8 w-8 rounded-full border border-rose-500/10 animate-contamination"
                 style={{ animationDelay: '0.7s' }} />
          </div>
        </div>
      )}

      {/* ── Collapsed header ──────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-mono font-bold text-[rgb(var(--text))] text-sm">{position.symbol}</span>
              {isLocked && <Lock className="h-3 w-3 text-amber-400 flex-shrink-0" />}
              {isBleeding && <AlertTriangle className="h-3 w-3 text-rose-400 flex-shrink-0 animate-pulse" />}
            </div>
            {position.name && position.name !== position.symbol && (
              <span className="text-[10px] text-[rgb(var(--muted))] truncate">{position.name}</span>
            )}
          </div>
          <MiniSparkline values={sparkValues} up={pnlUp} />
        </div>

        <div className="flex items-center gap-3">
          <ConfidenceMeter score={score} />
          <div className="text-right">
            <div
              className={`text-sm font-mono font-bold tabular-nums
                ${pnlUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}
                ${glitching ? 'animate-chromatic-glitch' : ''}
              `}
            >
              {unreal != null ? (unreal >= 0 ? '+' : '') + formatCurrency(unreal) : '-'}
            </div>
            <div className="flex items-center gap-0.5 justify-end">
              {pnlUp
                ? <TrendingUp className="h-3 w-3 text-[rgb(var(--up))]" />
                : <TrendingDown className="h-3 w-3 text-[rgb(var(--down))]" />
              }
              {lossRatio !== 0 && (
                <span className={`text-[10px] font-mono ${pnlUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}`}>
                  {(lossRatio * 100).toFixed(1)}%
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Expanded body ────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-[rgb(var(--border))/30] px-4 pb-4 pt-3 animate-card-explode">
          {/* KPI grid */}
          <div className="mb-3 grid grid-cols-3 gap-1.5 text-[11px]">
            {([
              ['均價', avg, true],
              ['現價', last, true],
              ['數量', qty, false],
              ['未實現', unreal, true],
              ['比重', position.weight ?? null, false],
              ['來源', position.price_source === 'eod' ? '收盤' : '即時', false],
            ] as [string, number | null | string, boolean][]).map(([label, val, isCurrency]) => (
              <div key={label} className="bg-[rgb(var(--surface))/0.5] px-2 py-1.5"
                   style={{ borderRadius: '2px' }}>
                <div className="text-[rgb(var(--muted))] text-[9px] uppercase tracking-wider">{label}</div>
                <div className="mt-0.5 font-mono font-semibold text-[rgb(var(--text))]">
                  {val == null
                    ? '-'
                    : isCurrency
                      ? formatCurrency(val as number)
                      : typeof val === 'string'
                        ? val
                        : formatNumber(val as number, { maximumFractionDigits: 4 })
                  }
                </div>
              </div>
            ))}
          </div>

          {/* Mini K-line */}
          {klineData && klineData.length > 0 ? (
            <div className="border border-[rgb(var(--border))/30] bg-[rgb(var(--bg))/0.6] p-1.5 overflow-hidden"
                 style={{ borderRadius: '2px' }}>
              <KLineChart symbol={position.symbol} data={klineData} height={130} />
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-[10px] text-[rgb(var(--muted))] py-2">
              <Zap className="h-3 w-3" />
              K線需從報價服務取得
            </div>
          )}

          {/* Close button */}
          {!isLocked && onClose && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onClose() }}
              className="mt-3 w-full border border-rose-700/50 bg-rose-900/20
                         py-2 text-xs font-mono font-semibold tracking-wider text-rose-300 transition
                         hover:bg-rose-800/40 active:scale-[0.98]"
              style={{ borderRadius: '2px' }}
            >
              CLOSE {position.symbol}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
