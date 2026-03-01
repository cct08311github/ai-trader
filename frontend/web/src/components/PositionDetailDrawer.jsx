import React, { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Shield, BarChart3, FileText, AlertTriangle } from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'
import { formatCurrency, formatNumber } from '../lib/format'

/**
 * Position Detail Drawer — Design doc §4.1
 *
 * Slides in from the right to show:
 * - 進場理由（Entry reason from llm_traces PM decision）
 * - 止損/止盈設定（Stop-loss / take-profit settings）
 * - PM 授權原文（PM authorization text）
 * - 籌碼趨勢歷史（Chip trend history chart）
 */
export default function PositionDetailDrawer({ symbol, position, onClose }) {
    const [detail, setDetail] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)

    useEffect(() => {
        if (!symbol) return
        setLoading(true)
        setError(null)

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
                className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-slate-800 bg-slate-950/95 shadow-2xl backdrop-blur-xl transition-transform duration-300"
                style={{ transform: symbol ? 'translateX(0)' : 'translateX(100%)' }}
            >
                {/* Header */}
                <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
                    <div>
                        <h2 className="text-lg font-bold text-slate-100">{symbol}</h2>
                        <p className="text-xs text-slate-400">持倉詳情</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
                        aria-label="關閉"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-5">
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
                            {/* Current position summary */}
                            {position && (
                                <DetailSection icon={BarChart3} title="持倉摘要">
                                    <div className="grid grid-cols-2 gap-3">
                                        <DetailField label="數量" value={formatNumber(position.qty || 0)} />
                                        <DetailField label="均價" value={formatCurrency(position.avgCost || position.avg_price || 0)} />
                                        <DetailField label="現價" value={formatCurrency(position.lastPrice || position.last_price || 0)} />
                                        <DetailField
                                            label="未實現損益"
                                            value={formatCurrency(
                                                ((position.lastPrice || position.last_price || 0) - (position.avgCost || position.avg_price || 0)) *
                                                (position.qty || 0)
                                            )}
                                            valueClass={
                                                ((position.lastPrice || position.last_price || 0) - (position.avgCost || position.avg_price || 0)) >= 0
                                                    ? 'text-emerald-400' : 'text-rose-400'
                                            }
                                        />
                                    </div>
                                </DetailSection>
                            )}

                            {/* Entry reason */}
                            <DetailSection icon={FileText} title="進場理由">
                                <p className="text-sm leading-relaxed text-slate-300">
                                    {detail.entry_reason || '暫無進場理由資料'}
                                </p>
                            </DetailSection>

                            {/* Stop-loss / Take-profit */}
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

                            {/* PM authorization */}
                            <DetailSection icon={FileText} title="PM 授權原文">
                                <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-xs font-mono text-slate-400 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
                                    {detail.pm_authorization || '暫無 PM 授權資料'}
                                </div>
                            </DetailSection>

                            {/* Chip trend history */}
                            <DetailSection icon={BarChart3} title="籌碼趨勢歷史">
                                {detail.chip_trend && detail.chip_trend.length > 0 ? (
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
                                ) : (
                                    <p className="text-sm text-slate-500">暫無籌碼趨勢資料</p>
                                )}
                            </DetailSection>
                        </>
                    )}
                </div>
            </div>
        </>
    )
}

/** Section wrapper */
function DetailSection({ icon: Icon, title, children }) {
    return (
        <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-200">
                <Icon className="h-4 w-4 text-emerald-400" />
                {title}
            </div>
            {children}
        </div>
    )
}

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
