/**
 * Settings.jsx -- Control Panel Layout
 *
 * Complete layout restructure:
 *   Top: DANGER ZONE (red border, dark bg) -- emergency stop, trading mode toggle, kill switches
 *   Bottom: Configuration -- system parameters as monospace key:value pairs
 *   Split visually into danger/safe zones
 *
 * All data fetching and state management preserved from original.
 */

import React, { useCallback, useEffect, useState } from 'react'
import {
    DollarSign, Shield, TrendingDown, CheckCircle, AlertCircle,
    Save, RefreshCw, Lock, Bell, Layers, ChevronDown, ChevronUp,
    List, Plus, X, Zap, AlertTriangle, Power, Skull
} from 'lucide-react'
import { formatComma } from '../lib/format'
import { authFetch, getApiBase } from '../lib/auth'

/* ── API helper ──────────────────────────────────────────── */
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

/* ── Dramatic Toggle ─────────────────────────────────────── */
function DangerSwitch({ label, hint, checked, onChange }) {
    return (
        <div className="flex items-center justify-between gap-4 py-3">
            <div className="flex-1">
                <div className="font-mono text-xs font-bold text-[rgb(var(--text))]">{label}</div>
                {hint && <div className="font-mono text-[10px] text-[rgb(var(--muted))] mt-0.5">{hint}</div>}
            </div>
            <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
                className="relative shrink-0 h-8 w-16 transition-all"
                style={{
                    borderRadius: '3px',
                    backgroundColor: checked ? 'rgba(var(--danger),0.25)' : 'rgba(var(--surface),0.6)',
                    border: `2px solid ${checked ? 'rgb(var(--danger))' : 'rgba(var(--grid),0.3)'}`,
                    boxShadow: checked ? '0 0 12px rgba(var(--danger),0.4)' : 'none',
                }}>
                <span className="absolute top-1 h-5 w-5 transition-transform font-mono text-[8px] font-bold flex items-center justify-center"
                    style={{
                        borderRadius: '2px',
                        left: '3px',
                        backgroundColor: checked ? 'rgb(var(--danger))' : 'rgb(var(--muted))',
                        transform: checked ? 'translateX(30px)' : 'translateX(0)',
                        color: checked ? 'rgb(var(--bg))' : 'rgb(var(--bg))',
                    }}>
                    {checked ? 'ON' : 'OFF'}
                </span>
            </button>
        </div>
    )
}

function SafeToggle({ label, hint, checked, onChange }) {
    return (
        <div className="flex items-center justify-between gap-4 py-3">
            <div className="flex-1">
                <div className="font-mono text-xs font-bold text-[rgb(var(--text))]">{label}</div>
                {hint && <div className="font-mono text-[10px] text-[rgb(var(--muted))] mt-0.5">{hint}</div>}
            </div>
            <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
                className="relative shrink-0 h-7 w-14 transition-all"
                style={{
                    borderRadius: '3px',
                    backgroundColor: checked ? 'rgba(var(--up),0.2)' : 'rgba(var(--surface),0.6)',
                    border: `2px solid ${checked ? 'rgb(var(--up))' : 'rgba(var(--grid),0.3)'}`,
                }}>
                <span className="absolute top-0.5 h-5 w-5 transition-transform"
                    style={{
                        borderRadius: '2px',
                        left: '2px',
                        backgroundColor: checked ? 'rgb(var(--up))' : 'rgb(var(--muted))',
                        transform: checked ? 'translateX(26px)' : 'translateX(0)',
                    }} />
            </button>
        </div>
    )
}

