/**
 * Agents.jsx -- BattleTheme Redesign
 *
 * Agent execution center. Each agent displayed as a brutalist
 * intelligence card with status dot, monospace labels, expandable
 * execution history. No rounded SaaS cards.
 */

import React, { useCallback, useEffect, useState } from 'react'
import {
    Brain, RefreshCw, Play, Clock, CheckCircle, AlertCircle,
    TrendingUp, Shield, BarChart3, Settings2, Cpu,
    ChevronDown, ChevronUp, Zap
} from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'

/* ── Agent metadata ──────────────────────────────────────────── */
const AGENT_META = {
    market_research: {
        labelZh: 'MARKET RESEARCH',
        labelFull: 'Market Research Agent',
        icon: TrendingUp,
        accentVar: '--up',
    },
    portfolio_review: {
        labelZh: 'PORTFOLIO REVIEW',
        labelFull: 'Portfolio Review Agent',
        icon: BarChart3,
        accentVar: '--info',
    },
    system_health: {
        labelZh: 'SYSTEM HEALTH',
        labelFull: 'System Health Monitor',
        icon: Shield,
        accentVar: '--warn',
    },
    strategy_committee: {
        labelZh: 'STRATEGY COMMITTEE',
        labelFull: 'Strategy Committee',
        icon: Brain,
        accentVar: '--accent',
    },
    system_optimization: {
        labelZh: 'SYS OPTIMIZER',
        labelFull: 'System Optimization Agent',
        icon: Settings2,
        accentVar: '--gold',
    },
}

/* ── Shared components ───────────────────────────────────────── */
function ConfidenceBadge({ value }) {
    if (value == null) return <span className="font-mono text-[10px] text-[rgb(var(--muted))]">--</span>
    const pct = Math.round(value * 100)
    const cls = pct >= 70 ? 'text-[rgb(var(--up))]' : pct >= 40 ? 'text-[rgb(var(--warn))]' : 'text-[rgb(var(--danger))]'
    return <span className={`font-mono text-[10px] font-bold tabular-nums ${cls}`}>{pct}%</span>
}

function RelativeTime({ ts }) {
    if (!ts) return <span className="font-mono text-[10px] text-[rgb(var(--muted))]">NEVER</span>
    const d = new Date(typeof ts === 'number' ? ts : ts.replace(' ', 'T') + (ts.includes('+') ? '' : 'Z'))
    const min = Math.floor((Date.now() - d.getTime()) / 60000)
    let label
    if (min < 1) label = 'JUST NOW'
    else if (min < 60) label = `${min}m AGO`
    else if (min < 1440) label = `${Math.floor(min / 60)}h AGO`
    else label = `${Math.floor(min / 1440)}d AGO`
    return (
        <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]" title={d.toLocaleString('zh-TW')}>
            {label}
        </span>
    )
}

function LatencyBadge({ ms }) {
    if (!ms) return null
    const s = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
    return <span className="font-mono text-[10px] tabular-nums text-[rgb(var(--muted))]">{s}</span>
}

