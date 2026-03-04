import React, { useCallback, useEffect, useState } from 'react'
import {
    DollarSign, Shield, TrendingDown, CheckCircle, AlertCircle,
    Save, RefreshCw, Lock, Bell, Layers, ChevronDown, ChevronUp,
    List, Plus, X, Zap
} from 'lucide-react'
import { formatComma } from '../lib/format'
import { authFetch, getApiBase } from '../lib/auth'

/* ── API base ───────────────────────────────────────────────── */
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

/* ── Watchlist Section ────────────────────────────────────── */
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
            setData(await res.json())
            setError(null)
        } catch (e) { setError(e.message) }
    }, [])

    useEffect(() => { load() }, [load])

    function addSymbol() {
        const sym = newSymbol.trim().toUpperCase()
        if (!sym) return
        if (!/^\d{4}$/.test(sym) && !/^[A-Z]{1,5}$/.test(sym)) {
            setAddError('格式不正確（台股4位數字或美股英文代碼）')
            return
        }
        if (data.universe.includes(sym)) {
            setAddError(`${sym} 已在清單中`)
            return
        }
        setData(d => ({ ...d, universe: [...d.universe, sym] }))
        setNewSymbol('')
        setAddError('')
        setDirty(true)
        setSaved(false)
    }

    function removeSymbol(sym) {
        setData(d => ({ ...d, universe: d.universe.filter(s => s !== sym) }))
        setDirty(true)
        setSaved(false)
    }

    async function save() {
        setSaving(true)
        try {
            const res = await authFetch(`${getApiBase()}/api/settings/watchlist`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ universe: data.universe, max_active: data.max_active }),
            })
            if (!res.ok) {
                const b = await res.json().catch(() => ({}))
                throw new Error(b.detail || `HTTP ${res.status}`)
            }
            const updated = await res.json()
            setData(updated)
            setDirty(false)
            setSaved(true)
            setTimeout(() => setSaved(false), 4000)
        } catch (e) { setError(e.message) }
        finally { setSaving(false) }
    }

    return (
        <Section title="選股候選池 (Watchlist)" icon={List} color="text-violet-400" defaultOpen={true}>
            {error && (
                <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300 mt-4">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />{error}
                </div>
            )}
            {!data ? (
                <div className="flex items-center gap-2 text-xs text-slate-400 py-4">
                    <RefreshCw className="h-3.5 w-3.5 animate-spin" />載入中...
                </div>
            ) : (
                <>
                    {/* Active watchlist — read-only */}
                    <div className="pt-4">
                        <div className="flex items-center gap-2 mb-2">
                            <Zap className="h-3.5 w-3.5 text-amber-400" />
                            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                                系統主動篩選（Active Watchlist）
                            </span>
                            <button onClick={load} className="ml-auto text-slate-500 hover:text-slate-300 transition-colors">
                                <RefreshCw className="h-3 w-3" />
                            </button>
                        </div>
                        <p className="text-xs text-slate-500 mb-2">
                            每3分鐘從候選池中依漲跌幅排名自動更新，最多取前 {data.max_active} 支。
                            {data.screened_at && <span className="ml-1 text-slate-600">最後篩選：{data.screened_at}</span>}
                        </p>
                        <div className="flex flex-wrap gap-2 min-h-[2rem]">
                            {data.active_watchlist && data.active_watchlist.length > 0 ? (
                                data.active_watchlist.map(sym => (
                                    <span key={sym} className="flex items-center gap-1 rounded-lg bg-amber-500/10 border border-amber-500/30 px-2.5 py-1 text-xs font-mono font-semibold text-amber-300">
                                        <Zap className="h-3 w-3" />{sym}
                                    </span>
                                ))
                            ) : (
                                <span className="text-xs text-slate-500 italic">尚無篩選結果（watcher 執行後自動更新）</span>
                            )}
                        </div>
                    </div>

                    <div className="my-4 border-t border-slate-800/60" />

                    {/* Universe — editable */}
                    <div>
                        <div className="flex items-center gap-2 mb-2">
                            <List className="h-3.5 w-3.5 text-violet-400" />
                            <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                                候選池（Universe）
                            </span>
                            <span className="ml-auto text-xs text-slate-500">{data.universe.length} 支</span>
                        </div>
                        <p className="text-xs text-slate-500 mb-3">手動維護的股票候選池。系統每次掃描時從此清單篩選 active watchlist。</p>
                        <div className="flex flex-wrap gap-2 mb-3">
                            {data.universe.map(sym => (
                                <span key={sym} className="flex items-center gap-1 rounded-lg bg-slate-800/60 border border-slate-700/60 px-2.5 py-1 text-xs font-mono text-slate-200">
                                    {sym}
                                    <button
                                        onClick={() => removeSymbol(sym)}
                                        className="text-slate-500 hover:text-rose-400 transition-colors ml-0.5"
                                        title={`移除 ${sym}`}
                                    >
                                        <X className="h-3 w-3" />
                                    </button>
                                </span>
                            ))}
                        </div>

                        {/* Add symbol */}
                        <div className="flex items-center gap-2">
                            <input
                                type="text"
                                placeholder="新增股票代碼（如 2330 或 AAPL）"
                                value={newSymbol}
                                onChange={e => { setNewSymbol(e.target.value); setAddError('') }}
                                onKeyDown={e => e.key === 'Enter' && addSymbol()}
                                className="flex-1 rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 outline-none focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
                            />
                            <button
                                onClick={addSymbol}
                                className="flex items-center gap-1.5 rounded-xl bg-violet-600/20 border border-violet-500/30 px-3 py-2 text-sm font-medium text-violet-300 hover:bg-violet-600/30 transition-colors"
                            >
                                <Plus className="h-4 w-4" />新增
                            </button>
                        </div>
                        {addError && <p className="text-xs text-rose-400 mt-1">{addError}</p>}
                    </div>

                    <div className="my-4 border-t border-slate-800/60" />

                    {/* max_active */}
                    <Field
                        label="Active Watchlist 最大數量"
                        hint="每次掃描最多選取幾支股票進行監控與交易訊號產生"
                        value={data.max_active}
                        min={1} max={20} step={1}
                        onChange={v => { setData(d => ({ ...d, max_active: v })); setDirty(true); setSaved(false) }}
                        suffix="支"
                    />

                    <SaveBar saving={saving} saved={saved} dirty={dirty} onSave={save} />
                </>
            )}
        </Section>
    )
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
            setAuthorityInput(p => ({ ...p, reason: '' }))
            auth.refresh()
        } catch (e) { setAuthError(e.message) }
        finally { setAuthSaving(false) }
    }

    const loading = !capital.data && !sentinel.data && !limits.data

    return (
        <div className="space-y-6 max-w-5xl">
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

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
                {/* 0. Watchlist */}
                <WatchlistSection />

                {/* 1. Capital */}
                {capital.data && (
                    <Section title="可操作資金" icon={DollarSign} color="text-emerald-400">
                        <Field label="總可操作資金" hint="AI 系統可動用的資金上限，所有比例限制均以此為基準"
                            prefix="TWD" value={capital.data.total_capital_twd} step={50000}
                            onChange={v => capital.set({ total_capital_twd: v })} />
                        <Field label="單一持倉上限"
                            hint="系統允許投入單檔持倉的最大金額上限"
                            type="number" prefix="TWD" step={10000}
                            value={Math.round(capital.data.total_capital_twd * capital.data.max_single_position_pct)}
                            onChange={v => {
                                if (capital.data.total_capital_twd > 0) {
                                    capital.set({ max_single_position_pct: v / capital.data.total_capital_twd })
                                }
                            }} />
                        <Field label="每月 API 預算" hint="達到此預算後當月停止下單 (需開啟 API 預算熔斷)"
                            prefix="TWD" value={capital.data.monthly_api_budget_twd} step={500}
                            onChange={v => capital.set({ monthly_api_budget_twd: v })} />
                        <PctField label="預設止損比例" hint="當個別標的未設定止損時使用的全域預設值"
                            value={capital.data.default_stop_loss_pct}
                            onChange={v => capital.set({ default_stop_loss_pct: v })} />
                        <PctField label="預設止盈比例" hint="當個別標的未設定止盈時使用的全域預設值"
                            value={capital.data.default_take_profit_pct}
                            onChange={v => capital.set({ default_take_profit_pct: v })} />
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
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
        </div>
    )
}
