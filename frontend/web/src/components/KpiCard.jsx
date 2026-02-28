import React from 'react'

export default function KpiCard({ title, value, subtext, tone = 'neutral' }) {
  const toneClass =
    tone === 'good'
      ? 'text-emerald-300'
      : tone === 'bad'
        ? 'text-rose-300'
        : 'text-slate-100'

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/30 p-4 shadow-panel">
      <div className="text-xs uppercase tracking-widest text-slate-400">{title}</div>
      <div className={`mt-2 text-2xl font-semibold ${toneClass}`}>{value}</div>
      {subtext ? <div className="mt-2 text-xs text-slate-400">{subtext}</div> : null}
    </div>
  )
}
