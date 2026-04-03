/**
 * Agents.jsx -- Mission Control Layout
 *
 * Complete layout restructure:
 *   Top: System status bar -- total agents, running, last error, uptime
 *   Main: Irregular layout -- active=LARGE, idle=SMALL, error=RED pulsing top
 *   Right sidebar (desktop): Agent execution timeline
 *
 * All data fetching and state management preserved from original.
 */

import React, { useCallback, useEffect, useState, useMemo } from 'react'
import {
    Brain, RefreshCw, Play, Clock, CheckCircle, AlertCircle,
    TrendingUp, Shield, BarChart3, Settings2, Cpu,
    ChevronDown, ChevronUp, Zap, Activity
} from 'lucide-react'
import { authFetch, getApiBase } from '../lib/auth'

/* ── Agent metadata ──────────────────────────────────────── */
const AGENT_META = {
    market_research: { labelZh: 'MARKET RESEARCH', labelFull: 'Market Research Agent', icon: TrendingUp, accentVar: '--up' },
    portfolio_review: { labelZh: 'PORTFOLIO REVIEW', labelFull: 'Portfolio Review Agent', icon: BarChart3, accentVar: '--info' },
    system_health: { labelZh: 'SYSTEM HEALTH', labelFull: 'System Health Monitor', icon: Shield, accentVar: '--warn' },
    strategy_committee: { labelZh: 'STRATEGY COMMITTEE', labelFull: 'Strategy Committee', icon: Brain, accentVar: '--accent' },
    system_optimization: { labelZh: 'SYS OPTIMIZER', labelFull: 'System Optimization Agent', icon: Settings2, accentVar: '--gold' },
}

/* ── Shared components ──────────────────────────────────── */
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

