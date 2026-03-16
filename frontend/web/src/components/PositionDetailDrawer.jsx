import React, { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Shield, BarChart3, AlertTriangle, Lock } from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'
import { lockSymbol, unlockSymbol } from '../lib/portfolio'
import { formatCurrency, formatNumber } from '../lib/format'
import QuotePanel from './position-detail/QuotePanel'
import KlinePanel from './position-detail/KlinePanel'
import DecisionChainPanel from './position-detail/DecisionChainPanel'
import PositionLocks from './position-detail/PositionLocks'
import DetailSection from './position-detail/DetailSection'

/** Label-value pair */
function DetailField({ label, value, valueClass = 'text-slate-200' }) {
    return (
        <div>
            <div className="text-xs text-slate-500">{label}</div>
            <div className={`mt-0.5 text-sm font-medium ${valueClass}`}>{value}</div>
        </div>
    )
}

/** Chip score progress bar — 0-3 red, 4-6 yellow, 7-10 green */
function ChipScoreBar({ score }) {
    const pct = Math.min(100, Math.max(0, (score / 10) * 100))
    let color = 'bg-rose-500'
    if (score >= 7) color = 'bg-emerald-500'
    else if (score >= 4) color = 'bg-amber-500'

    return (
        <div className="h-1.5 w-12 rounded-full bg-slate-800 overflow-hidden">
            <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
        </div>
    )
}

/**
 * Position Detail Drawer — Design doc §4.1
 */
