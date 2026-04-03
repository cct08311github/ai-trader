/**
 * PortfolioPage.tsx -- Kyo Nakamura
 *
 * The War Room. The command center. The cockpit.
 *
 * Layout (asymmetric, never 50/50):
 *   Left column (4/12):  Position intelligence cards, stacked
 *   Right column (8/12): K-Line hero chart + P&L ECG + allocation
 *   Top bar:             PM status + SSE badge + Emergency Stop + Refresh
 *   Bottom (mobile):     MobileNav bottom bar
 *
 * All data flows preserved from original Portfolio.jsx.
 * Emergency stop triggers nuclear detonation sequence.
 */

import React, { useCallback, useEffect, useReducer, useState, useRef } from 'react'
import { Lock, RefreshCw, Shield, Zap, Radio, AlertTriangle } from 'lucide-react'

import { useToast } from '../components/ToastProvider'
import PmStatusCard from '../components/PmStatusCard'
import KpiCard from '../components/KpiCard'
import AllocationDonut from '../components/charts/AllocationDonut'
import PnlLineChart from '../components/charts/PnlLineChart'
import EmptyState from '../components/EmptyState'
import LoadingSpinner from '../components/LoadingSpinner'
import ErrorState from '../components/ErrorState'
import ChatButton from '../components/chat/ChatButton'

import KLineChart from '../components/KLineChart'
import PnLError from '../components/PnLError'
import PositionCard from '../components/PositionCard'
import EmergencyStopButton from '../components/EmergencyStopButton'
import MobileNav from '../components/MobileNav'

import {
  mockPositions,
  fetchPortfolioPositions,
  fetchEquityCurve,
  buildAllocationData,
  calcPortfolioKpis,
  fetchPortfolioKpis,
  fetchLockedSymbols,
  lockSymbol,
  unlockSymbol,
  closePosition,
} from '../lib/portfolio'
import { formatCurrency, formatNumber, formatPercent } from '../lib/format'

// ── Animated number with chromatic glitch ────────────────────────────────────
function AnimatedNumber({ value, format = (v: number) => String(v), className = '' }: {
  value: number
  format?: (v: number) => string
  className?: string
}) {
  const [tick, setTick] = useState(false)
  const prevRef = useRef(value)

  useEffect(() => {
    if (prevRef.current !== value) {
      setTick(true)
      prevRef.current = value
      const t = setTimeout(() => setTick(false), 400)
      return () => clearTimeout(t)
    }
  }, [value])

  return (
    <span className={`tabular-nums ${tick ? 'animate-digit-tick' : ''} ${className}`}>
      {format(value)}
    </span>
  )
}

// ── Panel wrapper (brutalist edges) ──────────────────────────────────────────
function Panel({ title, right, children, className = '' }: {
  title: string
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section
      className={`border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.2] shadow-panel ${className}`}
      style={{ borderRadius: '4px' }}
    >
      <div className="flex items-center justify-between border-b border-[rgb(var(--border))] px-4 py-2.5">
        <div className="text-xs font-mono font-semibold uppercase tracking-wider">{title}</div>
        {right ? <div className="text-[10px] font-mono text-[rgb(var(--muted))]">{right}</div> : null}
      </div>
      <div className="p-3">{children}</div>
    </section>
  )
}

// ── Status indicator dot ─────────────────────────────────────────────────────
function StatusDot({ active, label }: { active: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`h-2 w-2 rounded-full ${active ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--muted))]'}`}
        style={{
          boxShadow: active ? '0 0 6px rgb(var(--up))' : 'none',
        }}
      />
      <span className={`text-[10px] font-mono uppercase tracking-wider
                        ${active ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--muted))]'}`}>
        {label}
      </span>
    </span>
  )
}

// ── Types ───────────────────────────────────────────────────────────────────
interface Position {
  symbol: string
  name?: string
  qty: number
  lastPrice: number
  avgCost: number
  chip_score?: number
  sector?: string
  last_price?: number
}

