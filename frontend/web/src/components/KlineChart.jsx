import React, { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'

/* ── K線圖（純 SVG，共用元件） ─────────────────────────── */
const VB_W = 400, VB_H = 200
const PAD = { top: 8, right: 6, bottom: 22, left: 44 }
const PRICE_H = 126, VOL_H = 28, VOL_Y = PAD.top + PRICE_H + 10

const PERIODS = [
    { key: 'daily',   label: '日', bars: 60 },
    { key: 'weekly',  label: '週', bars: 52 },
    { key: 'monthly', label: '月', bars: 36 },
]

// 日期標籤格式：日線 MM-DD，週/月線 YY-MM
function fmtLabel(date, period) {
    if (!date) return ''
    if (period === 'daily') return date.slice(5)       // MM-DD
    if (period === 'monthly') return date.slice(2, 7)  // YY-MM
    return date.slice(5)                               // MM-DD (週線用期末日)
}

export default function KlineChart({ symbol }) {
    const [period, setPeriod] = useState('daily')
    const [data, setData] = useState(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!symbol) return
        setLoading(true)
        const bars = PERIODS.find(p => p.key === period)?.bars ?? 60
        authFetch(`${getApiBase()}/api/portfolio/kline/${encodeURIComponent(symbol)}?days=${bars}&period=${period}`)
            .then(r => r.json())
            .then(d => { setData(d.data || []); setLoading(false) })
            .catch(() => { setData([]); setLoading(false) })
    }, [symbol, period])

    const periodLabel = PERIODS.find(p => p.key === period)?.label ?? '日'

    return (
        <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-3">
            <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-200">K 線圖</span>
                    <div className="flex rounded-md overflow-hidden border border-slate-700">
                        {PERIODS.map(p => (
                            <button key={p.key} onClick={() => setPeriod(p.key)}
                                className={`px-2.5 py-0.5 text-xs transition-colors ${
                                    period === p.key
                                        ? 'bg-emerald-500/25 text-emerald-300'
                                        : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
                                }`}
                            >{p.label}</button>
                        ))}
                    </div>
                </div>
                {data && data.length > 0 && (
                    <span className="text-[11px] text-slate-500">
                        {data[0].trade_date} ~ {data[data.length - 1].trade_date}
                    </span>
                )}
            </div>

            {loading ? (
                <div className="flex items-center justify-center" style={{ height: 170 }}>
                    <RefreshCw className="h-4 w-4 animate-spin text-slate-500" />
                </div>
            ) : !data || data.length === 0 ? (
                <div className="flex items-center justify-center" style={{ height: 80 }}>
                    <span className="text-xs text-slate-500">無 {periodLabel}線歷史資料</span>
                </div>
            ) : (() => {
                const chartW = VB_W - PAD.left - PAD.right
                const n = data.length
                const xStep = chartW / n
                const cw = Math.max(2, Math.min(10, Math.floor(xStep * 0.65)))
                const cx = i => PAD.left + (i + 0.5) * xStep

                const minP = Math.min(...data.map(d => d.low))
                const maxP = Math.max(...data.map(d => d.high))
                const pPad = (maxP - minP) * 0.04 || 1
                const pMin = minP - pPad, pMax = maxP + pPad
                const py = price => PAD.top + PRICE_H - ((price - pMin) / (pMax - pMin)) * PRICE_H

                const maxVol = Math.max(...data.map(d => d.volume || 0))
                const pTicks = [0, 1, 2, 3].map(i => pMin + (pMax - pMin) * (i / 3))
                const labelStep = Math.max(1, Math.floor(n / 5))
                const dLabels = data.map((d, i) => ({ i, date: d.trade_date }))
                    .filter(({ i }) => i % labelStep === 0 || i === n - 1)

                return (
                    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full" style={{ height: 170 }}>
                        {pTicks.map((tick, i) => (
                            <line key={i} x1={PAD.left} y1={py(tick)} x2={PAD.left + chartW} y2={py(tick)}
                                stroke="rgba(148,163,184,0.08)" strokeWidth="1" />
                        ))}
                        {pTicks.map((tick, i) => (
                            <text key={i} x={PAD.left - 3} y={py(tick) + 3.5}
                                textAnchor="end" fill="rgba(148,163,184,0.55)" fontSize="9">
                                {tick.toFixed(1)}
                            </text>
                        ))}
                        <line x1={PAD.left} y1={VOL_Y - 4} x2={PAD.left + chartW} y2={VOL_Y - 4}
                            stroke="rgba(148,163,184,0.06)" strokeWidth="1" />
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
                        {dLabels.map(({ i, date }) => (
                            <text key={i} x={cx(i)} y={VB_H - 4}
                                textAnchor="middle" fill="rgba(148,163,184,0.55)" fontSize="9">
                                {fmtLabel(date, period)}
                            </text>
                        ))}
                    </svg>
                )
            })()}
        </div>
    )
}
