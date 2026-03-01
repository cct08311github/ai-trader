import React, { useEffect, useMemo, useState, Fragment } from 'react'
import { useStreamApiBase, useStrategyData } from '../lib/strategyApi'

function formatUnixSec(sec) {
  const n = Number(sec)
  if (!Number.isFinite(n) || n <= 0) return ''
  return new Date(n * 1000).toLocaleString('zh-TW', { hour12: false })
}

function safeJsonParse(s) {
  try {
    return JSON.parse(s)
  } catch {
    return null
  }
}

function StatusTag({ status }) {
  const s = String(status || '').toLowerCase() || 'unknown'
  const map = {
    pending: 'bg-slate-800 text-slate-200 border-slate-700',
    approved: 'bg-emerald-900/30 text-emerald-200 border-emerald-800',
    rejected: 'bg-rose-900/30 text-rose-200 border-rose-800',
    executed: 'bg-indigo-900/30 text-indigo-200 border-indigo-800',
    unknown: 'bg-slate-900/30 text-slate-300 border-slate-800'
  }
  const cls = map[s] || map.unknown
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{s}</span>
}

function RatingCard({ rating, basis }) {
  const r = String(rating || '').toUpperCase()
  const theme = {
    A: { bg: 'bg-emerald-900/20', border: 'border-emerald-700', text: 'text-emerald-200', sub: 'text-emerald-200/80' },
    B: { bg: 'bg-amber-900/15', border: 'border-amber-700', text: 'text-amber-200', sub: 'text-amber-200/80' },
    C: { bg: 'bg-rose-900/15', border: 'border-rose-700', text: 'text-rose-200', sub: 'text-rose-200/80' }
  }[r] || { bg: 'bg-slate-950/20', border: 'border-slate-800', text: 'text-slate-200', sub: 'text-slate-400' }

  return (
    <div className={`rounded-2xl border ${theme.border} ${theme.bg} p-6 shadow-panel`}>
      <div className="text-sm font-semibold"></div>
      <div className="mt-4 flex items-end justify-between gap-4">
        <div className={`text-6xl font-black tracking-tight ${theme.text}`}>{r || '-'}</div>
        <div className="text-right text-[11px] text-slate-500">llm_tracesPM / </div>
      </div>
      <div className={`mt-4 whitespace-pre-wrap break-words text-xs leading-relaxed ${theme.sub}`}>{basis || '()'}</div>
    </div>
  )
}

function JsonBox({ value }) {
  const text = useMemo(() => {
    if (value == null) return ''
    if (typeof value === 'string') {
      const j = safeJsonParse(value)
      if (j) return JSON.stringify(j, null, 2)
      return value
    }
    return JSON.stringify(value, null, 2)
  }, [value])

  if (!text) return <div className="text-xs text-slate-500">()</div>

  return (
    <pre className="max-h-[55vh] overflow-auto rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-200">
      {text}
    </pre>
  )
}

function ProposalModal({ open, onClose, proposal, onApprove, onReject, busy }) {
  const payload = safeJsonParse(proposal?.proposal_json || '')

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div className="w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-panel" onMouseDown={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold"></div>
            <div className="mt-1 text-xs text-slate-400">
              ID: <code className="text-slate-200">{proposal?.proposal_id || '-'}</code>
              <span className="mx-2"></span>
              {formatUnixSec(proposal?.created_at) || '-'}
              <span className="mx-2"></span>
              <StatusTag status={proposal?.status} />
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-700">
            
          </button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200"></div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/20 p-3 text-xs text-slate-300">
              <div className="grid grid-cols-3 gap-2">
                <div className="text-slate-500">generated_by</div>
                <div className="col-span-2 break-words">{proposal?.generated_by || '-'}</div>
                <div className="text-slate-500">target_rule</div>
                <div className="col-span-2 break-words">{proposal?.target_rule || '-'}</div>
                <div className="text-slate-500">rule_category</div>
                <div className="col-span-2 break-words">{proposal?.rule_category || '-'}</div>
                <div className="text-slate-500">confidence</div>
                <div className="col-span-2 break-words">{proposal?.confidence ?? '-'}</div>
                <div className="text-slate-500">decided_at</div>
                <div className="col-span-2 break-words">{formatUnixSec(proposal?.decided_at) || '-'}</div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                disabled={busy || String(proposal?.status || '').toLowerCase() !== 'pending'}
                onClick={onApprove}
                className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 hover:bg-emerald-500"
              >
                 (Approve)
              </button>
              <button
                disabled={busy || String(proposal?.status || '').toLowerCase() !== 'pending'}
                onClick={onReject}
                className="rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 hover:bg-rose-500"
              >
                 (Reject)
              </button>
              <div className="text-[11px] text-slate-500"> pending </div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200">proposal_json /  / </div>
            <JsonBox value={payload || proposal?.proposal_json} />
          </div>
        </div>
      </div>
    </div>
  )
}