interface BackendKpis {
  available_cash: number
  today_trades_count: number
  overall_win_rate: number
}

interface FetchState {
  positions: Position[]
  source: 'api' | 'mock' | 'error'
  error: string | null
  loading: boolean
  backendKpis: BackendKpis
}

type FetchAction =
  | { type: 'FETCH_START' }
  | { type: 'FETCH_SUCCESS'; positions: Position[]; backendKpis: BackendKpis }
  | { type: 'FETCH_ERROR'; error: string }
  | { type: 'SET_MOCK'; positions: Position[] }

function fetchReducer(state: FetchState, action: FetchAction): FetchState {
  switch (action.type) {
    case 'FETCH_START':
      return { ...state, loading: true, error: null }
    case 'FETCH_SUCCESS':
      return { ...state, loading: false, error: null, positions: action.positions, backendKpis: action.backendKpis, source: 'api' }
    case 'FETCH_ERROR':
      return { ...state, loading: false, positions: [], source: 'error', error: action.error }
    case 'SET_MOCK':
      return { ...state, loading: false, error: null, positions: action.positions, source: 'mock' }
    default:
      return state
  }
}

const initialFetchState: FetchState = {
  positions: [],
  source: 'api',
  error: null,
  loading: false,
  backendKpis: { available_cash: 0, today_trades_count: 0, overall_win_rate: 0 },
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function PortfolioPage() {
  const [fetchState, dispatch] = useReducer(fetchReducer, initialFetchState)
  const { positions, source, error, loading, backendKpis } = fetchState

  const [preferApi] = useState(true)
  const toast = useToast()
  const [lockedSymbols, setLockedSymbols] = useState(new Set())
  const [equitySeries, setEquitySeries] = useState<{ date: string; equity: number }[]>([])
  const [equitySource, setEquitySource] = useState('讀取中...')
  const [closeTarget, setCloseTarget] = useState<Position | null>(null)
  const [closeBusy, setCloseBusy] = useState(false)
  const [sseActive, setSseActive] = useState(false)

  async function load(nextPreferApi = preferApi) {
    if (!nextPreferApi) {
      dispatch({ type: 'SET_MOCK', positions: mockPositions })
      return
    }
    dispatch({ type: 'FETCH_START' })
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 10000)
    try {
      const [data, kpisData] = await Promise.all([
        fetchPortfolioPositions({ signal: controller.signal }),
        fetchPortfolioKpis({ signal: controller.signal }),
      ])
      dispatch({ type: 'FETCH_SUCCESS', positions: data, backendKpis: kpisData })
    } catch (e: any) {
      dispatch({ type: 'FETCH_ERROR', error: String(e?.message || e) })
    } finally {
      clearTimeout(timeout)
    }
  }

  useEffect(() => {
    load(true)
    fetchEquityCurve({ days: 60, startEquity: 100000 }).then((data: { date: string; equity: number }[]) => {
      if (data.length > 0) {
        setEquitySeries(data)
        setEquitySource('DB')
      } else {
        setEquitySource('mock (no trades)')
      }
    })
    fetchLockedSymbols().then(setLockedSymbols)
  }, [])

  async function handleCloseConfirm() {
    if (!closeTarget) return
    setCloseBusy(true)
    try {
      const res = await closePosition(closeTarget.symbol)
      toast.success(`已平倉 ${res.qty_closed} 股 @ ${formatCurrency(res.sell_price)}`)
      setCloseTarget(null)
      await load(preferApi)
    } catch (e: any) {
      toast.error(String(e?.message || e))
      setCloseTarget(null)
    } finally {
      setCloseBusy(false)
    }
  }

  const kpis = React.useMemo(
    () => calcPortfolioKpis(positions, { equitySeries }),
    [positions, equitySeries]
  )
  const dailyTone = kpis.dailyPnl >= 0 ? 'good' : 'bad'
  const cumulativeTone = kpis.cumulativePnl >= 0 ? 'good' : 'bad'

  async function handleEmergencyStop() {
    toast.warning('緊急止損觸發中...')
    const targets = positions.filter((p: Position) => !lockedSymbols.has(p.symbol))
    const results = await Promise.allSettled(
      targets.map((p: Position) => closePosition(p.symbol))
    )
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length === 0) {
      toast.success(`緊急止損完成 — ${targets.length} 個倉位已關閉`)
    } else {
      toast.error(`⚠️ ${failed.length}/${targets.length} 個倉位關閉失敗，請手動確認！`)
    }
    await load(preferApi)
  }

  // K-line mock data
  const klineSymbol = positions[0]?.symbol ?? '2330'
  const klineData = React.useMemo(() => {
    if (!positions.length) return []
    const ref = positions[0]
    const base = Number(ref.lastPrice || ref.last_price || 100)
    return Array.from({ length: 60 }, (_, i) => {
      const rand = (Math.random() - 0.48) * base * 0.02
      const close = base + rand * (i + 1) / 2
      const open = close + (Math.random() - 0.5) * base * 0.01
      const high = Math.max(open, close) + Math.random() * base * 0.01
      const low  = Math.min(open, close) - Math.random() * base * 0.01
      const d = new Date(); d.setDate(d.getDate() - (59 - i))
      return {
        date: `${d.getMonth() + 1}/${d.getDate()}`,
        open: +open.toFixed(2),
        high: +high.toFixed(2),
        low:  +low.toFixed(2),
        close: +close.toFixed(2),
        volume: Math.floor(Math.random() * 5000 + 1000),
      }
    })
  }, [positions.length])

  return (
    <div className="space-y-4 pb-20 lg:pb-4">

      {/* ══════════════════════════════════════════════════════════
          TOP COMMAND BAR -- PM status, SSE, Emergency, Refresh
          ══════════════════════════════════════════════════════════ */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Left: status indicators */}
        <div className="flex items-center gap-4 flex-wrap">
          <PmStatusCard />

          {/* SSE toggle */}
          <button
            type="button"
            onClick={() => setSseActive(a => !a)}
            className={`flex items-center gap-1.5 border px-2.5 py-1.5 text-[10px] font-mono font-bold
                       uppercase tracking-widest transition-all
                       ${sseActive
                         ? 'border-[rgb(var(--up))/40] bg-[rgb(var(--up))/8] text-[rgb(var(--up))]'
                         : 'border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.3] text-[rgb(var(--muted))]'
                       }`}
            style={{
              borderRadius: '3px',
              boxShadow: sseActive ? '0 0 8px rgba(var(--up), 0.2)' : 'none',
            }}
            title={sseActive ? 'SSE 即時串流已連接' : '點擊啟用 SSE 即時報價'}
          >
            <Radio className="h-3 w-3" />
            {sseActive ? 'MOCK (模擬)' : 'SSE OFF'}
          </button>

          {/* Data source badge */}
          <StatusDot
            active={source === 'api'}
            label={source === 'api' ? 'API' : source.toUpperCase()}
          />
          {error && (
            <span className="text-[10px] text-rose-400 font-mono">
              ERR: {error.slice(0, 40)}
            </span>
          )}
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-2">
          <EmergencyStopButton
            onTrigger={handleEmergencyStop}
            disabled={loading || positions.length === 0}
          />
          <button
            type="button"
            onClick={() => load(preferApi)}
            disabled={loading}
            className="flex items-center gap-1.5 border border-[rgb(var(--border))]
                       bg-[rgb(var(--surface))/0.3] px-4 py-2.5 text-xs font-mono
                       text-[rgb(var(--text))] transition
                       hover:bg-[rgb(var(--surface))/0.5] disabled:opacity-50"
            style={{ borderRadius: '3px' }}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            {loading ? '...' : 'REFRESH'}
          </button>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          KPI STRIP -- 6 cards, asymmetric widths
          ══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <KpiCard
          title="總資產"
          value={<AnimatedNumber value={kpis.total} format={v => formatCurrency(v)} className="font-mono" />}
          subtext="TOTAL EQUITY"
        />
        <KpiCard
          title="可用現金"
          value={<AnimatedNumber value={backendKpis.available_cash} format={v => formatCurrency(v)} className="font-mono" />}
          subtext="CASH"
          tone="neutral"
        />
        <KpiCard
          title="日損益"
          value={<AnimatedNumber value={kpis.dailyPnl} format={v => formatCurrency(v)} className="font-mono" />}
          subtext="DAILY P&L"
          tone={dailyTone}
        />
        <KpiCard
          title="累計損益"
          value={<AnimatedNumber value={kpis.cumulativePnl} format={v => formatCurrency(v)} className="font-mono" />}
          subtext="CUMULATIVE"
          tone={cumulativeTone}
        />
        <KpiCard
          title="今日成交"
          value={<AnimatedNumber value={backendKpis.today_trades_count} format={v => formatNumber(v)} className="font-mono" />}
          subtext="TRADES"
          tone="neutral"
        />
        <KpiCard
          title="勝率"
          value={
            <AnimatedNumber
              value={backendKpis.overall_win_rate * 100}
              format={v => `${formatNumber(v, { maximumFractionDigits: 1 })}%`}
              className="font-mono"
            />
          }
          subtext="WIN RATE"
          tone={backendKpis.overall_win_rate >= 0.5 ? 'good' : 'bad'}
        />
      </div>

      {/* ══════════════════════════════════════════════════════════
          BATTLE LAYOUT -- asymmetric 4:8 split
          Left: position cards (intelligence briefings)
          Right: K-line hero + P&L ECG + allocation
          ══════════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">

        {/* ── LEFT COLUMN: Position Intelligence ──────────────── */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-[9px] uppercase tracking-[0.2em] font-mono text-[rgb(var(--muted))]">
              POSITION INTEL
            </span>
            <span className="text-[10px] font-mono text-[rgb(var(--muted))]">
              {loading ? '...' : `${positions.length} POS`}
            </span>
          </div>

          {loading ? (
            <div className="flex items-center justify-center border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.15] py-16"
                 style={{ borderRadius: '4px' }}>
              <LoadingSpinner label="讀取持倉資料中..." />
            </div>
          ) : error ? (
            <div className="border border-rose-800/40 bg-rose-900/10 p-4" style={{ borderRadius: '4px' }}>
              <ErrorState message="讀取持倉失敗" onRetry={() => load(preferApi)} />
            </div>
          ) : positions.length === 0 ? (
            <div className="border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.1] p-8"
                 style={{ borderRadius: '4px' }}>
              <EmptyState
                icon={Shield}
                title="NO POSITIONS"
                description="系統將在下次交易時段自動建倉"
              />
            </div>
          ) : (
            <div className="space-y-2">
              {positions.map((p: Position) => (
                <PositionCard
                  key={p.symbol}
                  position={p}
                  isLocked={lockedSymbols.has(p.symbol)}
                  onClose={() => setCloseTarget(p)}
                />
              ))}
            </div>
          )}

          {/* Sharpe ratio card */}
          {kpis.sharpe != null && (
            <div className="border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.15] px-4 py-3"
                 style={{ borderRadius: '4px' }}>
              <div className="text-[9px] uppercase tracking-[0.2em] font-mono text-[rgb(var(--muted))]">
                SHARPE RATIO
              </div>
              <div className={`mt-1 text-2xl font-mono font-bold tabular-nums
                              ${kpis.sharpe >= 1 ? 'text-[rgb(var(--up))]' : 'text-[rgb(var(--text))]'}`}
                   style={{
                     filter: kpis.sharpe >= 2 ? 'drop-shadow(0 0 6px rgb(var(--up)))' : 'none',
                   }}>
                {kpis.sharpe.toFixed(2)}
              </div>
              <div className="text-[10px] text-[rgb(var(--muted))] font-mono mt-0.5">
                annualized ({equitySource})
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT COLUMN: Charts & Data ─────────────────────── */}
        <div className="lg:col-span-8 space-y-4">

          {/* K-Line hero chart -- full width, no card padding constraints */}
          <Panel
            title={`${klineSymbol} KLINE`}
            right={klineData.length > 0 ? `${klineData.length} BARS` : 'LOADING...'}
          >
            <KLineChart
              symbol={klineSymbol}
              data={klineData}
              height={320}
              animate={sseActive}
            />
          </Panel>

          {/* P&L ECG */}
          <Panel
            title="P&L ECG"
            right={equitySource}
          >
            <PnLError
              data={equitySeries}
              dailyPnl={kpis.dailyPnl}
              height={220}
              animate={sseActive}
            />
          </Panel>

          {/* Allocation + legacy trend (2 columns on xl) */}
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Panel title="SECTOR CONCENTRATION">
              {positions.length > 0 ? (
                <AllocationDonut data={buildAllocationData(positions)} warnThreshold={40} />
              ) : (
                <EmptyState icon={Shield} title="NO DATA" description="無持倉資料" />
              )}
            </Panel>

            <Panel title="EQUITY TREND" right={equitySource}>
              <PnlLineChart data={equitySeries} />
            </Panel>
          </div>
        </div>
      </div>

      {/* ── Accessibility ────────────────────────────────────────── */}
      <div className="sr-only" aria-live="polite">
        {loading ? 'Loading portfolio data' : `Portfolio data loaded from ${source}`}
      </div>

      {/* ── Floating chat ────────────────────────────────────────── */}
      <ChatButton />

      {/* ── Mobile bottom nav ────────────────────────────────────── */}
      <MobileNav />

      {/* ── Close Position Modal ─────────────────────────────────── */}
      {closeTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
          onMouseDown={() => setCloseTarget(null)}
        >
          <div
            className="w-full max-w-sm border-2 border-rose-700/60 bg-[rgb(var(--bg))] p-6 shadow-2xl"
            onMouseDown={(e: React.MouseEvent) => e.stopPropagation()}
            style={{
              borderRadius: '4px',
              boxShadow: '0 0 40px rgba(185,28,28,0.2)',
            }}
          >
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center border border-rose-700/50 bg-rose-900/20"
                   style={{ borderRadius: '2px' }}>
                <AlertTriangle className="h-5 w-5 text-rose-400" />
              </div>
              <div>
                <div className="text-sm font-mono font-bold text-[rgb(var(--text))]">CONFIRM CLOSE</div>
                <div className="text-[10px] text-[rgb(var(--muted))] font-mono">
                  此操作將立即反向賣出全部持倉
                </div>
              </div>
            </div>

            <div className="mb-5 space-y-2 border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.3] p-4 text-xs font-mono"
                 style={{ borderRadius: '2px' }}>
              <div className="flex justify-between">
                <span className="text-[rgb(var(--muted))]">SYMBOL</span>
                <span className="font-bold text-[rgb(var(--text))]">{closeTarget.symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[rgb(var(--muted))]">QTY</span>
                <span className="text-[rgb(var(--text))]">{formatNumber(Number(closeTarget.qty || 0))} shares</span>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setCloseTarget(null)}
                disabled={closeBusy}
                className="flex-1 border border-[rgb(var(--border))] py-2.5 text-xs font-mono font-medium
                           text-[rgb(var(--muted))] hover:bg-[rgb(var(--surface))/0.4] disabled:opacity-50 transition-colors"
                style={{ borderRadius: '3px' }}
              >
                CANCEL
              </button>
              <button
                onClick={handleCloseConfirm}
                disabled={closeBusy}
                className="flex-1 border-2 border-rose-600 bg-rose-900/40 py-2.5 text-xs font-mono font-bold
                           text-rose-200 hover:bg-rose-800/60 disabled:opacity-50 transition-colors"
                style={{ borderRadius: '3px' }}
              >
                {closeBusy ? 'EXECUTING...' : 'CONFIRM CLOSE'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