export default function PositionDetailDrawer({ symbol, position, isLocked, onLockChange, onClose }) {
    const [detail, setDetail] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [lockLoading, setLockLoading] = useState(false)
    const [lockError, setLockError] = useState(null)
    const contentRef = React.useRef(null)

    async function handleToggleLock() {
        setLockLoading(true)
        setLockError(null)
        try {
            if (isLocked) {
                await unlockSymbol(symbol)
                onLockChange?.(symbol, false)
            } else {
                await lockSymbol(symbol)
                onLockChange?.(symbol, true)
            }
        } catch (e) {
            setLockError(e.message)
        } finally {
            setLockLoading(false)
        }
    }

    useEffect(() => {
        if (!symbol) return
        setLoading(true)
        setError(null)
        setDetail(null)
        if (contentRef.current) contentRef.current.scrollTop = 0

        const base = getApiBase()
        authFetch(`${base}/api/portfolio/position-detail/${encodeURIComponent(symbol)}`)
            .then((r) => r.json())
            .then((d) => {
                setDetail(d?.data || d)
                setLoading(false)
            })
            .catch((e) => {
                setError(e.message)
                setLoading(false)
            })
    }, [symbol])

    if (!symbol) return null

    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm transition-opacity"
                onClick={onClose}
                aria-hidden="true"
            />

            {/* Drawer panel */}
            <div
                className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-slate-800 bg-slate-950/95 shadow-2xl backdrop-blur-xl transition-transform duration-300"
                style={{ transform: symbol ? 'translateX(0)' : 'translateX(100%)' }}
            >
                {/* Header */}
                <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <h2 className="text-lg font-bold text-slate-100">{symbol}</h2>
                            {isLocked && (
                                <span className="flex items-center gap-1 rounded-md bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-400 ring-1 ring-amber-500/30">
                                    <Lock className="h-3 w-3" /> 長期持股鎖定
                                </span>
                            )}
                        </div>
                        <p className="text-xs text-slate-400">持倉詳情 · 決策鏈</p>
                    </div>
                    <div className="flex items-center gap-2">
                        <PositionLocks
                            isLocked={isLocked}
                            lockLoading={lockLoading}
                            onToggle={handleToggleLock}
                        />
                        <button
                            onClick={onClose}
                            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
                            aria-label="關閉"
                        >
                            <X className="h-5 w-5" />
                        </button>
                    </div>
                </div>
                {lockError && (
                    <div className="border-b border-rose-500/20 bg-rose-500/10 px-6 py-2 text-xs text-rose-300">
                        {lockError}
                    </div>
                )}

                {/* Content */}
                <div ref={contentRef} className="flex-1 overflow-y-auto p-6 space-y-4">
                    {/* 即時報價（五檔）— 始終顯示 */}
                    <QuotePanel symbol={symbol} />
                    {/* K 線圖 */}
                    <KlinePanel symbol={symbol} />

                    {loading && (
                        <div className="flex items-center justify-center py-20">
                            <svg className="h-6 w-6 animate-spin text-emerald-400" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                        </div>
                    )}

                    {error && (
                        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-300">
                            <AlertTriangle className="mb-1 inline-block h-4 w-4" /> {error}
                        </div>
                    )}

                    {!loading && detail && (
                        <>
                            {/* ── 持倉摘要 ── */}
                            {position && (
                                <DetailSection icon={BarChart3} title="持倉摘要">
                                    <div className="grid grid-cols-2 gap-3">
                                        <DetailField label="數量" value={formatNumber(position.qty || 0)} />
                                        <DetailField label="均價" value={formatCurrency(position.avgCost || position.avg_price || 0)} />
                                        <DetailField label={position.price_source === 'eod' ? '現價（收盤）' : '現價'} value={
                                            (position.lastPrice || position.last_price)
                                                ? formatCurrency(position.lastPrice || position.last_price)
                                                : <span className="text-slate-500">市場休市中</span>
                                        } />
                                        <DetailField
                                            label="未實現損益"
                                            value={
                                                (position.lastPrice || position.last_price)
                                                    ? formatCurrency(
                                                        ((position.lastPrice || position.last_price) - (position.avgCost || position.avg_price || 0)) *
                                                        (position.qty || 0)
                                                    )
                                                    : '-'
                                            }
                                            valueClass={
                                                ((position.lastPrice || position.last_price || 0) - (position.avgCost || position.avg_price || 0)) >= 0
                                                    ? 'text-emerald-400' : 'text-rose-400'
                                            }
                                        />
                                    </div>
                                </DetailSection>
                            )}

                            {/* ── 決策鏈 ── */}
                            <DecisionChainPanel decision={detail.decision} riskCheck={detail.risk_check} fills={detail.fills} />

                            {/* ── 止損 / 止盈 ── */}
                            <DetailSection icon={Shield} title="止損 / 止盈設定">
                                <div className="grid grid-cols-2 gap-3">
                                    <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3">
                                        <div className="flex items-center gap-1.5 text-xs text-rose-400">
                                            <TrendingDown className="h-3.5 w-3.5" /> 止損價
                                        </div>
                                        <div className="mt-1 text-lg font-bold text-rose-300">
                                            {detail.stop_loss ? formatCurrency(detail.stop_loss) : '-'}
                                        </div>
                                    </div>
                                    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
                                        <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                                            <TrendingUp className="h-3.5 w-3.5" /> 止盈價
                                        </div>
                                        <div className="mt-1 text-lg font-bold text-emerald-300">
                                            {detail.take_profit ? formatCurrency(detail.take_profit) : '-'}
                                        </div>
                                    </div>
                                </div>
                            </DetailSection>

                            {/* ── 籌碼趨勢 ── */}
                            {detail.chip_trend && detail.chip_trend.length > 0 && (
                                <DetailSection icon={BarChart3} title="籌碼趨勢歷史">
                                    <div className="space-y-2">
                                        <div className="grid grid-cols-4 gap-2 text-xs text-slate-500 font-medium">
                                            <span>日期</span>
                                            <span>法人買</span>
                                            <span>法人賣</span>
                                            <span>評分</span>
                                        </div>
                                        {detail.chip_trend.map((t, i) => (
                                            <div key={i} className="grid grid-cols-4 gap-2 text-sm">
                                                <span className="text-slate-400">{t.date}</span>
                                                <span className="text-emerald-400">{formatNumber(t.institution_buy)}</span>
                                                <span className="text-rose-400">{formatNumber(t.institution_sell)}</span>
                                                <span className="flex items-center gap-1.5">
                                                    <ChipScoreBar score={t.score} />
                                                    <span className="text-slate-300">{t.score}</span>
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </DetailSection>
                            )}
                        </>
                    )}
                </div>
            </div>
        </>
    )
}