/* ── Inline Edit Field ────────────────────────────────────── */
function InlineField({ label, value, onChange, prefix, suffix, type = 'number', hint, step = 1, min, max }) {
    const [editing, setEditing] = useState(false)
    const [editVal, setEditVal] = useState(value)

    useEffect(() => { setEditVal(value) }, [value])

    function commit() {
        setEditing(false)
        const v = type === 'number' ? Number(editVal) : editVal
        if (v !== value) onChange(v)
    }

    return (
        <div className="flex items-center justify-between gap-4 py-2 border-b border-[rgba(var(--grid),0.08)] last:border-0 group">
            <div>
                <span className="font-mono text-[10px] uppercase tracking-widest text-[rgb(var(--muted))]">{label}</span>
                {hint && <div className="font-mono text-[9px] text-[rgb(var(--muted))] mt-0.5">{hint}</div>}
            </div>
            {editing ? (
                <div className="flex items-center gap-1">
                    {prefix && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{prefix}</span>}
                    <input type={type} value={editVal} step={step} min={min} max={max}
                        onChange={e => setEditVal(type === 'number' ? Number(e.target.value) : e.target.value)}
                        onBlur={commit}
                        onKeyDown={e => e.key === 'Enter' && commit()}
                        autoFocus
                        className="w-28 border border-[rgba(var(--accent),0.5)] bg-[rgba(var(--surface),0.4)] px-2 py-1 font-mono text-xs tabular-nums text-[rgb(var(--text))] outline-none text-right"
                        style={{ borderRadius: '2px' }} />
                    {suffix && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{suffix}</span>}
                </div>
            ) : (
                <button onClick={() => setEditing(true)}
                    className="flex items-center gap-1 font-mono text-xs tabular-nums text-[rgb(var(--text))] hover:text-[rgb(var(--accent))] cursor-text transition-colors">
                    {prefix && <span className="text-[rgb(var(--muted))]">{prefix}</span>}
                    <span className="font-bold">{typeof value === 'number' ? formatComma(value) : value}</span>
                    {suffix && <span className="text-[rgb(var(--muted))]">{suffix}</span>}
                </button>
            )}
        </div>
    )
}

function InlinePctField({ label, hint, value, onChange }) {
    return (
        <InlineField label={label} hint={hint} value={Math.round(value * 10000) / 100}
            onChange={v => onChange(v / 100)} suffix="%" step={0.1} min={0} max={100} />
    )
}

