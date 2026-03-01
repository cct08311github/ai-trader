import React, { useCallback, useEffect, useState } from 'react'
import {
    DollarSign, Shield, TrendingDown, CheckCircle, AlertCircle,
    Save, RefreshCw, Lock, Bell, Layers, ChevronDown, ChevronUp
} from 'lucide-react'
import { formatComma } from '../lib/format'

/* ── API base ─────────────────────────────────────────────── */
// Empty string = same origin → Vite proxy routes /api/* to 127.0.0.1:8080 locally
const API = (import.meta?.env?.VITE_API_BASE || '').replace(/\/$/, '')

async function apiFetch(path, opts = {}) {
    const res = await fetch(`${API}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
    })
    if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
    }
    return res.json()
}

/* ── Shared UI pieces ─────────────────────────────────────── */
function Section({ title, icon: Icon, color = 'text-emerald-400', children, defaultOpen = true }) {
    const [open, setOpen] = useState(defaultOpen)
    return (
        <div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen(o => !o)}
                className={`w-full flex items-center justify-between px-6 py-4 text-sm font-semibold ${color} hover:bg-slate-800/30 transition-colors`}
            >
                <span className="flex items-center gap-2"><Icon className="h-4 w-4" />{title}</span>
                {open ? <ChevronUp className="h-4 w-4 opacity-50" /> : <ChevronDown className="h-4 w-4 opacity-50" />}
            </button>
            {open && <div className="px-6 pb-6 space-y-4 border-t border-slate-800/60">{children}</div>}
        </div>
    )
}

function Field({ label, hint, value, onChange, prefix, suffix, type = 'number', min, max, step = 1 }) {
    return (
        <div className="flex flex-col gap-1">
            <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider pt-4">{label}</label>
            {hint && <p className="text-xs text-slate-500 mb-1">{hint}</p>}
            <div className="flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 focus-within:border-emerald-500/40 focus-within:ring-1 focus-within:ring-emerald-500/20 transition-all">
                {prefix && <span className="text-sm text-slate-400 shrink-0">{prefix}</span>}
                <input
                    type={type}
                    min={min} max={max} step={step}
                    value={value}
                    onChange={e => onChange(type === 'number' ? Number(e.target.value) : e.target.value)}
                    className="flex-1 bg-transparent text-sm text-slate-100 outline-none"
                />
                {suffix && <span className="text-sm text-slate-400 shrink-0">{suffix}</span>}
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

function Toggle({ label, hint, checked, onChange }) {
    return (
        <div className="flex items-start justify-between gap-4 pt-4">
            <div>
                <div className="text-sm text-slate-200">{label}</div>
                {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
            </div>
            <button
                type="button"
                role="switch"
                aria-checked={checked}
                onClick={() => onChange(!checked)}
                className={`relative shrink-0 h-6 w-11 rounded-full transition-colors ${checked ? 'bg-emerald-500' : 'bg-slate-700'}`}
            >
                <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
            </button>
        </div>
    )
}

function SaveBar({ saving, saved, dirty, onSave }) {
    return (
        <div className="flex items-center gap-3 pt-2">
            <button
                type="button"
                onClick={onSave}
                disabled={saving || !dirty}
                className="flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
                {saving ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? '儲存中...' : '儲存'}
            </button>
            {dirty && <span className="text-xs text-amber-400">● 有未儲存的變更</span>}
            {saved && <span className="text-xs text-emerald-400 flex items-center gap-1"><CheckCircle className="h-3 w-3" />已儲存並生效</span>}
        </div>
    )
}

/* ── Hooks ────────────────────────────────────────────────── */
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
        setDirty(true)
        setSaved(false)
    }, [])

    const save = useCallback(async (payload) => {
        setSaving(true)
        try {
            const updated = await apiFetch(path, { method: 'PUT', body: JSON.stringify(payload) })
            setData(updated)
            setDirty(false)
            setSaved(true)
            setTimeout(() => setSaved(false), 4000)
        } catch (e) { setError(e.message) }
        finally { setSaving(false) }
    }, [path])

    return { data, error, saving, saved, dirty, set, save, refresh: load }
}

/* ── Page ─────────────────────────────────────────────────── */
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
            auth.refresh()
        } catch (e) { setAuthError(e.message) }
        finally { setAuthSaving(false) }
    }

    const loading = !capital.data && !sentinel.data && !limits.data

    return (
        <div className="space-y-6 max-w-2xl">
            <div>
                <h1 className="text-2xl font-bold text-slate-100 tracking-tight">系統維護設定</h1>
                <p className="mt-1 text-sm text-slate-400">所有設定儲存後即時生效，不需重啟服務。</p>
            </div>

            {errors.map((e, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                    <AlertCircle className="h-4 w-4 shrink-0" />{e}
                </div>
            ))}

            {loading && (
                <div className="flex items-center gap-3 text-sm text-slate-400 py-8">
                    <RefreshCw className="h-4 w-4 animate-spin" />載入中...
                </div>
            )}

            {/* 1. Capital */}
            {capital.data && (
                <Section title="可操作資金" icon={DollarSign} color="text-emerald-400">
                    <Field label="總可操作資金" hint="AI 系統可動用的資金上限，所有比例限制均以此為基準"
                        prefix="TWD" value={capital.data.total_capital_twd} step={50000}
                        onChange={v => capital.set({ total_capital_twd: v })} />
                    <PctField label="單一持倉上限"
                        hint={`換算金額：TWD ${formatComma(Math.round(capital.data.total_capital_twd * capital.data.max_single_position_pct))}`}
                        value={capital.data.max_single_position_pct}
                        onChange={v => capital.set({ max_single_position_pct: v })} />
                    <Field label="每日虧損熔斷" hint="超過此金額系統切換防禦模式"
                        prefix="TWD" value={capital.data.daily_loss_limit_twd} step={1000}
                        onChange={v => capital.set({ daily_loss_limit_twd: v })} />
                    <Field label="每月虧損熔斷" hint="超過此金額觸發月度熔斷，需手動解除"
                        prefix="TWD" value={capital.data.monthly_loss_limit_twd} step={5000}
                        onChange={v => capital.set({ monthly_loss_limit_twd: v })} />
                    <SaveBar saving={capital.saving} saved={capital.saved} dirty={capital.dirty}
                        onSave={() => capital.save(capital.data)} />
                </Section>
            )}

            {/* 2. Position Limits */}
            {limits.data && (
                <Section title="倉位授權層級（Position Limits）" icon={Layers} color="text-sky-400" defaultOpen={false}>
                    <p className="text-xs text-slate-500 pt-4">
                        Level 越高代表交易授權越大。Level 0 = 禁止交易；Level 3 = 最高自動化授權。
                    </p>
                    {[1, 2, 3].map(lv => (
                        <div key={lv} className="rounded-xl border border-slate-800/60 bg-slate-950/30 px-4 py-3 space-y-2">
                            <div className="text-xs font-semibold text-slate-300 uppercase tracking-wider">Level {lv}</div>
                            <div className="grid grid-cols-2 gap-3">
                                <PctField label="單筆風險上限（% NAV）"
                                    value={limits.data[`level_${lv}_max_risk_pct`]}
                                    onChange={v => limits.set({ [`level_${lv}_max_risk_pct`]: v })} />
                                <PctField label="持倉名義上限（% NAV）"
                                    value={limits.data[`level_${lv}_max_position_pct`]}
                                    onChange={v => limits.set({ [`level_${lv}_max_position_pct`]: v })} />
                            </div>
                        </div>
                    ))}
                    <SaveBar saving={limits.saving} saved={limits.saved} dirty={limits.dirty}
                        onSave={() => limits.save(limits.data)} />
                </Section>
            )}

            {/* 3. Sentinel */}
            {sentinel.data && (
                <Section title="Sentinel 熔斷開關" icon={Shield} color="text-orange-400" defaultOpen={false}>
                    <Toggle label="API 預算熔斷" hint="超過月度 API 預算後暫停"
                        checked={sentinel.data.budget_halt_enabled}
                        onChange={v => sentinel.set({ budget_halt_enabled: v })} />
                    <Toggle label="回撤熔斷" hint="日虧損超過上限後暫停交易"
                        checked={sentinel.data.drawdown_suspended_enabled}
                        onChange={v => sentinel.set({ drawdown_suspended_enabled: v })} />
                    <Toggle label="只減倉模式" hint="熔斷後僅允許平倉，不允許開新倉"
                        checked={sentinel.data.reduce_only_enabled}
                        onChange={v => sentinel.set({ reduce_only_enabled: v })} />
                    <Toggle label="券商斷線熔斷" hint="Shioaji 連線中斷後暫停"
                        checked={sentinel.data.broker_disconnected_enabled}
                        onChange={v => sentinel.set({ broker_disconnected_enabled: v })} />
                    <Toggle label="DB 延遲熔斷" hint="資料庫寫入 p99 超過門檻後告警"
                        checked={sentinel.data.db_latency_enabled}
                        onChange={v => sentinel.set({ db_latency_enabled: v })} />
                    <Field label="DB 延遲門檻（ms）"
                        value={sentinel.data.max_db_write_p99_ms} step={50} min={50}
                        onChange={v => sentinel.set({ max_db_write_p99_ms: v })} />
                    <Field label="健康檢查間隔（秒）"
                        value={sentinel.data.health_check_interval_seconds} step={5} min={5}
                        onChange={v => sentinel.set({ health_check_interval_seconds: v })} />
                    <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                        onSave={() => sentinel.save(sentinel.data)} />
                </Section>
            )}

            {/* 4. Telegram */}
            {sentinel.data && (
                <Section title="Telegram 通知" icon={Bell} color="text-blue-400" defaultOpen={false}>
                    <Field label="Telegram Chat ID" hint="填入您的頻道或群組 ID（例如：-1003772422881）"
                        type="text" value={sentinel.data.telegram_chat_id || ''}
                        onChange={v => sentinel.set({ telegram_chat_id: v })} />
                    <SaveBar saving={sentinel.saving} saved={sentinel.saved} dirty={sentinel.dirty}
                        onSave={() => sentinel.save(sentinel.data)} />
                </Section>
            )}

            {/* 5. Authority Level */}
            <Section title="交易授權層級" icon={Lock} color="text-red-400" defaultOpen={false}>
                {auth.data && (
                    <div className="rounded-xl border border-slate-800/60 bg-slate-950/30 px-4 py-3 text-sm space-y-1 mt-4">
                        <div className="flex justify-between">
                            <span className="text-slate-400">目前層級</span>
                            <span className="font-semibold text-slate-100">Level {auth.data.level}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">原因</span>
                            <span className="text-slate-300">{auth.data.reason}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-slate-400">生效時間</span>
                            <span className="text-slate-400 text-xs">{auth.data.effective_from?.replace('T', ' ').slice(0, 19)}</span>
                        </div>
                    </div>
                )}
                <div className="space-y-3">
                    <div className="flex flex-col gap-1 pt-4">
                        <label className="text-xs font-semibold text-slate-300 uppercase tracking-wider">新層級</label>
                        <select
                            value={authorityInput.level}
                            onChange={e => setAuthorityInput(p => ({ ...p, level: Number(e.target.value) }))}
                            className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500/40"
                        >
                            <option value={0}>Level 0 — 禁止交易</option>
                            <option value={1}>Level 1 — 極保守（1% NAV）</option>
                            <option value={2}>Level 2 — 保守（5% NAV）</option>
                            <option value={3}>Level 3 — 標準（10% NAV）</option>
                        </select>
                    </div>
                    <Field label="變更原因（必填）" type="text"
                        value={authorityInput.reason}
                        onChange={v => setAuthorityInput(p => ({ ...p, reason: v }))} />
                </div>
                {authError && <div className="text-xs text-red-400">{authError}</div>}
                <SaveBar saving={authSaving} saved={authSaved} dirty={!!authorityInput.reason}
                    onSave={saveAuthority} />
            </Section>
        </div>
    )
}
