import React, { useEffect, useState } from 'react'
import { X, TrendingUp, TrendingDown, Shield, BarChart3, FileText, AlertTriangle, Lock, Unlock, GitBranch, CheckCircle2, XCircle, RefreshCw } from 'lucide-react'
import { authFetch, getApiBase, getToken } from '../lib/auth'
import { lockSymbol, unlockSymbol } from '../lib/portfolio'
import { formatCurrency, formatNumber } from '../lib/format'

/* ── K線圖（純 SVG） ────────────────────────────────────── */
const VB_W = 400, VB_H = 200
const PAD = { top: 8, right: 6, bottom: 22, left: 44 }
const PRICE_H = 126, VOL_H = 28, VOL_Y = PAD.top + PRICE_H + 10

function KlineChart({ symbol }) {
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!symbol) return
        setLoading(true)
        authFetch(`${getApiBase()}/api/portfolio/kline/${encodeURIComponent(symbol)}?days=60`)
            .then(r => r.json())
            .then(d => { setData(d.data || []); setLoading(false) })
            .catch(() => { setData([]); setLoading(false) })
    }, [symbol])

    if (loading) return (
        <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4 flex items-center justify-center" style={{ height: 120 }}>
            <RefreshCw className="h-4 w-4 animate-spin text-slate-500" />
        </div>
    )
    if (!data || data.length === 0) return (
        <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4 flex items-center justify-center" style={{ height: 80 }}>
            <span className="text-xs text-slate-500">無 K 線歷史資料</span>
        </div>
    )

    const chartW = VB_W - PAD.left - PAD.right
    const n = data.length
    const xStep = chartW / n
    const cw = Math.max(2, Math.min(10, Math.floor(xStep * 0.65)))
    const cx = i => PAD.left + (i + 0.5) * xStep

    const minP = Math.min(...data.map(d => d.low))
    const maxP = Math.max(...data.map(d => d.high))
    const pPad = (maxP - minP) * 0.04
    const pMin = minP - pPad, pMax = maxP + pPad
    const py = price => PAD.top + PRICE_H - ((price - pMin) / (pMax - pMin)) * PRICE_H

    const maxVol = Math.max(...data.map(d => d.volume || 0))

    const pTicks = [0, 1, 2, 3].map(i => pMin + (pMax - pMin) * (i / 3))
    const labelStep = Math.max(1, Math.floor(n / 5))
    const dLabels = data.map((d, i) => ({ i, date: d.trade_date })).filter(({ i }) => i % labelStep === 0 || i === n - 1)

    return (
        <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-3">
            <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-semibold text-slate-200">K 線圖（日線）</span>
                {data.length > 0 && (
                    <span className="text-[11px] text-slate-500">
                        {data[0].trade_date} ~ {data[data.length - 1].trade_date}
                    </span>
                )}
            </div>
            <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full" style={{ height: 170 }}>
                {/* Grid */}
                {pTicks.map((tick, i) => (
                    <line key={i} x1={PAD.left} y1={py(tick)} x2={PAD.left + chartW} y2={py(tick)}
                        stroke="rgba(148,163,184,0.08)" strokeWidth="1" />
                ))}
                {/* Price labels */}
                {pTicks.map((tick, i) => (
                    <text key={i} x={PAD.left - 3} y={py(tick) + 3.5}
                        textAnchor="end" fill="rgba(148,163,184,0.55)" fontSize="9">
                        {tick.toFixed(1)}
                    </text>
                ))}
                {/* Vol separator */}
                <line x1={PAD.left} y1={VOL_Y - 4} x2={PAD.left + chartW} y2={VOL_Y - 4}
                    stroke="rgba(148,163,184,0.06)" strokeWidth="1" />
                {/* Candles + Volume */}
                {data.map((d, i) => {
                    const isUp = d.close >= d.open
                    const color = isUp ? '#10b981' : '#f43f5e'
                    const x = cx(i)
                    const bodyTop = Math.min(py(d.open), py(d.close))
                    const bodyH = Math.max(1, Math.abs(py(d.close) - py(d.open)))
                    const volBarH = maxVol > 0 ? ((d.volume || 0) / maxVol) * VOL_H : 0
                    return (
                        <g key={i}>
                            <line x1={x} y1={py(d.high)} x2={x} y2={py(d.low)} stroke={color} strokeWidth="0.8" />
                            <rect x={x - cw / 2} y={bodyTop} width={cw} height={bodyH} fill={color} />
                            <rect x={x - cw / 2} y={VOL_Y + VOL_H - volBarH}
                                width={cw} height={Math.max(1, volBarH)}
                                fill={isUp ? 'rgba(16,185,129,0.35)' : 'rgba(244,63,94,0.35)'} />
                        </g>
                    )
                })}
                {/* Date labels */}
                {dLabels.map(({ i, date }) => (
                    <text key={i} x={cx(i)} y={VB_H - 4}
                        textAnchor="middle" fill="rgba(148,163,184,0.55)" fontSize="9">
                        {date ? date.slice(5) : ''}
                    </text>
                ))}
            </svg>
        </div>
    )
}