function SemanticMemoryTable({ data, order }) {
  if (!data || data.length === 0) return <div className="text-xs text-slate-500"></div>
  return (
    <div className="overflow-auto rounded-xl border border-slate-800">
      <table className="w-full text-left text-[11px]">
        <thead className="bg-slate-950/40 text-slate-400">
          <tr>
            <th className="px-3 py-2"></th>
            <th className="px-3 py-2">Rule ID</th>
            <th className="px-3 py-2"></th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {data.map((m, idx) => (
            <tr key={m.rule_id || idx} className="hover:bg-slate-950/30">
              <td className="px-3 py-2 text-slate-300">{(m.confidence * 100).toFixed(0)}%</td>
              <td className="px-3 py-2 text-slate-200 font-mono">{m.rule_id}</td>
              <td className="px-3 py-2 text-slate-400 break-words">{m.content_summary || m.content?.slice(0, 100)}</td>
              <td className="px-3 py-2 text-slate-500">{formatUnixSec(m.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function StrategyPage() {
  const { proposals, logs, marketRating, semanticMemory, debates, error, loading, opsToken, saveOpsToken, act, refreshProposals, refreshSemanticMemory } = useStrategyData({ pollMs: 10000 })
  const STREAM_BASE = useStreamApiBase()

  const [selected, setSelected] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)

  const [memOrder, setMemOrder] = useState('desc')

  // SSE integration: when new llm_traces logs arrive, refresh proposals (debounced).
  useEffect(() => {
    const url = `${STREAM_BASE}/logs`
    const es = new EventSource(url)

    let t = null
    const scheduleRefresh = () => {
      if (t) clearTimeout(t)
      t = setTimeout(() => {
        refreshProposals()
      }, 500)
    }

    es.addEventListener('log', scheduleRefresh)
    es.addEventListener('error', () => {
      // ignore; browser will reconnect
    })

    return () => {
      if (t) clearTimeout(t)
      es.close()
    }
  }, [STREAM_BASE, refreshProposals])

  useEffect(() => {
    if (refreshSemanticMemory) {
      refreshSemanticMemory({ sort: 'confidence', order: memOrder, limit: 50 })
    }
  }, [memOrder, refreshSemanticMemory])

  const rows = useMemo(() => {
    return (proposals || []).map(p => {
      const payload = safeJsonParse(p?.proposal_json || '') || {}
      const symbol = payload?.symbol || payload?.ticker || payload?.stock || payload?.contract || ''
      const side = payload?.side || payload?.direction || payload?.action || ''
      return {
        ...p,
        _symbol: symbol || '-',
        _side: side || '-',
        _ts: formatUnixSec(p?.created_at) || '-'
      }
    })
  }, [proposals])

  const openDetail = p => {
    setSelected(p)
    setModalOpen(true)
  }

  const closeDetail = () => {
    setModalOpen(false)
  }

  const doApprove = async p => {
    if (!p?.proposal_id) return
    const ok = window.confirm(` proposal ${p.proposal_id}`)
    if (!ok) return
    await act('approve', p.proposal_id, { actor: 'operator', reason: 'manual approve via UI' })
    setModalOpen(false)
  }

  const doReject = async p => {
    if (!p?.proposal_id) return
    const ok = window.confirm(` proposal ${p.proposal_id}`)
    if (!ok) return
    await act('reject', p.proposal_id, { actor: 'operator', reason: 'manual reject via UI' })
    setModalOpen(false)
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-semibold"></div>
            <div className="mt-1 text-xs text-slate-400">pending/approved/rejected/executed+ proposal_json+ SSE </div>
          </div>

          <div className="flex flex-col items-start gap-2">
            <div className="text-[11px] text-slate-500"> STRATEGY_OPS_TOKEN X-OPS-TOKEN  approve/reject</div>
            <div className="flex items-center gap-2">
              <input
                value={opsToken}
                onChange={e => saveOpsToken(e.target.value)}
                placeholder=" ops token localStorage"
                className="w-72 max-w-full rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-500"
              />
              <button
                onClick={() => saveOpsToken('')}
                className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-700"
              >
                
              </button>
            </div>
          </div>
        </div>

        {error && <div className="mt-4 rounded-lg border border-rose-800 bg-rose-900/20 p-3 text-xs text-rose-300">{error}</div>}

        <div className="mt-5 overflow-auto rounded-xl border border-slate-800">
          <table className="min-w-[980px] w-full text-left text-xs">
            <thead className="bg-slate-950/40 text-slate-400">
              <tr>
                <th className="px-4 py-3"></th>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3"></th>
                <th className="px-4 py-3"></th>
                <th className="px-4 py-3"></th>
                <th className="px-4 py-3"></th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-5 text-slate-500" colSpan={7}>
                    {loading.proposals ? '...' : ''}
                  </td>
                </tr>
              ) : (
                rows.map(p => {
                  const status = String(p?.status || '').toLowerCase()
                  const canAct = status === 'pending'
                  return (
                    <tr key={p.proposal_id} className="hover:bg-slate-950/30">
                      <td className="px-4 py-3 text-slate-300 whitespace-nowrap">{p._ts}</td>
                      <td className="px-4 py-3">
                        <button onClick={() => openDetail(p)} className="text-slate-200 hover:text-white underline underline-offset-2">
                          {p.proposal_id}
                        </button>
                      </td>
                      <td className="px-4 py-3 text-slate-300">{p._symbol}</td>
                      <td className="px-4 py-3 text-slate-300">{p._side}</td>
                      <td className="px-4 py-3 text-slate-300">{p.confidence ?? '-'}</td>
                      <td className="px-4 py-3">
                        <StatusTag status={p.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            disabled={!canAct || loading.act}
                            onClick={() => doApprove(p)}
                            className="rounded-lg bg-emerald-700 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-40 hover:bg-emerald-600"
                          >
                            Approve
                          </button>
                          <button
                            disabled={!canAct || loading.act}
                            onClick={() => doReject(p)}
                            className="rounded-lg bg-rose-700 px-2.5 py-1.5 text-[11px] font-semibold text-white disabled:opacity-40 hover:bg-rose-600"
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-3 text-[11px] text-slate-500"> ID  proposal_jsonSSE llm_traces</div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <RatingCard rating={marketRating?.rating} basis={marketRating?.basis} />

        <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel lg:col-span-2">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">semantic_memory</div>
              <div className="mt-1 text-xs text-slate-400"> source episodes confidence </div>
            </div>
            <button
              onClick={() => setMemOrder(o => (o === 'desc' ? 'asc' : 'desc'))}
              className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 transition-colors"
            >
              {memOrder === "desc" ? " " : " "}
            </button>
          </div>
          <div className="mt-4">
            <SemanticMemoryTable data={semanticMemory} order={memOrder} />
          </div>
        </div>
      </div>

      <ProposalModal
        open={modalOpen}
        onClose={closeDetail}
        proposal={selected}
        busy={loading.act}
        onApprove={() => doApprove(selected)}
        onReject={() => doReject(selected)}
      />
    </div>
  )
}