/* ── Agent Card ──────────────────────────────────────────────── */
function AgentCard({ agent, running, onRun }) {
    const [histOpen, setHistOpen] = useState(false)
    const [history, setHistory] = useState(null)
    const [loadingHist, setLoadingHist] = useState(false)

    const meta = AGENT_META[agent.name] || {}
    const Icon = meta.icon || Cpu
    const isRunning = running.includes(agent.name)
    const accentVar = meta.accentVar || '--accent'

    // Status dot color
    const statusColor = isRunning
        ? 'bg-[rgb(var(--warn))] animate-pulse'
        : agent.last_run_at
            ? 'bg-[rgb(var(--up))]'
            : 'bg-[rgb(var(--muted))]'

    const statusLabel = isRunning ? 'RUNNING' : agent.last_run_at ? 'IDLE' : 'NEVER RUN'

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
        <div
            className="flex flex-col overflow-hidden border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.6)]"
            style={{
                borderRadius: '4px',
                borderLeft: `3px solid rgb(var(${accentVar}))`,
            }}
        >
            {/* Card header */}
            <div className="flex items-start justify-between gap-3 border-b border-[rgba(var(--grid),0.15)] px-5 py-4">
                <div className="flex items-center gap-2.5 min-w-0">
                    <Icon className="h-4 w-4 shrink-0" style={{ color: `rgb(var(${accentVar}))` }} />
                    <div className="min-w-0">
                        <div className="font-mono text-xs font-bold uppercase tracking-widest truncate" style={{ color: `rgb(var(${accentVar}))` }}>
                            {meta.labelZh || agent.label}
                        </div>
                        <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-[rgb(var(--muted))]">
                            <Clock className="h-3 w-3 shrink-0" />
                            <span className="truncate">{agent.schedule}</span>
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => onRun(agent.name)}
                    disabled={isRunning}
                    className="shrink-0 flex items-center gap-1.5 border px-3 py-1.5 font-mono text-[10px] font-bold uppercase tracking-widest transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{
                        borderRadius: '3px',
                        borderColor: isRunning ? 'rgba(var(--grid), 0.3)' : `rgba(var(${accentVar}), 0.4)`,
                        backgroundColor: isRunning ? 'rgba(var(--surface), 0.3)' : `rgba(var(${accentVar}), 0.08)`,
                        color: isRunning ? 'rgb(var(--muted))' : `rgb(var(${accentVar}))`,
                    }}
                >
                    {isRunning
                        ? <><RefreshCw className="h-3 w-3 animate-spin" />RUNNING</>
                        : <><Play className="h-3 w-3" />EXECUTE</>
                    }
                </button>
            </div>

            {/* Card body */}
            <div className="flex-1 px-5 py-4 space-y-3">
                {/* Status + metrics */}
                <div className="flex items-center gap-2 mb-3">
                    <span className={`h-2 w-2 rounded-full ${statusColor}`} />
                    <span className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">{statusLabel}</span>
                </div>

                <div className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[10px]">
                    <span className="text-[rgb(var(--muted))]">LAST RUN</span>
                    <RelativeTime ts={agent.last_run_at} />
                    <span className="text-[rgb(var(--muted))]">CONFIDENCE</span>
                    <ConfidenceBadge value={agent.last_confidence} />
                    {agent.last_latency_ms && <>
                        <span className="text-[rgb(var(--muted))]">LATENCY</span>
                        <LatencyBadge ms={agent.last_latency_ms} />
                    </>}
                </div>

                {agent.last_summary ? (
                    <p className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-[11px] leading-relaxed text-[rgb(var(--muted))] line-clamp-3"
                       style={{ borderRadius: '2px' }}
                    >
                        {agent.last_summary}
                    </p>
                ) : (
                    <p className="font-mono text-[11px] italic text-[rgb(var(--muted))]">
                        Not yet executed. Click EXECUTE to trigger.
                    </p>
                )}
            </div>

            {/* History toggle */}
            <div className="border-t border-[rgba(var(--grid),0.15)]">
                <button
                    onClick={toggleHistory}
                    className="w-full flex items-center justify-between px-5 py-3 font-mono text-[10px] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))] hover:bg-[rgba(var(--surface),0.3)] transition-colors"
                >
                    <span className="flex items-center gap-1.5 uppercase tracking-widest">
                        <Zap className="h-3 w-3" />EXECUTION HISTORY
                    </span>
                    {histOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>

                {histOpen && (
                    <div className="px-5 pb-4 space-y-2 max-h-56 overflow-y-auto">
                        {loadingHist && (
                            <div className="flex items-center gap-2 font-mono text-[10px] text-[rgb(var(--muted))] py-2">
                                <RefreshCw className="h-3 w-3 animate-spin" />LOADING...
                            </div>
                        )}
                        {history && history.length === 0 && (
                            <p className="font-mono text-[10px] italic text-[rgb(var(--muted))] py-2">No history</p>
                        )}
                        {history && history.map((h, i) => (
                            <div key={h.trace_id || i}
                                className="border border-[rgba(var(--grid),0.1)] bg-[rgba(var(--surface),0.2)] px-3 py-2 space-y-1"
                                style={{ borderRadius: '2px' }}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    <RelativeTime ts={h.created_at} />
                                    <div className="flex items-center gap-2">
                                        <LatencyBadge ms={h.latency_ms} />
                                        <ConfidenceBadge value={h.confidence} />
                                    </div>
                                </div>
                                {h.summary && (
                                    <p className="font-mono text-[10px] text-[rgb(var(--muted))] line-clamp-2">{h.summary}</p>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Main Page ─────────────────────────────────────────────── */
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
        } catch (e) { setError(e.message) }
    }, [])

    useEffect(() => {
        load()
        const id = setInterval(load, 15000)
        return () => clearInterval(id)
    }, [load])

    useEffect(() => {
        if (running.length === 0) return
        const id = setInterval(load, 3000)
        return () => clearInterval(id)
    }, [running.length, load])

    async function handleRunAll() {
        const toRun = agents.filter(a => !running.includes(a.name))
        for (const agent of toRun) { await handleRun(agent.name) }
    }

    async function handleRun(agentName) {
        try {
            const res = await authFetch(`${getApiBase()}/api/agents/${agentName}/run`, { method: 'POST' })
            if (!res.ok) {
                const b = await res.json().catch(() => ({}))
                throw new Error(b.detail || `HTTP ${res.status}`)
            }
            const meta = AGENT_META[agentName]
            setToast(`${meta?.labelZh || agentName} STARTED`)
            setTimeout(() => setToast(null), 4000)
            setTimeout(load, 500)
        } catch (e) {
            setError(e.message)
            setTimeout(() => setError(null), 6000)
        }
    }

    const totalRuns = agents.filter(a => a.last_run_at).length

    return (
        <div className="space-y-4 pb-20 lg:pb-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="font-mono text-xl font-bold tracking-tight text-[rgb(var(--text))]">AGENT COMMAND CENTER</h1>
                    <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
                        MULTI-AGENT EXECUTION STATUS
                        {totalRuns > 0 && <span className="ml-2">{totalRuns}/{agents.length} EXECUTED</span>}
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button onClick={handleRunAll}
                        disabled={agents.length === 0 || running.length === agents.length}
                        className="flex items-center gap-2 border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-4 py-2.5 font-mono text-xs font-bold uppercase tracking-widest text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.15)] disabled:opacity-40 disabled:cursor-not-allowed"
                        style={{ borderRadius: '3px' }}
                    >
                        <Zap className="h-4 w-4" />EXECUTE ALL
                    </button>
                    <button onClick={load}
                        className="flex items-center gap-2 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2.5 font-mono text-xs text-[rgb(var(--muted))] transition hover:bg-[rgba(var(--surface),0.5)]"
                        style={{ borderRadius: '3px' }}
                    >
                        <RefreshCw className="h-4 w-4" />REFRESH
                    </button>
                </div>
            </div>

            {/* Error / Toast */}
            {error && (
                <div className="flex items-center gap-3 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] px-4 py-3 font-mono text-xs text-[rgb(var(--danger))]" style={{ borderRadius: '2px' }}>
                    <AlertCircle className="h-4 w-4 shrink-0" />{error}
                </div>
            )}
            {toast && (
                <div className="flex items-center gap-3 border-l-2 border-l-[rgb(var(--up))] bg-[rgba(var(--up),0.05)] px-4 py-3 font-mono text-xs text-[rgb(var(--up))]" style={{ borderRadius: '2px' }}>
                    <CheckCircle className="h-4 w-4 shrink-0" />{toast}
                </div>
            )}

            {/* Running banner */}
            {running.length > 0 && (
                <div className="flex items-center gap-2 border border-[rgba(var(--accent),0.2)] bg-[rgba(var(--accent),0.03)] px-4 py-2.5 font-mono text-[10px] text-[rgb(var(--accent))]" style={{ borderRadius: '3px' }}>
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                    RUNNING: {running.map(n => AGENT_META[n]?.labelZh || n).join(', ')} (auto-refresh 3s)
                </div>
            )}

            {/* Loading state */}
            {agents.length === 0 && !error && (
                <div className="flex items-center gap-3 font-mono text-xs text-[rgb(var(--muted))] py-12">
                    <RefreshCw className="h-4 w-4 animate-spin" />LOADING...
                </div>
            )}

            {/* Agent grid -- asymmetric: 5:7 on large */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                {agents.map(agent => (
                    <AgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                ))}
            </div>
        </div>
    )
}