/* ── Save Bar ────────────────────────────────────────────── */
function SaveBar({ saving, saved, dirty, onSave }) {
    return (
        <div className="flex items-center gap-3 pt-3">
            <button type="button" onClick={onSave} disabled={saving || !dirty}
                className="flex items-center gap-2 border-2 border-[rgb(var(--accent))] bg-[rgba(var(--accent),0.1)] px-5 py-2 font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.2)] disabled:opacity-40"
                style={{ borderRadius: '3px' }}>
                {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                {saving ? 'SAVING...' : 'SAVE'}
            </button>
            {dirty && <span className="flex items-center gap-1.5 font-mono text-[10px] text-[rgb(var(--warn))]"><span className="h-1.5 w-1.5 rounded-full bg-[rgb(var(--warn))]" />UNSAVED</span>}
            {saved && <span className="flex items-center gap-1.5 font-mono text-[10px] text-[rgb(var(--up))]"><span className="h-1.5 w-1.5 rounded-full bg-[rgb(var(--up))]" />SAVED</span>}
        </div>
    )
}

/* ── Hooks ───────────────────────────────────────────────── */
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

/* ── Watchlist Section ───────────────────────────────────── */
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

    if (!data) return <div className="flex items-center gap-2 font-mono text-xs text-[rgb(var(--muted))] py-4"><RefreshCw className="h-3.5 w-3.5 animate-spin" />LOADING...</div>

    return (
        <div className="space-y-4">
            {error && (
                <div className="flex items-center gap-2 border-l-2 border-l-[rgb(var(--danger))] bg-[rgba(var(--danger),0.05)] px-3 py-2 font-mono text-xs text-[rgb(var(--danger))]" style={{ borderRadius: '2px' }}>
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />{error}
                </div>
            )}

            {/* My Watchlist */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">MY WATCHLIST</span>
                    <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{data.manual_watchlist.length}</span>
                </div>
                <div className="flex flex-wrap gap-2 mb-3">
                    {data.manual_watchlist.map(sym => (
                        <span key={sym} className="flex items-center gap-1 border border-[rgba(var(--info),0.3)] bg-[rgba(var(--info),0.08)] px-2.5 py-1 font-mono text-xs font-bold text-[rgb(var(--info))]" style={{ borderRadius: '3px' }}>
                            {sym}
                            <button onClick={() => removeSymbol(sym)} className="text-[rgb(var(--muted))] hover:text-[rgb(var(--danger))] transition-colors ml-0.5"><X className="h-3 w-3" /></button>
                        </span>
                    ))}
                </div>
                <div className="flex items-center gap-2">
                    <input type="text" placeholder="Add symbol (e.g. 2330)" value={newSymbol}
                        onChange={e => { setNewSymbol(e.target.value); setAddError('') }}
                        onKeyDown={e => e.key === 'Enter' && addSymbol()}
                        className="flex-1 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.3)] px-3 py-2 font-mono text-xs text-[rgb(var(--text))] placeholder-[rgb(var(--muted))] outline-none focus:border-[rgba(var(--accent),0.5)]"
                        style={{ borderRadius: '2px' }} />
                    <button onClick={addSymbol}
                        className="flex items-center gap-1.5 border border-[rgba(var(--accent),0.4)] bg-[rgba(var(--accent),0.08)] px-3 py-2 font-mono text-[10px] font-bold text-[rgb(var(--accent))]"
                        style={{ borderRadius: '2px' }}><Plus className="h-3.5 w-3.5" />ADD</button>
                </div>
                {addError && <p className="mt-1 font-mono text-[10px] text-[rgb(var(--danger))]">{addError}</p>}
            </div>

            {/* System Candidates */}
            {data.system_candidates && data.system_candidates.length > 0 && (
                <div>
                    <div className="flex items-center gap-2 mb-2">
                        <Zap className="h-3.5 w-3.5" style={{ color: 'rgb(var(--warn))' }} />
                        <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">SYSTEM CANDIDATES</span>
                        <button onClick={load} className="ml-auto text-[rgb(var(--muted))] hover:text-[rgb(var(--text))]"><RefreshCw className="h-3 w-3" /></button>
                    </div>
                    <div className="space-y-2">
                        {data.system_candidates.map(c => (
                            <div key={`${c.symbol}-${c.label}`} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] px-4 py-3 space-y-2" style={{ borderRadius: '2px' }}>
                                <div className="flex items-center gap-2">
                                    <span className="font-mono text-sm font-bold text-[rgb(var(--text))]">{c.symbol}</span>
                                    {c.name && <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{c.name}</span>}
                                    <span className="border border-[rgba(var(--grid),0.3)] px-1.5 py-0.5 font-mono text-[9px] font-bold text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>{c.label || '--'}</span>
                                    <span className="ml-auto font-mono text-[9px] text-[rgb(var(--muted))]">EXP {c.expires_at}</span>
                                </div>
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
                                            <span key={i} className="border border-[rgba(var(--grid),0.2)] bg-[rgba(var(--surface),0.3)] px-1.5 py-0.5 font-mono text-[9px] text-[rgb(var(--muted))]" style={{ borderRadius: '2px' }}>{r}</span>
                                        ))}
                                    </div>
                                )}
                                {c.llm_filtered === false && (
                                    <div className="flex items-center gap-1 font-mono text-[9px] text-[rgb(var(--warn))]"><AlertCircle className="h-3 w-3 shrink-0" />RULE-ONLY (NO AI VERIFICATION)</div>
                                )}
                                {!data.manual_watchlist.includes(c.symbol) && (
                                    <button onClick={() => pinSymbol(c.symbol)} className="flex items-center gap-1 font-mono text-[9px] font-bold text-[rgb(var(--accent))] hover:underline"><Plus className="h-3 w-3" />PIN TO WATCHLIST</button>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Active Symbols */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))]">ACTIVE MONITORING</span>
                    <span className="font-mono text-[10px] text-[rgb(var(--muted))]">{data.active_symbols ? data.active_symbols.length : 0}</span>
                </div>
                <div className="flex flex-wrap gap-2 min-h-[2rem]">
                    {data.active_symbols && data.active_symbols.length > 0 ? (
                        data.active_symbols.map(sym => {
                            const isManual = data.manual_watchlist.includes(sym)
                            const isSystem = data.system_candidates && data.system_candidates.some(c => c.symbol === sym)
                            const borderVar = isManual && isSystem ? '--up' : isManual ? '--info' : '--warn'
                            return (
                                <span key={sym} className="flex items-center gap-1 border px-2.5 py-1 font-mono text-xs font-bold"
                                    style={{ borderRadius: '3px', borderColor: `rgba(var(${borderVar}),0.3)`, backgroundColor: `rgba(var(${borderVar}),0.08)`, color: `rgb(var(${borderVar}))` }}>
                                    {sym}
                                </span>
                            )
                        })
                    ) : <span className="font-mono text-[10px] italic text-[rgb(var(--muted))]">No active symbols</span>}
                </div>
            </div>

            <SaveBar saving={saving} saved={saved} dirty={dirty} onSave={save} />
        </div>
    )
}

