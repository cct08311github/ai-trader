import React, { useEffect, useState } from 'react'
import { ShieldCheck, ShieldOff, ShieldAlert, RefreshCw } from 'lucide-react'
import { fetchPmStatus, pmApprove, pmReject } from '../lib/pmApi'

/**
 * PmStatusCard — 每日 PM 審核狀態卡片
 *
 * 顯示今日 PM 是否授權交易，並提供人工覆蓋按鈕。
 * 放置在 Dashboard 頂部，讓操作者每日開盤前確認狀態。
 */
export default function PmStatusCard() {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [error, setError] = useState(null)

  async function refresh() {
    setLoading(true)
    const data = await fetchPmStatus()
    setState(data)
    setLoading(false)
  }

  useEffect(() => { refresh() }, [])

  async function handleApprove() {
    setActing(true); setError(null)
    try { setState(await pmApprove()) } catch (e) { setError(e.message) }
    setActing(false)
  }

  async function handleReject() {
    setActing(true); setError(null)
    try { setState(await pmReject()) } catch (e) { setError(e.message) }
    setActing(false)
  }

  const isToday = state?.is_today
  const approved = isToday && state?.approved
  const rejected = isToday && !state?.approved && state?.source !== 'none'
  const pending = !isToday || state?.source === 'none' || state?.source === 'pending'

  const statusConfig = approved
    ? { icon: ShieldCheck, label: '今日交易已授權', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', iconColor: 'text-emerald-400' }
    : rejected
      ? { icon: ShieldOff, label: '今日交易已封鎖', bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400', iconColor: 'text-rose-400' }
      : { icon: ShieldAlert, label: '尚未執行今日 PM 審核', bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', iconColor: 'text-amber-400' }

  const { icon: Icon, label, bg, border, text, iconColor } = statusConfig

  if (loading) {
    return (
      <div className={`rounded-2xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))/0.25] px-4 py-3 animate-pulse`}>
        <div className="h-4 w-40 rounded bg-slate-700/50" />
      </div>
    )
  }

  return (
    <div className={`rounded-2xl border ${border} ${bg} px-4 py-3`}>
      <div className="flex items-center justify-between flex-wrap gap-3">
        {/* Status */}
        <div className="flex items-center gap-3">
          <Icon className={`h-5 w-5 flex-shrink-0 ${iconColor}`} />
          <div>
            <div className={`text-sm font-semibold ${text}`}>{label}</div>
            {state?.reason && (
              <div className="mt-0.5 text-xs text-slate-400 max-w-sm truncate">{state.reason}</div>
            )}
            {state?.date && (
              <div className="mt-0.5 text-xs text-slate-500">
                {state.date}
                {state.source && state.source !== 'none' && ` · ${state.source === 'manual' ? '人工覆蓋' : state.source === 'llm' ? 'LLM 審核' : '待審核'}`}
                {state.confidence > 0 && ` · 信心 ${(state.confidence * 100).toFixed(0)}%`}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={handleApprove}
            disabled={acting || approved}
            className="rounded-lg bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-400 ring-1 ring-emerald-500/30 transition hover:bg-emerald-500/25 disabled:opacity-40"
          >
            {acting ? '…' : '授權今日'}
          </button>
          <button
            onClick={handleReject}
            disabled={acting || (rejected && !approved)}
            className="rounded-lg bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-400 ring-1 ring-rose-500/20 transition hover:bg-rose-500/20 disabled:opacity-40"
          >
            {acting ? '…' : '封鎖今日'}
          </button>
          <button
            onClick={refresh}
            disabled={loading}
            className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-200"
            title="重新整理"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-2 text-xs text-rose-300">{error}</div>
      )}

      {/* Confidence breakdown — shown when LLM reviewed */}
      {state?.source === 'llm' && state.bull_case && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3 border-t border-white/5 pt-3">
          {[
            { label: '多方', value: state.bull_case, color: 'text-emerald-400' },
            { label: '空方', value: state.bear_case, color: 'text-rose-400' },
            { label: '中立', value: state.neutral_case, color: 'text-slate-400' },
          ].map(({ label: l, value, color }) => value ? (
            <div key={l}>
              <div className={`text-xs font-medium ${color}`}>{l}</div>
              <div className="mt-0.5 text-xs text-slate-500 line-clamp-2">{value}</div>
            </div>
          ) : null)}
        </div>
      )}
    </div>
  )
}
