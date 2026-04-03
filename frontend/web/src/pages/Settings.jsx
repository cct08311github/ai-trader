/**
 * Settings.jsx -- BattleTheme Redesign
 *
 * System configuration war room. Dramatic toggles for trading
 * switches, sentinel circuit breakers, authority levels.
 * Brutalist panels, monospace labels, accent borders.
 */

import React, { useCallback, useEffect, useState } from 'react'
import {
    DollarSign, Shield, TrendingDown, CheckCircle, AlertCircle,
    Save, RefreshCw, Lock, Bell, Layers, ChevronDown, ChevronUp,
    List, Plus, X, Zap
} from 'lucide-react'
import { formatComma } from '../lib/format'
import { authFetch, getApiBase } from '../lib/auth'

/* ── API helper ──────────────────────────────────────────────── */
async function apiFetch(path, opts = {}) {
    const res = await authFetch(`${getApiBase()}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    })
    if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
    }
    return res.json()
}

/* ── Section (collapsible brutalist panel) ────────────────── */
function Section({ title, icon: Icon, accentVar = '--accent', children, defaultOpen = true }) {
    const [open, setOpen] = useState(defaultOpen)
    return (
        <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.6)] overflow-hidden"
             style={{ borderRadius: '4px', borderLeft: `3px solid rgb(var(${accentVar}))` }}>
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                className="w-full flex items-center justify-between px-5 py-4 font-mono text-xs font-bold uppercase tracking-widest hover:bg-[rgba(var(--surface),0.3)] transition-colors"
                style={{ color: `rgb(var(${accentVar}))` }}
            >
                <span className="flex items-center gap-2"><Icon className="h-4 w-4" />{title}</span>
                {open ? <ChevronUp className="h-4 w-4 opacity-50" /> : <ChevronDown className="h-4 w-4 opacity-50" />}
            </button>
            {open && <div className="px-5 pb-5 space-y-4 border-t border-[rgba(var(--grid),0.15)]">{children}</div>}
        </div>
    )
}

/* ── Field ───────────────────────────────────────────────────── */
function Field({ label, hint, value, onChange, prefix, suffix, type = 'number', min, max, step = 1 }) {
    return (
        <div className="flex flex-col gap-1">
            <label className="pt-4 font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">{label}</label>
            {hint && <p className="font-mono text-[10px] text-[rgb(var(--muted))] mb-1">{hint}</p>}
            <div className="flex items-center gap-2 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 focus-within:border-[rgba(var(--accent),0.5)] transition-all"
                 style={{ borderRadius: '3px' }}
            >
                {prefix && <span className="font-mono text-xs text-[rgb(var(--muted))] shrink-0">{prefix}</span>}
                <input
                    type={type}
                    min={min} max={max} step={step}
                    value={value}
                    onChange={e => onChange(type === 'number' ? Number(e.target.value) : e.target.value)}
                    className="flex-1 bg-transparent font-mono text-sm tabular-nums text-[rgb(var(--text))] outline-none"
                />
                {suffix && <span className="font-mono text-xs text-[rgb(var(--muted))] shrink-0">{suffix}</span>}
            </div>
        </div>
    )
}

function PctField({ label, hint, value, onChange }) {
    return (
        <Field label={label} hint={hint} value={Math.round(value * 10000) / 100}
            onChange={v => onChange(v / 100)} suffix="%" step={0.1} min={0} max={100} />
    )
}

/* ── Dramatic Toggle ─────────────────────────────────────────── */
function Toggle({ label, hint, checked, onChange, danger }) {
    const activeColor = danger ? '--danger' : '--up'
    return (
        <div className="flex items-start justify-between gap-4 pt-4">
            <div>
                <div className="font-mono text-xs font-bold text-[rgb(var(--text))]">{label}</div>
                {hint && <div className="font-mono text-[10px] text-[rgb(var(--muted))] mt-0.5">{hint}</div>}
            </div>
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                onClick={() => onChange(!checked)}
                className="relative shrink-0 h-7 w-14 transition-all"
                style={{
                    borderRadius: '4px',
                    backgroundColor: checked ? `rgba(var(${activeColor}), 0.2)` : 'rgba(var(--surface), 0.6)',
                    border: `2px solid ${checked ? `rgb(var(${activeColor}))` : 'rgba(var(--grid), 0.3)'}`,
                    boxShadow: checked ? `0 0 8px rgba(var(${activeColor}), 0.3)` : 'none',
                }}
            >
                <span
                    className="absolute top-0.5 h-5 w-5 transition-transform"
                    style={{
                        borderRadius: '2px',
                        left: '2px',
                        backgroundColor: checked ? `rgb(var(${activeColor}))` : 'rgb(var(--muted))',
                        transform: checked ? 'translateX(26px)' : 'translateX(0)',
                    }}
                />
            </button>
        </div>
    )
}

/* ── Save Bar ────────────────────────────────────────────────── */
function SaveBar({ saving, saved, dirty, onSave }) {
    return (
        <div className="flex items-center gap-3 pt-3">
            <button
                type="button"
                onClick={onSave}
                disabled={saving || !dirty}
                className="flex items-center gap-2 border-2 border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.1)] px-5 py-2.5 font-mono text-xs font-bold uppercase tracking-widest text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.2)] disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ borderRadius: '3px' }}
            >
                {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? 'SAVING...' : 'SAVE'}
            </button>
            {dirty && (
                <span className="flex items-center gap-1.5 font-mono text-[10px] text-[rgb(var(--warn))]">
                    <span className="h-1.5 w-1.5 rounded-full bg-[rgb(var(--warn))]" />UNSAVED
                </span>
            )}
            {saved && (
                <span className="flex items-center gap-1.5 font-mono text-[10px] text-[rgb(var(--up))]">
                    <span className="h-1.5 w-1.5 rounded-full bg-[rgb(var(--up))]" />SAVED
                </span>
            )}
        </div>
    )
}

/* ── Hooks ────────────────────────────────────────────────────── */
function useSection(path) {
    const [data, setData] = useState(null)
    const [error, setError] = useState(null)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [dirty, setDirty] = useState(false)

    const load = useCallback(async () => {
        try { setData(await apiFetch(path)); setError(null) }
        catch (e) { setError(e.message) }
    }, [path])

    useEffect(() => { load() }, [load])

    const set = useCallback((updater) => {
        setData(prev => typeof updater === 'function' ? updater(prev) : { ...prev, ...updater })
        setDirty(true); setSaved(false)
    }, [])

    const save = useCallback(async (payload) => {
        setSaving(true)
        try {
            const updated = await apiFetch(path, { method: 'PUT', body: JSON.stringify(payload) })
            setData(updated); setDirty(false); setSaved(true)
            setTimeout(() => setSaved(false), 4000)
        } catch (e) { setError(e.message) }
        finally { setSaving(false) }
    }, [path])

    return { data, error, saving, saved, dirty, set, save, refresh: load }
}

/* ── Watchlist Section ───────────────────────────────────────── */
function WatchlistSection() {
    const [data, setData] = useState(null)
    const [error, setError] = useState(null)
    const [saving, setSaving] = useState(false)
    const [saved, setSaved] = useState(false)
    const [dirty, setDirty] = useState(false)
    const [newSymbol, setNewSymbol] = useState('')
    const [addError, setAddError] = useState('')

    const load = useCallback(async () => {
        try {
            const res = await authFetch(`${getApiBase()}/api/settings/watchlist`)
            if (!res.ok) throw new Error(`HTTP ${res.status}`)
            setData(await res.json()); setError(null)
        } catch (e) { setError(e.message) }
    }, [])

    useEffect(() => { load() }, [load])

    function addSymbol() {
        const sym = newSymbol.trim().toUpperCase()
        if (!sym) return
        if (!/^\d{4}$/.test(sym) && !/^[A-Z]{1,5}$/.test(sym)) { setAddError('Invalid format (4-digit TW or US alpha)'); return }
        if (data.manual_watchlist.includes(sym)) { setAddError(`${sym} already in list`); return }
        setData(d => ({ ...d, manual_watchlist: [...d.manual_watchlist, sym] }))
        setNewSymbol(''); setAddError(''); setDirty(true); setSaved(false)
    }

    function removeSymbol(sym) {
        setData(d => ({ ...d, manual_watchlist: d.manual_watchlist.filter(s => s !== sym) }))
        setDirty(true); setSaved(false)
    }

    function pinSymbol(sym) {
        if (data.manual_watchlist.includes(sym)) return
        setData(d => ({ ...d, manual_watchlist: [...d.manual_watchlist, sym] }))
        setDirty(true); setSaved(false)
    }

    async function save() {
        setSaving(true)
        try {
            const res = await authFetch(`${getApiBase()}/api/settings/watchlist`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ manual_watchlist: data.manual_watchlist }),
            })
            if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.detail || `HTTP ${res.status}`) }
            const updated = await res.json()
            setData(updated); setDirty(false); setSaved(true)
            setTimeout(() => setSaved(false), 4000)
        } catch (e) { setError(e.message) }
        finally { setSaving(false) }
    }

    return (
        <Section title="WATCHLIST" icon={List} accentVar="--info" defaultOpen={true}>
            {error && (
                <div className="flex items-center gap-2 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] px-3 py-2 mt-4 font-mono text-xs text-[rgb(var(--danger))]" style={{ borderRadius: '2px' }}>
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />{error}
                </div>
            )}
            {!data ? (
                <div className="flex items-center gap-2 font-mono text-xs text-[rgb(var(--muted))] py-4">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />LOADING...
                </div>
            ) : (
                <>
                    {/* Manual Watchlist */}
                    <div className="pt-4">
                        <div className="flex items-center gap-2 mb-2">
                            <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                                MY WATCHLIST
                            </span>
                            <span className="ml-auto font-mono text-[10px] text-[rgb(var(--muted))]">{data.manual_watchlist.length}</span>
                        </div>
                        <div className="flex flex-wrap gap-2 mb-3">
                            {data.manual_watchlist.map(sym => (
                                <span key={sym} className="flex items-center gap-1 border border-[rgba(var(--info),0.3)] bg-[rgba(var(--info),0.08)] px-2.5 py-1 font-mono text-xs font-bold text-[rgb(var(--info))]"
                                      style={{ borderRadius: '3px' }}
                                >
                                    {sym}
                                    <button onClick={() => removeSymbol(sym)}
                                        className="text-[rgb(var(--muted))] hover:text-[rgb(var(--danger))] transition-colors ml-0.5"
                                    ><X className="h-3 w-3" /></button>
                                </span>
                            ))}
                        </div>
                        <div className="flex items-center gap-2">
                            <input type="text" placeholder="Add symbol (e.g. 2330)"
                                value={newSymbol}
                                onChange={e => { setNewSymbol(e.target.value); setAddError('') }}
                                onKeyDown={e => e.key === 'Enter' && addSymbol()}
                                className="flex-1 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))] placeholder-[rgb(var(--muted))] outline-none focus:border-[rgba(var(--accent),0.5)]"
                                style={{ borderRadius: '3px' }}
                            />
                            <button onClick={addSymbol}
                                className="flex items-center gap-1.5 border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-3 py-2 font-mono text-xs font-bold text-[rgb(var(--accent))]"
                                style={{ borderRadius: '3px' }}
                            ><Plus className="h-4 w-4" />ADD</button>
                        </div>
                        {addError && <p className="mt-1 font-mono text-[10px] text-[rgb(var(--danger))]">{addError}</p>}
                    </div>

                    <div className="my-4 border-t border-[rgba(var(--grid),0.15)]" />

                    {/* System Candidates */}
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <Zap className="h-3.5 w-3.5" style={{ color: 'rgb(var(--warn))' }} />
                            <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                                SYSTEM CANDIDATES
                            </span>
                            <button onClick={load} className="ml-auto text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]">
                                <RefreshCw className="h-3 w-3" />
                            </button>
                        </div>
                        {data.system_candidates && data.system_candidates.length > 0 ? (
                            <div className="space-y-2">
                                {data.system_candidates.map(c => (
                                    <div key={`${c.symbol}-${c.label}`}
                                        className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] px-4 py-3 space-y-2"
                                        style={{ borderRadius: '2px' }}
                                    >
                                        <div className="flex items-center gap-2">
                                            <span className="font-mono text-sm font-bold text-[rgb(var(--text))]">{c.symbol}</span>
                                            {c.name && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{c.name}</span>}
                                            <span className="border border-[rgba(var(--grid),0.3)] px-1.5 py-0.5 font-mono text-[9px] font-bold text-[rgb(var(--muted))]"
                                                  style={{ borderRadius: '2px' }}>{c.label || '--'}</span>
                                            <span className="ml-auto font-mono text-[9px] text-[rgb(var(--muted))]">EXP {c.expires_at}</span>
                                        </div>
                                        {/* Score bar */}
                                        <div className="flex items-center gap-2">
                                            <span className="font-mono text-[9px] text-[rgb(var(--muted))] w-8 shrink-0">SCORE</span>
                                            <div className="flex-1 h-1.5 bg-[rgba(var(--grid),0.15)] overflow-hidden" style={{ borderRadius: '1px' }}>
                                                <div className="h-full bg-[rgb(var(--warn))]" style={{ width: `${Math.min((c.score || 0) * 100, 100)}%` }} />
                                            </div>
                                            <span className="font-mono text-[9px] tabular-nums text-[rgb(var(--muted))] w-8 text-right">{(c.score || 0).toFixed(2)}</span>
                                        </div>
                                        {c.reasons && c.reasons.length > 0 && (
                                            <div className="flex flex-wrap gap-1">
                                                {c.reasons.map((r, i) => (
                                                    <span key={i} className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-1.5 py-0.5 font-mono text-[9px] text-[rgb(var(--muted))]"
                                                          style={{ borderRadius: '2px' }}>{r}</span>
                                                ))}
                                            </div>
                                        )}
                                        {c.llm_filtered === false && (
                                            <div className="flex items-center gap-1 font-mono text-[9px] text-[rgb(var(--warn))]">
                                                <AlertCircle className="h-3 w-3 shrink-0" />RULE-ONLY (NO AI VERIFICATION)
                                            </div>
                                        )}
                                        {!data.manual_watchlist.includes(c.symbol) && (
                                            <button onClick={() => pinSymbol(c.symbol)}
                                                className="flex items-center gap-1 font-mono text-[9px] font-bold text-[rgb(var(--accent))] hover:underline"
                                            ><Plus className="h-3 w-3" />PIN TO WATCHLIST</button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <span className="font-mono text-[10px] italic text-[rgb(var(--muted))]">No system candidates yet</span>
                        )}
                    </div>

                    <div className="my-4 border-t border-[rgba(var(--grid),0.15)]" />

                    {/* Active Symbols */}
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">
                                ACTIVE MONITORING
                            </span>
                            <span className="ml-auto font-mono text-[10px] text-[rgb(var(--muted))]">{data.active_symbols ? data.active_symbols.length : 0}</span>
                        </div>
                        <div className="flex flex-wrap gap-2 min-h-[2rem]">
                            {data.active_symbols && data.active_symbols.length > 0 ? (
                                data.active_symbols.map(sym => {
                                    const isManual = data.manual_watchlist.includes(sym)
                                    const isSystem = data.system_candidates && data.system_candidates.some(c => c.symbol === sym)
                                    const borderVar = isManual && isSystem ? '--up' : isManual ? '--info' : '--warn'
                                    return (
                                        <span key={sym}
                                            className="flex items-center gap-1 border px-2.5 py-1 font-mono text-xs font-bold"
                                            style={{
                                                borderRadius: '3px',
                                                borderColor: `rgba(var(${borderVar}), 0.3)`,
                                                backgroundColor: `rgba(var(${borderVar}), 0.08)`,
                                                color: `rgb(var(${borderVar}))`,
                                            }}
                                        >{sym}</span>
                                    )
                                })
                            ) : (
                                <span className="font-mono text-[10px] italic text-[rgb(var(--muted))]">No active symbols</span>
                            )}
                        </div>
                    </div>

                    <SaveBar saving={saving} saved={saved} dirty={dirty} onSave={save} />
                </>
            )}
        </Section>
    )
}

/* ── Main Page ─────────────────────────────────────────────── */
export default function SettingsPage() {
    const capital = useSection('/api/settings/capital')
    const sentinel = useSection('/api/settings/sentinel')
    const limits = useSection('/api/settings/position-limits')
    const auth = useSection('/api/settings/authority')

    const [authorityInput, setAuthorityInput] = useState({ level: 1, reason: '' })
    const [authSaving, setAuthSaving] = useState(false)
    const [authSaved, setAuthSaved] = useState(false)
    const [authError, setAuthError] = useState(null)

    const errors = [capital.error, sentinel.error, limits.error, auth.error].filter(Boolean)

    async function saveAuthority() {
        setAuthSaving(true); setAuthError(null)
        try {
            await apiFetch('/api/settings/authority', { method: 'PUT', body: JSON.stringify(authorityInput) })
            setAuthSaved(true); setTimeout(() => setAuthSaved(false), 4000)
            setAuthorityInput(p => ({ ...p, reason: '' }))
            auth.refresh()
        } catch (e) { setAuthError(e.message) }
        finally { setAuthSaving(false) }
    }

    const loading = !capital.data && !sentinel.data && !limits.data

    return (
        <div className="space-y-4 max-w-5xl pb-20 lg:pb-4">
            {/* Header */}
            <div>
                <h1 className="font-mono text-xl font-bold tracking-tight text-[rgb(var(--text))]">SYSTEM CONFIG</h1>
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">
                    SETTINGS TAKE EFFECT IMMEDIATELY -- NO RESTART REQUIRED
                </p>
            </div>

            {errors.map((e, i) => (
                <div key={i} className="flex items-center gap-3 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] px-4 py-3 font-mono text-xs text-[rgb(var(--danger))]" style={{ borderRadius: '2px' }}>
                    <AlertCircle className="h-4 w-4 shrink-0" />{e}
                </div>
            ))}

            {loading && (
                <div className="flex items-center gap-3 font-mono text-xs text-[rgb(var(--muted))] py-8">
                    <RefreshCw className="h-4 w-4 animate-spin" />LOADING...
                </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-start">
                {/* Watchlist */}
                <WatchlistSection />

                {/* Capital */}
                {capital.data && (
                    <Section title="CAPITAL LIMITS" icon={DollarSign} accentVar="--up">
                        <Field label="TOTAL CAPITAL" hint="Maximum capital AI can deploy"
                            prefix="TWD" value={capital.data.total_capital_twd} step={50000}
                            onChange={v => capital.set({ total_capital_twd: v })} />
                        <Field label="MAX SINGLE POSITION"
                            hint="Maximum amount for any single position"
                            type="number" prefix="TWD" step={10000}
                            value={Math.round(capital.data.total_capital_twd * capital.data.max_single_position_pct)}
                            onChange={v => {
                                if (capital.data.total_capital_twd > 0) capital.set({ max_single_position_pct: v / capital.data.total_capital_twd })
                            }} />
                        <Field label="MONTHLY API BUDGET" hint="Stop trading when reached"
                            prefix="TWD" value={capital.data.monthly_api_budget_twd} step={500}
                            onChange={v => capital.set({ monthly_api_budget_twd: v })} />
                        <PctField label="DEFAULT STOP LOSS" hint="Global default when per-stock not set"
                            value={capital.data.default_stop_loss_pct}
                            onChange={v => capital.set({ default_stop_loss_pct: v })} />
                        <PctField label="DEFAULT TAKE PROFIT" hint="Global default when per-stock not set"
                            value={capital.data.default_take_profit_pct}
                            onChange={v => capital.set({ default_take_profit_pct: v })} />
                        <Field label="DAILY LOSS CIRCUIT BREAKER" hint="Switch to defense mode when exceeded"
                            prefix="TWD" value={capital.data.daily_loss_limit_twd} step={1000}
                            onChange={v => capital.set({ daily_loss_limit_twd: v })} />
                        <Field label="MONTHLY LOSS CIRCUIT BREAKER" hint="Manual unlock required"
                            prefix="TWD" value={capital.data.monthly_loss_limit_twd} step={5000}
                            onChange={v => capital.set({ monthly_loss_limit_twd: v })} />
                        <SaveBar saving={capital.saving} saved={capital.saved} dirty={capital.dirty}
                            onSave={() => capital.save(capital.data)} />
                    </Section>
                )}

                {/* Position Limits */}
                {limits.data && (
                    <Section title="POSITION LIMITS" icon={Layers} accentVar="--info" defaultOpen={false}>
                        <p className="pt-4 font-mono text-[10px] text-[rgb(var(--muted))]">
                            HIGHER LEVEL = MORE AUTHORITY. L0 = NO TRADING. L3 = MAX AUTOMATION.
                        </p>
                        {[1, 2, 3].map(lv => (
                            <div key={lv} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.3)] px-4 py-3 space-y-2"
                                 style={{ borderRadius: '2px' }}
                            >
                                <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">LEVEL {lv}</div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    <PctField label="MAX RISK (% NAV)"
                                        value={limits.data[`level_${lv}_max_risk_pct`]}
                                        onChange={v => limits.set({ [`level_${lv}_max_risk_pct`]: v })} />
                                    <PctField label="MAX POSITION (% NAV)"
                                        value={limits.data[`level_${lv}_max_position_pct`]}
                                        onChange={v => limits.set({ [`level_${lv}_max_position_pct`]: v })} />
                                </div>
                            </div>
                        ))}
                        <SaveBar saving={limits.saving} saved={limits.saved} dirty={limits.dirty}
                            onSave={() => limits.save(limits.data)} />
                    </Section>
                )}

                {/* Sentinel */}
                {sentinel.data && (
                    <Section title="SENTINEL CIRCUIT BREAKERS" icon={Shield} accentVar="--warn" defaultOpen={false}>
                        <Toggle label="API BUDGET HALT" hint="Pause when monthly API budget exceeded" danger
                            checked={sentinel.data.budget_halt_enabled}
                            onChange={v => sentinel.set({ budget_halt_enabled: v })} />
                        <Toggle label="DRAWDOWN HALT" hint="Pause trading when daily loss exceeds limit" danger
                            checked={sentinel.data.drawdown_suspended_enabled}
                            onChange={v => sentinel.set({ drawdown_suspended_enabled: v })} />
                        <Toggle label="REDUCE-ONLY MODE" hint="Only allow closing positions after halt"
                            checked={sentinel.data.reduce_only_enabled}
                            onChange={v => sentinel.set({ reduce_only_enabled: v })} />
                        <Toggle label="BROKER DISCONNECT HALT" hint="Pause when Shioaji connection lost" danger
                            checked={sentinel.data.broker_disconnected_enabled}
                            onChange={v => sentinel.set({ broker_disconnected_enabled: v })} />
                        <Toggle label="DB LATENCY HALT" hint="Alert when DB write p99 exceeds threshold"
                            checked={sentinel.data.db_latency_enabled}
                            onChange={v => sentinel.set({ db_latency_enabled: v })} />
                        <Field label="DB LATENCY THRESHOLD (ms)"
                            value={sentinel.data.max_db_write_p99_ms} step={50} min={50}
                            onChange={v => sentinel.set({ max_db_write_p99_ms: v })} />
                        <Field label="HEALTH CHECK INTERVAL (s)"
                            value={sentinel.data.health_check_interval_seconds} step={5} min={5}
                            onChange={v => sentinel.set({ health_check_interval_seconds: v })} />
                        <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                            onSave={() => sentinel.save(sentinel.data)} />
                    </Section>
                )}

                {/* Telegram */}
                {sentinel.data && (
                    <Section title="TELEGRAM NOTIFICATIONS" icon={Bell} accentVar="--info" defaultOpen={false}>
                        <Field label="TELEGRAM CHAT ID" hint="Channel or group ID (e.g. -1003772422881)"
                            type="text" value={sentinel.data.telegram_chat_id || ''}
                            onChange={v => sentinel.set({ telegram_chat_id: v })} />
                        <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                            onSave={() => sentinel.save(sentinel.data)} />
                    </Section>
                )}

                {/* Authority Level -- dramatic styling */}
                <Section title="TRADING AUTHORITY" icon={Lock} accentVar="--danger" defaultOpen={false}>
                    {auth.data && (
                        <div className="border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--surface),0.3)] px-4 py-3 mt-4 font-mono text-xs space-y-1"
                             style={{ borderRadius: '2px' }}
                        >
                            <div className="flex justify-between">
                                <span className="text-[rgb(var(--muted))]">CURRENT LEVEL</span>
                                <span className="font-bold text-[rgb(var(--text))]">LEVEL {auth.data.level}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-[rgb(var(--muted))]">REASON</span>
                                <span className="text-[rgb(var(--text))]">{auth.data.reason}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-[rgb(var(--muted))]">EFFECTIVE</span>
                                <span className="text-[rgb(var(--muted))] text-[10px]">{auth.data.effective_from?.replace('T', ' ').slice(0, 19)}</span>
                            </div>
                        </div>
                    )}
                    <div className="space-y-3">
                        <div className="flex flex-col gap-1 pt-4">
                            <label className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">NEW LEVEL</label>
                            <select
                                value={authorityInput.level}
                                onChange={e => setAuthorityInput(p => ({ ...p, level: Number(e.target.value) }))}
                                className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-sm text-[rgb(var(--text))] outline-none focus:border-[rgba(var(--accent),0.5)]"
                                style={{ borderRadius: '3px' }}
                            >
                                <option value={0}>Level 0 -- NO TRADING</option>
                                <option value={1}>Level 1 -- ULTRA CONSERVATIVE (1% NAV)</option>
                                <option value={2}>Level 2 -- CONSERVATIVE (5% NAV)</option>
                                <option value={3}>Level 3 -- STANDARD (10% NAV)</option>
                            </select>
                        </div>
                        <Field label="REASON (REQUIRED)" type="text"
                            value={authorityInput.reason}
                            onChange={v => setAuthorityInput(p => ({ ...p, reason: v }))} />
                    </div>
                    {authError && <div className="font-mono text-xs text-[rgb(var(--danger))]">{authError}</div>}
                    <SaveBar saving={authSaving} saved={authSaved} dirty={!!authorityInput.reason}
                        onSave={saveAuthority} />
                </Section>
            </div>
        </div>
    )
}