/* ══════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════ */
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
        <div className="space-y-6 max-w-6xl pb-20 lg:pb-4">

            {/* Errors */}
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

            {/* ══════════════════════════════════════════════════════════
                DANGER ZONE -- red border, prominent controls
                ══════════════════════════════════════════════════════════ */}
            <div className="border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.03)] overflow-hidden"
                 style={{ borderRadius: '4px', boxShadow: '0 0 24px rgba(var(--danger),0.08)' }}>
                {/* Danger header */}
                <div className="flex items-center gap-3 bg-[rgba(var(--danger),0.08)] px-5 py-3 border-b border-[rgba(var(--danger),0.2)]">
                    <Skull className="h-5 w-5 text-[rgb(var(--danger))]" />
                    <span className="font-mono text-xs font-black uppercase tracking-widest text-[rgb(var(--danger))]">DANGER ZONE</span>
                    <span className="font-mono text-[10px] text-[rgb(var(--danger))] opacity-60">IRREVERSIBLE ACTIONS</span>
                </div>

                <div className="p-5 space-y-5">
                    {/* Trading Authority -- dramatic display */}
                    {auth.data && (
                        <div className="flex flex-col sm:flex-row gap-4">
                            {/* Current level -- big display */}
                            <div className="flex-shrink-0 border-2 border-[rgba(var(--danger),0.4)] bg-[rgba(var(--danger),0.05)] px-6 py-4 text-center" style={{ borderRadius: '3px' }}>
                                <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))]">AUTHORITY</div>
                                <div className="mt-2 font-mono text-5xl font-black tabular-nums text-[rgb(var(--danger))]"
                                     style={{ filter: 'drop-shadow(0 0 8px rgba(var(--danger),0.3))', lineHeight: 1 }}>
                                    L{auth.data.level}
                                </div>
                                <div className="mt-2 font-mono text-[10px] text-[rgb(var(--muted))]">{auth.data.reason}</div>
                            </div>

                            {/* Change authority */}
                            <div className="flex-1 space-y-3">
                                <div className="font-mono text-[9px] uppercase tracking-widest text-[rgb(var(--muted))]">CHANGE TRADING AUTHORITY</div>
                                <select value={authorityInput.level}
                                    onChange={e => setAuthorityInput(p => ({ ...p, level: Number(e.target.value) }))}
                                    className="w-full border border-[rgba(var(--danger),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-xs text-[rgb(var(--text))] outline-none"
                                    style={{ borderRadius: '2px' }}>
                                    <option value={0}>Level 0 -- NO TRADING</option>
                                    <option value={1}>Level 1 -- ULTRA CONSERVATIVE (1% NAV)</option>
                                    <option value={2}>Level 2 -- CONSERVATIVE (5% NAV)</option>
                                    <option value={3}>Level 3 -- STANDARD (10% NAV)</option>
                                </select>
                                <input type="text" placeholder="REASON (REQUIRED)" value={authorityInput.reason}
                                    onChange={e => setAuthorityInput(p => ({ ...p, reason: e.target.value }))}
                                    className="w-full border border-[rgba(var(--danger),0.3)] bg-[rgba(var(--surface),0.4)] px-3 py-2 font-mono text-xs text-[rgb(var(--text))] placeholder-[rgb(var(--muted))] outline-none"
                                    style={{ borderRadius: '2px' }} />
                                {authError && <div className="font-mono text-[10px] text-[rgb(var(--danger))]">{authError}</div>}
                                <button onClick={saveAuthority} disabled={authSaving || !authorityInput.reason}
                                    className="w-full border-2 border-[rgb(var(--danger))] bg-[rgba(var(--danger),0.1)] py-3 font-mono text-xs font-bold uppercase tracking-widest text-[rgb(var(--danger))] transition hover:bg-[rgba(var(--danger),0.2)] disabled:opacity-40"
                                    style={{ borderRadius: '3px' }}>
                                    {authSaving ? 'SAVING...' : 'APPLY AUTHORITY CHANGE'}
                                </button>
                                {authSaved && <span className="font-mono text-[10px] text-[rgb(var(--up))]">Authority updated</span>}
                            </div>
                        </div>
                    )}

                    {/* Sentinel kill switches */}
                    {sentinel.data && (
                        <div>
                            <div className="font-mono text-[9px] uppercase tracking-[0.2em] text-[rgb(var(--muted))] mb-2">CIRCUIT BREAKERS</div>
                            <div className="border border-[rgba(var(--danger),0.2)] bg-[rgba(var(--surface),0.3)] px-5 divide-y divide-[rgba(var(--grid),0.1)]" style={{ borderRadius: '3px' }}>
                                <DangerSwitch label="API BUDGET HALT" hint="Pause when monthly API budget exceeded"
                                    checked={sentinel.data.budget_halt_enabled} onChange={v => sentinel.set({ budget_halt_enabled: v })} />
                                <DangerSwitch label="DRAWDOWN HALT" hint="Pause trading when daily loss exceeds limit"
                                    checked={sentinel.data.drawdown_suspended_enabled} onChange={v => sentinel.set({ drawdown_suspended_enabled: v })} />
                                <DangerSwitch label="BROKER DISCONNECT HALT" hint="Pause when Shioaji connection lost"
                                    checked={sentinel.data.broker_disconnected_enabled} onChange={v => sentinel.set({ broker_disconnected_enabled: v })} />
                                <SafeToggle label="REDUCE-ONLY MODE" hint="Only allow closing positions after halt"
                                    checked={sentinel.data.reduce_only_enabled} onChange={v => sentinel.set({ reduce_only_enabled: v })} />
                                <SafeToggle label="DB LATENCY HALT" hint="Alert when DB write p99 exceeds threshold"
                                    checked={sentinel.data.db_latency_enabled} onChange={v => sentinel.set({ db_latency_enabled: v })} />
                            </div>
                            <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                                onSave={() => sentinel.save(sentinel.data)} />
                        </div>
                    )}
                </div>
            </div>

            {/* ══════════════════════════════════════════════════════════
                SAFE ZONE -- Configuration
                ══════════════════════════════════════════════════════════ */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">

                {/* ── LEFT: Watchlist (5 cols) ──────────────────── */}
                <div className="lg:col-span-5 border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
                    <div className="flex items-center gap-2 border-b border-[rgba(var(--grid),0.3)] px-5 py-3">
                        <List className="h-4 w-4 text-[rgb(var(--info))]" />
                        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--text))]">WATCHLIST</span>
                    </div>
                    <div className="p-5">
                        <WatchlistSection />
                    </div>
                </div>

                {/* ── RIGHT: System Parameters (7 cols) ─────── */}
                <div className="lg:col-span-7 space-y-4">

                    {/* Capital Limits -- key:value pairs */}
                    {capital.data && (
                        <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
                            <div className="flex items-center gap-2 border-b border-[rgba(var(--grid),0.3)] px-5 py-3">
                                <DollarSign className="h-4 w-4 text-[rgb(var(--up))]" />
                                <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--text))]">CAPITAL LIMITS</span>
                            </div>
                            <div className="px-5 py-3 divide-y divide-[rgba(var(--grid),0.08)]">
                                <InlineField label="TOTAL CAPITAL" prefix="TWD" value={capital.data.total_capital_twd} step={50000}
                                    onChange={v => capital.set({ total_capital_twd: v })} />
                                <InlineField label="MAX SINGLE POSITION" prefix="TWD" step={10000}
                                    value={Math.round(capital.data.total_capital_twd * capital.data.max_single_position_pct)}
                                    onChange={v => { if (capital.data.total_capital_twd > 0) capital.set({ max_single_position_pct: v / capital.data.total_capital_twd }) }} />
                                <InlineField label="MONTHLY API BUDGET" prefix="TWD" value={capital.data.monthly_api_budget_twd} step={500}
                                    onChange={v => capital.set({ monthly_api_budget_twd: v })} />
                                <InlinePctField label="DEFAULT STOP LOSS" value={capital.data.default_stop_loss_pct}
                                    onChange={v => capital.set({ default_stop_loss_pct: v })} />
                                <InlinePctField label="DEFAULT TAKE PROFIT" value={capital.data.default_take_profit_pct}
                                    onChange={v => capital.set({ default_take_profit_pct: v })} />
                                <InlineField label="DAILY LOSS BREAKER" prefix="TWD" value={capital.data.daily_loss_limit_twd} step={1000}
                                    onChange={v => capital.set({ daily_loss_limit_twd: v })} />
                                <InlineField label="MONTHLY LOSS BREAKER" prefix="TWD" value={capital.data.monthly_loss_limit_twd} step={5000}
                                    onChange={v => capital.set({ monthly_loss_limit_twd: v })} />
                            </div>
                            <div className="px-5 pb-4">
                                <SaveBar saving={capital.saving} saved={capital.saved} dirty={capital.dirty}
                                    onSave={() => capital.save(capital.data)} />
                            </div>
                        </div>
                    )}

                    {/* Position Limits */}
                    {limits.data && (
                        <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
                            <div className="flex items-center gap-2 border-b border-[rgba(var(--grid),0.3)] px-5 py-3">
                                <Layers className="h-4 w-4 text-[rgb(var(--info))]" />
                                <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--text))]">POSITION LIMITS</span>
                            </div>
                            <div className="px-5 py-3 space-y-3">
                                <div className="font-mono text-[10px] text-[rgb(var(--muted))]">HIGHER LEVEL = MORE AUTHORITY. L0 = NO TRADING. L3 = MAX AUTOMATION.</div>
                                {[1, 2, 3].map(lv => (
                                    <div key={lv} className="border border-[rgba(var(--grid),0.15)] bg-[rgba(var(--surface),0.2)] px-4 py-3" style={{ borderRadius: '2px' }}>
                                        <div className="font-mono text-[9px] font-bold uppercase tracking-widest text-[rgb(var(--muted))] mb-2">LEVEL {lv}</div>
                                        <div className="grid grid-cols-2 gap-4">
                                            <InlinePctField label="MAX RISK (% NAV)" value={limits.data[`level_${lv}_max_risk_pct`]}
                                                onChange={v => limits.set({ [`level_${lv}_max_risk_pct`]: v })} />
                                            <InlinePctField label="MAX POSITION (% NAV)" value={limits.data[`level_${lv}_max_position_pct`]}
                                                onChange={v => limits.set({ [`level_${lv}_max_position_pct`]: v })} />
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="px-5 pb-4">
                                <SaveBar saving={limits.saving} saved={limits.saved} dirty={limits.dirty}
                                    onSave={() => limits.save(limits.data)} />
                            </div>
                        </div>
                    )}

                    {/* Sentinel Thresholds + Telegram */}
                    {sentinel.data && (
                        <div className="border border-[rgba(var(--grid),0.3)] bg-[rgba(var(--surface),0.4)]" style={{ borderRadius: '4px' }}>
                            <div className="flex items-center gap-2 border-b border-[rgba(var(--grid),0.3)] px-5 py-3">
                                <Shield className="h-4 w-4 text-[rgb(var(--warn))]" />
                                <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-[rgb(var(--text))]">SYSTEM PARAMETERS</span>
                            </div>
                            <div className="px-5 py-3 divide-y divide-[rgba(var(--grid),0.08)]">
                                <InlineField label="DB LATENCY THRESHOLD" suffix="ms" value={sentinel.data.max_db_write_p99_ms} step={50} min={50}
                                    onChange={v => sentinel.set({ max_db_write_p99_ms: v })} />
                                <InlineField label="HEALTH CHECK INTERVAL" suffix="s" value={sentinel.data.health_check_interval_seconds} step={5} min={5}
                                    onChange={v => sentinel.set({ health_check_interval_seconds: v })} />
                                <InlineField label="TELEGRAM CHAT ID" type="text" value={sentinel.data.telegram_chat_id || ''} hint="Channel or group ID"
                                    onChange={v => sentinel.set({ telegram_chat_id: v })} />
                            </div>
                            <div className="px-5 pb-4">
                                <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                                    onSave={() => sentinel.save(sentinel.data)} />
                            </div>
                        </div>
                    )}

                    {/* Version info footer */}
                    <div className="flex items-center justify-between font-mono text-[9px] text-[rgb(var(--muted))] px-1 pt-2">
                        <span>SETTINGS TAKE EFFECT IMMEDIATELY -- NO RESTART REQUIRED</span>
                        <span>AI TRADER CONTROL PANEL</span>
                    </div>
                </div>
            </div>
        </div>
    )
}
