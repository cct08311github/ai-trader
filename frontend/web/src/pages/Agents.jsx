import React, { useCallback, useEffect, useState } from 'react'
import {
    Brain, RefreshCw, Play, Clock, CheckCircle, AlertCircle,
    TrendingUp, Shield, BarChart3, Settings2, Cpu,
    ChevronDown, ChevronUp, Zap
} from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'

/* ── Agent 前端元數據 ─────────────────────────────────────────────────────── */

const AGENT_META = {
    market_research: {
        labelZh: '市場研究員',
        icon: TrendingUp,
        color: 'text-emerald-400',
        ringColor: 'ring-emerald-500/20',
        borderColor: 'border-emerald-500/20',
        bgColor: 'bg-emerald-500/5',
        btnColor: 'text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/10',
    },
    portfolio_review: {
        labelZh: 'Portfolio 審查員',
        icon: BarChart3,
        color: 'text-sky-400',
        ringColor: 'ring-sky-500/20',
        borderColor: 'border-sky-500/20',
        bgColor: 'bg-sky-500/5',
        btnColor: 'text-sky-300 border-sky-500/30 hover:bg-sky-500/10',
    },
    system_health: {
        labelZh: '系統健康監控',
        icon: Shield,
        color: 'text-orange-400',
        ringColor: 'ring-orange-500/20',
        borderColor: 'border-orange-500/20',
        bgColor: 'bg-orange-500/5',
        btnColor: 'text-orange-300 border-orange-500/30 hover:bg-orange-500/10',
    },
    strategy_committee: {
        labelZh: '策略小組',
        icon: Brain,
        color: 'text-violet-400',
        ringColor: 'ring-violet-500/20',
        borderColor: 'border-violet-500/20',
        bgColor: 'bg-violet-500/5',
        btnColor: 'text-violet-300 border-violet-500/30 hover:bg-violet-500/10',
    },
    system_optimization: {
        labelZh: '系統優化員',
        icon: Settings2,
        color: 'text-amber-400',
        ringColor: 'ring-amber-500/20',
        borderColor: 'border-amber-500/20',
        bgColor: 'bg-amber-500/5',
        btnColor: 'text-amber-300 border-amber-500/30 hover:bg-amber-500/10',
    },
}

/* ── 共用小元件 ──────────────────────────────────────────────────────────── */

function ConfidenceBadge({ value }) {
    if (value == null) return <span className="text-xs text-slate-600 font-mono">—</span>
    const pct = Math.round(value * 100)
    const cls = pct >= 70 ? 'text-emerald-400' : pct >= 40 ? 'text-amber-400' : 'text-rose-400'
    return <span className={`text-xs font-mono font-semibold ${cls}`}>{pct}%</span>
}

function RelativeTime({ ts }) {
    if (!ts) return <span className="text-slate-600 text-xs">從未執行</span>
    const d = new Date(typeof ts === 'number' ? ts : ts.replace(' ', 'T') + (ts.includes('+') ? '' : 'Z'))
    const min = Math.floor((Date.now() - d.getTime()) / 60000)
    let label
    if (min < 1) label = '剛剛'
    else if (min < 60) label = `${min} 分鐘前`
    else if (min < 1440) label = `${Math.floor(min / 60)} 小時前`
    else label = `${Math.floor(min / 1440)} 天前`
    return (
        <span className="text-xs text-slate-400" title={d.toLocaleString('zh-TW')}>
            {label}
        </span>
    )
}

function LatencyBadge({ ms }) {
    if (!ms) return null
    const s = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
    return <span className="text-xs text-slate-600 font-mono">{s}</span>
}

/* ── Agent 卡片 ──────────────────────────────────────────────────────────── */

