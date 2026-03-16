import React, { useEffect, useState } from 'react'
import { authFetch, getApiBase, getToken } from '../../lib/auth'

/** 五檔即時報價面板 */
export default function QuotePanel({ symbol }) {
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
            .catch(() => { })
    }, [symbol])

    // BidAsk SSE 即時訂閱
    // Throttled via rAF: we store the latest value in a ref and commit to state
    // once per animation frame to prevent rapid quote pushes from causing jank.
    useEffect(() => {
        if (!symbol) return
        const base = getApiBase()
        const token = getToken()
        const url = `${base}/api/portfolio/quote-stream/${encodeURIComponent(symbol)}${token ? `?token=${token}` : ''}`
        const es = new EventSource(url)

        const latestRef = { current: null }
        let rafId = null

        function flushBidask() {
            rafId = null
            if (latestRef.current) {
                setBidask(latestRef.current)
                latestRef.current = null
            }
        }

        es.onopen = () => setLive(true)
        es.onmessage = e => {
            try {
                const d = JSON.parse(e.data)
                if (d.type === 'bidask') {
                    latestRef.current = d
                    if (rafId == null) rafId = requestAnimationFrame(flushBidask)
                }
            } catch { }
        }
        es.onerror = () => setLive(false)
        return () => {
            if (rafId != null) cancelAnimationFrame(rafId)
            es.close()
            setLive(false)
        }
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
                    <div className={`text-base font-semibold ${snap?.change_rate == null ? 'text-slate-400'
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
