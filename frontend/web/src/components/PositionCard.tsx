/**
 * PositionCard.tsx — Kyo Nakamura
 * Explosion-expandable position intelligence card.
 * On hover: expands to show mini K-line + PM confidence thermometer.
 *
 * Props:
 *   position  — { symbol, name, qty, avgCost, lastPrice, unrealPnl, chip_score, ... }
 *   onClose   — callback to trigger position close
 *   onExpand  — callback when card expands (to close others)
 */

import { useState } from 'react'
import { Lock, TrendingUp, TrendingDown, Zap } from 'lucide-react'
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
  weight?: number    // portfolio weight 0-1
  price_source?: string
}

interface Props {
  position: Position
  isLocked?: boolean
  onClose?: () => void
  // Optional mini K-line data
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
    rose:    { bar: 'bg-rose-500',   text: 'text-rose-400',    glow: 'shadow-rose-500/30' },
  }[color]

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-[rgb(var(--muted))]">PM</span>
      <div className="relative h-1.5 w-20 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`absolute inset-y-0 left-0 rounded-full ${cls.bar} shadow ${cls.glow} transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-xs font-mono font-bold ${cls.text}`}>{score}</span>
    </div>
  )
}

export default function PositionCard({ position, isLocked = false, onClose, klineData }: Props) {
  const [expanded, setExpanded] = useState(false)

  const qty   = Number(position.qty || 0)
  const last  = Number(position.lastPrice || position.last_price || 0)
  const avg   = Number(position.avgCost || position.avg_price || 0)
  const unreal = Number.isFinite(avg) ? (last - avg) * qty : null
  const pnlUp  = unreal != null && unreal >= 0

  const score  = position.chip_score ?? position.chip_health_score ?? null

  function toggle() { setExpanded(e => !e) }

  return (
    <div
      onMouseEnter={toggle}
      onMouseLeave={toggle}
      className={`
        relative rounded-2xl border transition-all duration-300 cursor-pointer
        ${pnlUp
          ? 'border-[rgb(var(--up))/30] bg-[rgb(var(--up))/5] hover:bg-[rgb(var(--up))/10]'
          : 'border-[rgb(var(--down))/30] bg-[rgb(var(--down))/5] hover:bg-[rgb(var(--down))/10]'
        }
        ${expanded ? 'shadow-2xl shadow-black/60' : 'shadow shadow-black/30'}
        hover:border-[rgb(var(--accent))/50]
      `}
    >
      {/* ── Collapsed header ──────────────────────────────────── */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-[rgb(var(--text))]">{position.symbol}</span>
          {position.name && position.name !== position.symbol && (
            <span className="text-xs text-[rgb(var(--muted))]">{position.name}</span>
          )}
          {isLocked && <Lock className="h-3.5 w-3.5 text-amber-400" />}
        </div>
        <div className="flex items-center gap-3">
          <ConfidenceMeter score={score} />
          <div className={`text-sm font-mono font-bold ${pnlUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}`}>
            {unreal != null ? formatCurrency(unreal) : '-'}
          </div>
          <div className={`flex items-center gap-0.5 ${pnlUp ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--down))]'}`}>
            {pnlUp
              ? <TrendingUp className="h-3.5 w-3.5" />
              : <TrendingDown className="h-3.5 w-3.5" />
            }
          </div>
        </div>
      </div>

      {/* ── Expanded body ────────────────────────────────────── */}
      {expanded && (
        <div className="border-t border-[rgb(var(--border))/40] px-4 pb-4 pt-3 animate-card-explode">
          {/* KPI row */}
          <div className="mb-3 grid grid-cols-3 gap-2 text-[11px]">
            {([
              ['均價', avg, true],
              ['現價', last, true],
              ['數量', qty, false],
              ['未實現', unreal, true],
              ['比重', position.weight ?? null, false],
              ['來源', position.price_source === 'eod' ? '收盤' : '即時', false],
            ] as [string, number | null | string, boolean][]).map(([label, val, isCurrency]) => (
              <div key={label} className="rounded-lg bg-[rgb(var(--surface))/0.5] px-2 py-1.5">
                <div className="text-[rgb(var(--muted))]">{label}</div>
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
            <div className="rounded-xl border border-[rgb(var(--border))/40] bg-[rgb(var(--bg))/0.6] p-2 overflow-hidden">
              <KLineChart
                symbol={position.symbol}
                data={klineData}
                height={140}
              />
            </div>
          ) : (
            <div className="mb-2 flex items-center gap-1.5 text-[10px] text-[rgb(var(--muted))]">
              <Zap className="h-3 w-3" />
              K線需從報價服務取得
            </div>
          )}

          {/* Close button */}
          {!isLocked && onClose && (
            <button
              type="button"
              onClick={e => { e.stopPropagation(); onClose() }}
              className="mt-2 w-full rounded-xl border border-rose-700/50 bg-rose-900/20
                         py-2 text-xs font-semibold text-rose-300 transition
                         hover:bg-rose-800/40 active:scale-[0.98]"
            >
              平倉 · {position.symbol}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