/** 五檔即時報價面板 */
function QuotePanel({ symbol }) {
    const [snap, setSnap] = useState(null)
    const [source, setSource] = useState(null)
    const [bidask, setBidask] = useState(null)
    const [live, setLive] = useState(false)

    // 初始 snapshot（含 EOD fallback）
    useEffect(() => {
        if (!symbol) return
        const base = getApiBase()
        authFetch(`${base}/api/portfolio/quote/${encodeURIComponent(symbol)}`)
            .then(r => r.json())
            .then(d => { if (d?.data) { setSnap(d.data); setSource(d.source) } })
            .catch(() => {})
    }, [symbol])

    // BidAsk SSE 即時訂閱
    useEffect(() => {
        if (!symbol) return
        const base = getApiBase()
        const token = getToken()
        const url = `${base}/api/portfolio/quote-stream/${encodeURIComponent(symbol)}${token ? `?token=${token}` : ''}`
        const es = new EventSource(url)
        es.onopen = () => setLive(true)
        es.onmessage = e => {
            try {
                const d = JSON.parse(e.data)
                if (d.type === 'bidask') setBidask(d)
            } catch {}
        }
        es.onerror = () => setLive(false)
        return () => { es.close(); setLive(false) }
    }, [symbol])

    const bids = (bidask?.bid_price || []).map((p, i) => ({ price: p, vol: bidask.bid_volume?.[i] ?? 0 }))
    const asks = (bidask?.ask_price || []).map((p, i) => ({ price: p, vol: bidask.ask_volume?.[i] ?? 0 }))
    const hasFive = bids.length > 0 || asks.length > 0

    return (
        <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4">
            {/* 標題列 */}
            <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-slate-200">即時報價</span>
                {source === 'eod'
                    ? <span className="flex items-center gap-1 text-[11px] text-slate-400">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-500" />
                        最後收盤資料（{snap?.trade_date || ''}）
                    </span>
                    : <span className={`flex items-center gap-1 text-[11px] ${live ? 'text-emerald-400' : 'text-slate-500'}`}>
                        <span className={`inline-block h-1.5 w-1.5 rounded-full ${live ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                        {live ? '即時連線' : '等待開盤'}
                    </span>
                }
            </div>

            {/* KPI 四格 */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-3 text-xs">
                <div>
                    <div className="text-slate-500 mb-0.5">最新成交</div>
                    <div className="text-xl font-bold text-slate-100">
                        {snap?.close ? `$${snap.close}` : '—'}
                    </div>
                </div>
                <div>
                    <div className="text-slate-500 mb-0.5">漲跌幅</div>
                    <div className={`text-base font-semibold ${
                        snap?.change_rate == null ? 'text-slate-400'
                        : snap.change_rate >= 0 ? 'text-emerald-400' : 'text-rose-400'
                    }`}>
                        {snap?.change_rate != null
                            ? `${snap.change_rate >= 0 ? '+' : ''}${snap.change_rate.toFixed(2)}%`
                            : '—'}
                    </div>
                </div>
                <div>
                    <div className="text-slate-500 mb-0.5">總成交量</div>
                    <div className="text-slate-200 font-medium">
                        {snap?.volume != null ? `${snap.volume.toLocaleString()} 張` : '—'}
                    </div>
                </div>
                <div>
                    <div className="text-slate-500 mb-0.5">成交金額</div>
                    <div className="text-slate-200 font-medium">
                        {snap?.total_amount ? `$${(snap.total_amount / 1000).toFixed(0)}K` : '—'}
                    </div>
                </div>
            </div>

            {/* 五檔 bid/ask */}
            {hasFive ? (
                <div>
                    <div className="grid grid-cols-4 text-[11px] text-slate-500 px-1 mb-1">
                        <div className="text-right">買量(張)</div>
                        <div className="text-right pr-3">買價</div>
                        <div className="pl-3">賣價</div>
                        <div>賣量(張)</div>
                    </div>
                    {Array.from({ length: 5 }, (_, i) => (
                        <div key={i} className="grid grid-cols-4 text-xs py-0.5 rounded odd:bg-slate-900/30">
                            <div className="text-right text-emerald-400/70 pr-1">{bids[i]?.vol ?? '—'}</div>
                            <div className="text-right text-emerald-300 font-mono font-medium pr-3">{bids[i]?.price ?? '—'}</div>
                            <div className="text-rose-300 font-mono font-medium pl-3">{asks[i]?.price ?? '—'}</div>
                            <div className="text-rose-400/70 pl-1">{asks[i]?.vol ?? '—'}</div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-center text-[11px] text-slate-600 py-1">
                    {live ? '等待五檔推送…' : '開盤後顯示五檔行情'}
                </div>
            )}
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
                        <button
                            onClick={handleToggleLock}
                            disabled={lockLoading}
                            title={isLocked ? '解除鎖定（允許賣出）' : '鎖定（禁止 AI 賣出）'}
                            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                                isLocked
                                    ? 'bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 ring-1 ring-amber-500/30'
                                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200'
                            }`}
                        >
                            {isLocked ? <Unlock className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />}
                            {lockLoading ? '處理中…' : isLocked ? '解除鎖定' : '鎖定持股'}
                        </button>
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
                <div className="flex-1 overflow-y-auto p-6 space-y-4">
                    {/* 即時報價（五檔）— 始終顯示 */}
                    <QuotePanel symbol={symbol} />
                    {/* K 線圖 */}
                    <KlineChart symbol={symbol} />

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
                                        <DetailField label="現價" value={
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
                            <DecisionChainSection decision={detail.decision} riskCheck={detail.risk_check} fills={detail.fills} />

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

/** 決策鏈 section：strategy → risk_check → fills */
function DecisionChainSection({ decision, riskCheck, fills }) {
    return (
        <DetailSection icon={GitBranch} title="決策鏈">
            <div className="space-y-3">
                {/* Strategy decision */}
                <ChainStep
                    step="1"
                    label="策略決策"
                    color="indigo"
                    content={
                        decision ? (
                            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                                <span className="text-slate-500">策略</span>
                                <span className="text-indigo-300 font-mono">{decision.strategy_id || '-'}</span>
                                <span className="text-slate-500">版本</span>
                                <span className="text-slate-300">{decision.strategy_version || '-'}</span>
                                <span className="text-slate-500">方向</span>
                                <span className={`font-semibold ${decision.signal_side === 'buy' ? 'text-emerald-300' : 'text-rose-300'}`}>
                                    {decision.signal_side?.toUpperCase() || '-'}
                                </span>
                                <span className="text-slate-500">信心分</span>
                                <span className="text-amber-300">{decision.signal_score ?? '-'}</span>
                                <span className="text-slate-500">時間</span>
                                <span className="text-slate-400">{decision.ts ? new Date(decision.ts).toLocaleString('zh-TW', { hour12: false }) : '-'}</span>
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無決策記錄</span>
                        )
                    }
                />

                {/* Risk check */}
                <ChainStep
                    step="2"
                    label="風控核驗"
                    color={riskCheck?.passed ? 'emerald' : 'rose'}
                    content={
                        riskCheck ? (
                            <div className="flex items-center gap-3 text-xs">
                                {riskCheck.passed
                                    ? <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                                    : <XCircle className="h-4 w-4 text-rose-400 flex-shrink-0" />
                                }
                                <span className={riskCheck.passed ? 'text-emerald-300' : 'text-rose-300'}>
                                    {riskCheck.passed ? '通過' : `拒絕：${riskCheck.reject_code || '未知'}`}
                                </span>
                                {riskCheck.metrics?.orders_last_60s != null && (
                                    <span className="text-slate-500">60s 訂單數：{riskCheck.metrics.orders_last_60s}</span>
                                )}
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無風控記錄</span>
                        )
                    }
                />

                {/* Fills */}
                <ChainStep
                    step="3"
                    label="成交明細"
                    color="slate"
                    content={
                        fills && fills.length > 0 ? (
                            <div className="space-y-1">
                                <div className="grid grid-cols-4 gap-2 text-[11px] text-slate-500 font-medium">
                                    <span>時間</span>
                                    <span>數量</span>
                                    <span>價格</span>
                                    <span>手續費</span>
                                </div>
                                {fills.map((f, i) => (
                                    <div key={f.fill_id || i} className="grid grid-cols-4 gap-2 text-xs">
                                        <span className="text-slate-400">
                                            {f.ts ? new Date(f.ts).toLocaleTimeString('zh-TW', { hour12: false }) : '-'}
                                        </span>
                                        <span className="text-slate-200">{f.qty}</span>
                                        <span className="text-slate-200">{formatCurrency(f.price)}</span>
                                        <span className="text-slate-400">{f.fee ? formatCurrency(f.fee) : '0'}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <span className="text-slate-500 text-xs">暫無成交記錄</span>
                        )
                    }
                />
            </div>
        </DetailSection>
    )
}

/** 單一鏈節點 */
function ChainStep({ step, label, color, content }) {
    const dotColor = {
        indigo: 'bg-indigo-500',
        emerald: 'bg-emerald-500',
        rose: 'bg-rose-500',
        slate: 'bg-slate-500',
    }[color] || 'bg-slate-500'

    return (
        <div className="flex gap-3">
            <div className="flex flex-col items-center">
                <div className={`flex h-6 w-6 items-center justify-center rounded-full ${dotColor} text-[10px] font-bold text-white flex-shrink-0`}>
                    {step}
                </div>
                <div className="mt-1 w-px flex-1 bg-slate-800" />
            </div>
            <div className="pb-3 flex-1 min-w-0">
                <div className="text-xs font-semibold text-slate-300 mb-1.5">{label}</div>
                {content}
            </div>
        </div>
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