/* ── Large Agent Card (for active/running) ───────────────── */
function LargeAgentCard({ agent, running, onRun }) {
    const [histOpen, setHistOpen] = useState(false)
    const [history, setHistory] = useState(null)
    const [loadingHist, setLoadingHist] = useState(false)

    const meta = AGENT_META[agent.name] || {}
    const Icon = meta.icon || Cpu
    const isRunning = running.includes(agent.name)
    const accentVar = meta.accentVar || '--accent'

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
        <div className={`border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.5)] overflow-hidden ${
            isRunning ? 'ring-1 ring-[rgba(var(--warn),0.4)]' : ''
        }`} style={{ borderRadius: '4px', borderLeft: `4px solid rgb(var(${accentVar}))` }}>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[rgba(var(--grid),0.15)]">
                <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center h-10 w-10 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]"
                         style={{ borderRadius: '3px' }}>
                        <Icon className="h-5 w-5" style={{ color: `rgb(var(${accentVar}))` }} />
                    </div>
                    <div>
                        <div className="font-mono text-sm font-black uppercase tracking-widest" style={{ color: `rgb(var(${accentVar}))` }}>
                            {meta.labelZh || agent.label}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                            <span className={`h-2 w-2 rounded-full ${isRunning ? 'bg-[rgb(var(--warn))] animate-pulse' : agent.last_run_at ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--muted))]'}`}
                                  style={{ boxShadow: isRunning ? '0 0 8px rgba(var(--warn),0.5)' : 'none' }} />
                            <span className="font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
                                {isRunning ? 'RUNNING' : agent.last_run_at ? 'IDLE' : 'NEVER RUN'}
                            </span>
                        </div>
                    </div>
                </div>
                <button onClick={() => onRun(agent.name)} disabled={isRunning}
                    className="flex items-center gap-2 border-2 px-4 py-2.5 font-mono text-[10px] font-bold uppercase tracking-widest transition-all disabled:opacity-40"
                    style={{
                        borderRadius: '3px',
                        borderColor: isRunning ? 'rgba(var(--grid),0.3)' : `rgb(var(${accentVar}))`,
                        backgroundColor: isRunning ? 'rgba(var(--surface),0.3)' : `rgba(var(${accentVar}),0.1)`,
                        color: isRunning ? 'rgb(var(--muted))' : `rgb(var(${accentVar}))`,
                    }}>
                    {isRunning ? <><RefreshCw className="h-4 w-4 animate-spin" />RUNNING</> : <><Play className="h-4 w-4" />EXECUTE</>}
                </button>
            </div>

            {/* Body */}
            <div className="px-5 py-4">
                {/* Current task / last summary */}
                {isRunning ? (
                    <div className="space-y-2">
                        <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">CURRENT TASK</div>
                        <div className="font-mono text-xs text-[rgb(var(--text))]">{agent.last_summary || 'Executing...'}</div>
                        {/* Simulated log tail */}
                        <div className="border border-[rgba(var(--grid),0.15)] bg-[rgb(var(--bg))] p-3 font-mono text-[10px] text-[rgb(var(--up))] space-y-0.5 max-h-16 overflow-hidden" style={{ borderRadius: '2px' }}>
                            <div>$ agent.run({agent.name})</div>
                            <div className="text-[rgb(var(--muted))]">... processing ...</div>
                            <div className="animate-pulse">{'>'} awaiting response</div>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-3">
                        <div className="grid grid-cols-3 gap-4">
                            <div>
                                <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">LAST RUN</div>
                                <div className="mt-1"><RelativeTime ts={agent.last_run_at} /></div>
                            </div>
                            <div>
                                <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CONFIDENCE</div>
                                <div className="mt-1"><ConfidenceBadge value={agent.last_confidence} /></div>
                            </div>
                            <div>
                                <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">LATENCY</div>
                                <div className="mt-1"><LatencyBadge ms={agent.last_latency_ms} /></div>
                            </div>
                        </div>
                        {agent.last_summary && (
                            <div className="border-l-2 border-l-[rgba(var(--grid),0.3)] pl-3 font-mono text-[11px] leading-relaxed text-[rgb(var(--muted))] line-clamp-3">
                                {agent.last_summary}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Schedule */}
            <div className="flex items-center gap-2 px-5 py-2 border-t border-[rgba(var(--grid),0.1)] font-mono text-[10px] text-[rgb(var(--muted))]">
                <Clock className="h-3 w-3" />
                <span>{agent.schedule}</span>
            </div>

            {/* History toggle */}
            <div className="border-t border-[rgba(var(--grid),0.15)]">
                <button onClick={toggleHistory}
                    className="w-full flex items-center justify-between px-5 py-2.5 font-mono text-[10px] text-[rgb(var(--muted))] hover:text-[rgb(var(--text))] hover:bg-[rgba(var(--surface),0.3)] transition-colors">
                    <span className="flex items-center gap-1.5 uppercase tracking-widest"><Zap className="h-3 w-3" />EXECUTION HISTORY</span>
                    {histOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                </button>
                {histOpen && (
                    <div className="px-5 pb-4 space-y-2 max-h-56 overflow-y-auto">
                        {loadingHist && <div className="flex items-center gap-2 font-mono text-[10px] text-[rgb(var(--muted))] py-2"><RefreshCw className="h-3 w-3 animate-spin" />LOADING...</div>}
                        {history && history.length === 0 && <p className="font-mono text-[10px] italic text-[rgb(var(--muted))] py-2">No history</p>}
                        {history && history.map((h, i) => (
                            <div key={h.trace_id || i} className="border border-[rgba(var(--grid),0.1)] bg-[rgba(var(--surface),0.2)] px-3 py-2 space-y-1" style={{ borderRadius: '2px' }}>
                                <div className="flex items-center justify-between gap-2">
                                    <RelativeTime ts={h.created_at} />
                                    <div className="flex items-center gap-2">
                                        <LatencyBadge ms={h.latency_ms} />
                                        <ConfidenceBadge value={h.confidence} />
                                    </div>
                                </div>
                                {h.summary && <p className="font-mono text-[10px] text-[rgb(var(--muted))] line-clamp-2">{h.summary}</p>}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}

/* ── Small Agent Card (for idle/never-run) ───────────────── */
function SmallAgentCard({ agent, running, onRun }) {
    const meta = AGENT_META[agent.name] || {}
    const Icon = meta.icon || Cpu
    const isRunning = running.includes(agent.name)
    const accentVar = meta.accentVar || '--accent'

    return (
        <div className="flex items-center gap-3 border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-4 py-3 transition-all hover:bg-[rgba(var(--surface),0.5)]"
             style={{ borderRadius: '3px', borderLeft: `3px solid rgb(var(${accentVar}))` }}>
            <Icon className="h-4 w-4 shrink-0" style={{ color: `rgb(var(${accentVar}))` }} />
            <div className="flex-1 min-w-0">
                <div className="font-mono text-[10px] font-bold uppercase tracking-widest truncate" style={{ color: `rgb(var(${accentVar}))` }}>
                    {meta.labelZh || agent.label}
                </div>
                <div className="flex items-center gap-2 mt-0.5 font-mono text-[9px] text-[rgb(var(--muted))]">
                    <span className={`h-1.5 w-1.5 rounded-full ${agent.last_run_at ? 'bg-[rgb(var(--up))]' : 'bg-[rgb(var(--muted))]'}`} />
                    <span>{agent.last_run_at ? 'IDLE' : 'NEVER RUN'}</span>
                    {agent.last_run_at && <RelativeTime ts={agent.last_run_at} />}
                </div>
            </div>
            <button onClick={() => onRun(agent.name)} disabled={isRunning}
                className="shrink-0 flex items-center gap-1.5 border px-2.5 py-1.5 font-mono text-[9px] font-bold uppercase tracking-widest disabled:opacity-40"
                style={{
                    borderRadius: '2px',
                    borderColor: `rgba(var(${accentVar}),0.4)`,
                    backgroundColor: `rgba(var(${accentVar}),0.08)`,
                    color: `rgb(var(${accentVar}))`,
                }}>
                {isRunning ? <RefreshCw className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
                {isRunning ? 'RUN' : 'GO'}
            </button>
        </div>
    )
}

/* ── Error Agent Card (highlighted, pulsing) ─────────────── */
function ErrorAgentCard({ agent, running, onRun }) {
    const meta = AGENT_META[agent.name] || {}
    const Icon = meta.icon || Cpu

    return (
        <div className="border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] px-5 py-4 animate-pulse"
             style={{ borderRadius: '4px', boxShadow: '0 0 16px rgba(var(--danger),0.15)' }}>
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center h-8 w-8 border border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)]" style={{ borderRadius: '3px' }}>
                        <AlertCircle className="h-4 w-4 text-[rgb(var(--danger))]" />
                    </div>
                    <div>
                        <div className="font-mono text-xs font-black uppercase tracking-widest text-[rgb(var(--danger))]">{meta.labelZh || agent.label}</div>
                        <div className="font-mono text-[10px] text-[rgb(var(--danger))]">ERROR -- REQUIRES ATTENTION</div>
                    </div>
                </div>
                <button onClick={() => onRun(agent.name)}
                    className="border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] px-4 py-2 font-mono text-[10px] font-bold uppercase text-[rgb(var(--danger))]"
                    style={{ borderRadius: '3px' }}>RETRY</button>
            </div>
            {agent.last_summary && (
                <div className="mt-3 border-l-2 border-l-[rgb(var(--danger))] pl-3 font-mono text-[10px] text-[rgb(var(--danger))]">{agent.last_summary}</div>
            )}
        </div>
    )
}

/* ── Timeline Entry ──────────────────────────────────────── */
function TimelineEntry({ agent, isLast }) {
    const meta = AGENT_META[agent.name] || {}
    const accentVar = meta.accentVar || '--accent'

    return (
        <div className="flex gap-3">
            {/* Dot + line */}
            <div className="flex flex-col items-center">
                <div className="h-3 w-3 rounded-full border-2 shrink-0"
                     style={{ borderColor: `rgb(var(${accentVar}))`, backgroundColor: agent.last_run_at ? `rgb(var(${accentVar}))` : 'transparent' }} />
                {!isLast && <div className="flex-1 w-px bg-[rgba(var(--grid),0.2)]" />}
            </div>
            {/* Content */}
            <div className="pb-4 min-w-0">
                <div className="font-mono text-[10px] font-bold uppercase tracking-widest" style={{ color: `rgb(var(${accentVar}))` }}>
                    {meta.labelZh || agent.name}
                </div>
                <div className="mt-0.5 font-mono text-[9px] text-[rgb(var(--muted))]">
                    <RelativeTime ts={agent.last_run_at} />
                </div>
                {agent.last_summary && (
                    <div className="mt-1 font-mono text-[9px] text-[rgb(var(--muted))] line-clamp-2">{agent.last_summary}</div>
                )}
            </div>
        </div>
    )
}

/* ══════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════ */
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

    // Categorize agents
    const { errorAgents, runningAgents, activeAgents, idleAgents } = useMemo(() => {
        const errorAgents = agents.filter(a => a.last_error || a.status === 'error')
        const runningAgents = agents.filter(a => running.includes(a.name) && !errorAgents.includes(a))
        const activeAgents = agents.filter(a => a.last_run_at && !running.includes(a.name) && !errorAgents.includes(a))
        const idleAgents = agents.filter(a => !a.last_run_at && !running.includes(a.name) && !errorAgents.includes(a))
        return { errorAgents, runningAgents, activeAgents, idleAgents }
    }, [agents, running])

    const totalRuns = agents.filter(a => a.last_run_at).length
    const sortedForTimeline = useMemo(() =>
        [...agents].sort((a, b) => {
            if (!a.last_run_at) return 1
            if (!b.last_run_at) return -1
            return new Date(b.last_run_at) - new Date(a.last_run_at)
        })
    , [agents])

    return (
        <div className="space-y-4 pb-20 lg:pb-4">

            {/* ══════════════════════════════════════════════════════════
                SYSTEM STATUS BAR
                ══════════════════════════════════════════════════════════ */}
            <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.5)]" style={{ borderRadius: '4px' }}>
                <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-3">
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2">
                            <Activity className="h-4 w-4 text-[rgb(var(--accent))]" />
                            <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">MISSION CONTROL</span>
                        </div>
                        {/* Stats */}
                        <div className="flex items-center gap-4 font-mono text-[10px]">
                            <span className="text-[rgb(var(--text))]"><span className="text-[rgb(var(--muted))]">AGENTS:</span> {agents.length}</span>
                            {running.length > 0 && (
                                <span className="text-[rgb(var(--warn))]">
                                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-[rgb(var(--warn))] animate-pulse mr-1" />
                                    RUNNING: {running.length}
                                </span>
                            )}
                            <span className="text-[rgb(var(--muted))]">EXECUTED: {totalRuns}/{agents.length}</span>
                            {errorAgents.length > 0 && (
                                <span className="text-[rgb(var(--danger))] font-bold">ERRORS: {errorAgents.length}</span>
                            )}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button onClick={handleRunAll}
                            disabled={agents.length === 0 || running.length === agents.length}
                            className="flex items-center gap-2 border-2 border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.08)] px-4 py-2 font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.15)] disabled:opacity-40"
                            style={{ borderRadius: '3px' }}>
                            <Zap className="h-3.5 w-3.5" />EXECUTE ALL
                        </button>
                        <button onClick={load}
                            className="flex items-center gap-1.5 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-[10px] text-[rgb(var(--muted))]"
                            style={{ borderRadius: '3px' }}>
                            <RefreshCw className="h-3.5 w-3.5" />
                        </button>
                    </div>
                </div>

                {/* Running banner */}
                {running.length > 0 && (
                    <div className="border-t border-[rgba(var(--grid),0.15)] px-5 py-2 font-mono text-[10px] text-[rgb(var(--accent))]">
                        <RefreshCw className="h-3 w-3 animate-spin inline mr-2" />
                        ACTIVE: {running.map(n => AGENT_META[n]?.labelZh || n).join(', ')} (auto-refresh 3s)
                    </div>
                )}
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

            {/* Loading */}
            {agents.length === 0 && !error && (
                <div className="flex items-center gap-3 font-mono text-xs text-[rgb(var(--muted))] py-12">
                    <RefreshCw className="h-4 w-4 animate-spin" />LOADING...
                </div>
            )}

            {/* ══════════════════════════════════════════════════════════
                MAIN LAYOUT -- agents + timeline sidebar
                ══════════════════════════════════════════════════════════ */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">

                {/* ── MAIN COLUMN: Irregular agent cards ────── */}
                <div className="lg:col-span-9 space-y-4">

                    {/* ERROR agents -- pulled to top, pulsing */}
                    {errorAgents.map(agent => (
                        <ErrorAgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                    ))}

                    {/* RUNNING agents -- large cards, full width */}
                    {runningAgents.map(agent => (
                        <LargeAgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                    ))}

                    {/* ACTIVE agents -- large cards, 2-col on desktop */}
                    {activeAgents.length > 0 && (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {activeAgents.map(agent => (
                                <LargeAgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                            ))}
                        </div>
                    )}

                    {/* IDLE agents -- compact row at bottom */}
                    {idleAgents.length > 0 && (
                        <div>
                            <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] px-1 mb-2">IDLE AGENTS</div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {idleAgents.map(agent => (
                                    <SmallAgentCard key={agent.name} agent={agent} running={running} onRun={handleRun} />
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                {/* ── RIGHT SIDEBAR: Execution Timeline ─────── */}
                <div className="lg:col-span-3">
                    <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] sticky top-4" style={{ borderRadius: '4px' }}>
                        <div className="border-b border-[rgba(var(--grid),0.3)] px-4 py-2.5">
                            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-[rgb(var(--text))]">EXECUTION TIMELINE</span>
                        </div>
                        <div className="p-4">
                            {sortedForTimeline.map((agent, i) => (
                                <TimelineEntry key={agent.name} agent={agent} isLast={i === sortedForTimeline.length - 1} />
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