function AgentCard({ agent, running, onRun }) {
    const [histOpen, setHistOpen] = useState(false)
    const [history, setHistory] = useState(null)
    const [loadingHist, setLoadingHist] = useState(false)

    const meta = AGENT_META[agent.name] || {}
    const Icon = meta.icon || Cpu
    const isRunning = running.includes(agent.name)

    async function loadHistory() {
        setLoadingHist(true)
        try {
            const res = await authFetch(`${getApiBase()}/api/agents/${agent.name}/history?limit=10`)
            const data = await res.json()
            setHistory(data.data || [])
        } catch { /* ignore */ }
        finally { setLoadingHist(false) }
    }

    function toggleHistory() {
        if (!histOpen && !history) loadHistory()
        setHistOpen(o => !o)
    }

    return (
        <div className={`rounded-2xl border ${meta.borderColor || 'border-slate-800'} bg-slate-900/40 overflow-hidden flex flex-col`}>
            {/* Card header */}
            <div className={`px-5 py-4 ${meta.bgColor || ''} border-b border-slate-800/60 flex items-start justify-between gap-3`}>
                <div className="flex items-center gap-2.5 min-w-0">
                    <Icon className={`h-4 w-4 ${meta.color || 'text-slate-400'} shrink-0`} />
                    <div className="min-w-0">
                        <div className={`text-sm font-semibold ${meta.color || 'text-slate-200'} truncate`}>
                            {meta.labelZh || agent.label}
                        </div>
                        <div className="text-xs text-slate-500 flex items-center gap-1 mt-0.5">
                            <Clock className="h-3 w-3 shrink-0" />
                            <span className="truncate">{agent.schedule}</span>
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => onRun(agent.name)}
                    disabled={isRunning}
                    className={`shrink-0 flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all ${
                        isRunning
                            ? 'border-slate-700 bg-slate-800 text-slate-500 cursor-not-allowed'
                            : `${meta.btnColor || 'text-slate-300 border-slate-700 hover:bg-slate-800'} bg-transparent`
                    }`}
                >
                    {isRunning
                        ? <><RefreshCw className="h-3 w-3 animate-spin" />執行中</>
                        : <><Play className="h-3 w-3" />立即執行</>
                    }
                </button>
            </div>

            {/* Card body */}
            <div className="px-5 py-4 space-y-3 flex-1">
                <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                    <span className="text-slate-500">上次執行</span>
                    <RelativeTime ts={agent.last_run_at} />
                    <span className="text-slate-500">信心度</span>
                    <ConfidenceBadge value={agent.last_confidence} />
                    {agent.last_latency_ms && <>
                        <span className="text-slate-500">耗時</span>
                        <LatencyBadge ms={agent.last_latency_ms} />
                    </>}
                </div>

                {agent.last_summary ? (
                    <p className="text-xs text-slate-400 leading-relaxed line-clamp-3 rounded-xl bg-slate-950/50 border border-slate-800/60 px-3 py-2">
                        {agent.last_summary}
                    </p>
                ) : (
                    <p className="text-xs text-slate-600 italic">
                        尚未執行，點擊「立即執行」觸發首次分析。
                    </p>
                )}
            </div>

            {/* History toggle */}
            <div className="border-t border-slate-800/60">
                <button
                    onClick={toggleHistory}
                    className="w-full flex items-center justify-between px-5 py-3 text-xs text-slate-500 hover:text-slate-300 hover:bg-slate-800/20 transition-colors"
                >
                    <span className="flex items-center gap-1.5">
                        <Zap className="h-3 w-3" />執行歷史
                    </span>
                    {histOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>

                {histOpen && (
                    <div className="px-5 pb-4 space-y-2 max-h-56 overflow-y-auto">
                        {loadingHist && (
                            <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
                                <RefreshCw className="h-3 w-3 animate-spin" />載入中...
                            </div>
                        )}
                        {history && history.length === 0 && (
                            <p className="text-xs text-slate-600 py-2 italic">無歷史記錄</p>
                        )}
                        {history && history.map((h, i) => (
                            <div
                                key={h.trace_id || i}
                                className="rounded-xl border border-slate-800/60 bg-slate-950/30 px-3 py-2 space-y-1"
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <RelativeTime ts={h.created_at} />
                                    <div className="flex items-center gap-2">
                                        <LatencyBadge ms={h.latency_ms} />
                                        <ConfidenceBadge value={h.confidence} />
                                    </div>
                                </div>
                                {h.summary && (
                                    <p className="text-xs text-slate-500 line-clamp-2">{h.summary}</p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── 主頁面 ──────────────────────────────────────────────────────────────── */

export default function AgentsPage() {
    const [agents, setAgents] = useState([])
    const [running, setRunning] = useState([])
    const [error, setError] = useState(null)
    const [toast, setToast] = useState(null)

    const load = useCallback(async () => {
        try {
            const res = await authFetch(`${getApiBase()}/api/agents`)
            const data = await res.json()
            setAgents(data.data || [])
            setRunning(data.running || [])
            setError(null)
        } catch (e) {
            setError(e.message)
        }
    }, [])

    // 一般輪詢
    useEffect(() => {
        load()
        const id = setInterval(load, 15000)
        return () => clearInterval(id)
    }, [load])

    // 執行中時加速輪詢
    useEffect(() => {
        if (running.length === 0) return
        const id = setInterval(load, 3000)
        return () => clearInterval(id)
    }, [running.length, load])

    async function handleRun(agentName) {
        try {
            const res = await authFetch(`${getApiBase()}/api/agents/${agentName}/run`, { method: 'POST' })
            if (!res.ok) {
                const b = await res.json().catch(() => ({}))
                throw new Error(b.detail || `HTTP ${res.status}`)
            }
            const meta = AGENT_META[agentName]
            setToast(`${meta?.labelZh || agentName} 已啟動`)
            setTimeout(() => setToast(null), 4000)
            setTimeout(load, 500)
        } catch (e) {
            setError(e.message)
            setTimeout(() => setError(null), 6000)
        }
    }

    const totalRuns = agents.filter(a => a.last_run_at).length

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-slate-100 tracking-tight">Agent 執行中心</h1>
                    <p className="mt-1 text-sm text-slate-400">
                        監控各 AI Agent 執行狀態，或手動觸發分析任務。
                        {totalRuns > 0 && <span className="ml-2 text-slate-500">{totalRuns}/{agents.length} 個 Agent 已執行過</span>}
                    </p>
                </div>
                <button
                    onClick={load}
                    className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
                >
                    <RefreshCw className="h-4 w-4" />刷新
                </button>
            </div>

            {/* Toast / Error */}
            {error && (
                <div className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    <AlertCircle className="h-4 w-4 shrink-0" />{error}
                </div>
            )}
            {toast && (
                <div className="flex items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
                    <CheckCircle className="h-4 w-4 shrink-0" />{toast}
                </div>
            )}

            {/* Running banner */}
            {running.length > 0 && (
                <div className="flex items-center gap-2 rounded-xl border border-violet-500/20 bg-violet-500/5 px-4 py-2.5 text-xs text-violet-300">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    執行中：{running.map(n => AGENT_META[n]?.labelZh || n).join('、')}（每 3 秒自動刷新）
                </div>
            )}

            {/* Agent grid */}
            {agents.length === 0 && !error && (
                <div className="flex items-center gap-3 text-sm text-slate-400 py-12">
                    <RefreshCw className="h-4 w-4 animate-spin" />載入中...
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                {agents.map(agent => (
                    <AgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                ))}
            </div>
        </div>
    )
}
