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
      <div className="text-sm font-semibold">今日市場評級</div>
      <div className="mt-4 flex items-end justify-between gap-4">
        <div className={`text-6xl font-black tracking-tight ${theme.text}`}>{r || '-'}</div>
        <div className="text-right text-[11px] text-slate-500">資料源：llm_traces（PM / 今日最新）</div>
      </div>
      <div className={`mt-4 whitespace-pre-wrap break-words text-xs leading-relaxed ${theme.sub}`}>{basis || '(尚無評級依據)'}</div>
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

  if (!text) return <div className="text-xs text-slate-500">(無內容)</div>

  return (
    <pre className="max-h-[55vh] overflow-auto rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs text-slate-200">
      {text}
    </pre>
  )
}

function EpisodeLinks({ value }) {
  if (!value) return <div className="text-[11px] text-slate-500">(無 source episodes)</div>
  if (Array.isArray(value)) {
    return (
      <div className="space-y-1">
        {value.map((ep, idx) => {
          const o = typeof ep === 'string' ? { title: ep, url: '' } : ep || {}
          const title = o.title || o.name || o.id || `episode_${idx + 1}`
          const url = o.url || o.link || o.href || ''
          return (
            <div key={idx} className="text-xs">
              {url ? (
                <a className="text-sky-300 hover:text-sky-200 underline underline-offset-2" href={url} target="_blank" rel="noreferrer">
                  {title}
                </a>
              ) : (
                <span className="text-slate-300">{title}</span>
              )}
            </div>
          )
        })}
      </div>
    )
  }
  return <JsonBox value={value} />
}

function ProposalModal({ open, onClose, proposal, onApprove, onReject, busy }) {
  const payload = safeJsonParse(proposal?.proposal_json || '')

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div className="w-full max-w-4xl rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-panel" onMouseDown={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">策略提案詳情</div>
            <div className="mt-1 text-xs text-slate-400">
              ID: <code className="text-slate-200">{proposal?.proposal_id || '-'}</code>
              <span className="mx-2">·</span>
              {formatUnixSec(proposal?.created_at) || '-'}
              <span className="mx-2">·</span>
              <StatusTag status={proposal?.status} />
            </div>
          </div>
          <button onClick={onClose} className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 transition-colors"
            >
              {memOrder === "desc" ? "↑ 高信心優先" : "↓ 低信心優先"}
            </button>
          </div>
          <div className="mt-4">
            <SemanticMemoryTable data={semanticMemories} order={memOrder} />
          </div>
        </div>
      </div>
    </div>
  );
            關閉
          </button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200">摘要</div>
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
                批准 (Approve)
              </button>
              <button
                disabled={busy || String(proposal?.status || '').toLowerCase() !== 'pending'}
                onClick={onReject}
                className="rounded-lg bg-rose-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40 hover:bg-rose-500"
              >
                拒絕 (Reject)
              </button>
              <div className="text-[11px] text-slate-500">狀態非 pending 時，禁止操作。</div>
            </div>
          </div>

          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-200">proposal_json（決策 / 推理 / 風險評估等）</div>
            <JsonBox value={payload || proposal?.proposal_json} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default function StrategyPage() {
  const { proposals, logs, marketRating, semanticMemory, debates, error, loading, opsToken, saveOpsToken, act, refreshProposals, refreshSemanticMemory } = useStrategyData({ pollMs: 10000 })
  const STREAM_BASE = useStreamApiBase()

  const [selected, setSelected] = useState(null)
  const [modalOpen, setModalOpen] = useState(false)

  const [memOrder, setMemOrder] = useState('desc')
  const [expandedRuleId, setExpandedRuleId] = useState(null)

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
    refreshSemanticMemory({ sort: 'confidence', order: memOrder, limit: 50 })
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
    const ok = window.confirm(`確定要批准 proposal ${p.proposal_id}？`)
    if (!ok) return
    await act('approve', p.proposal_id, { actor: 'operator', reason: 'manual approve via UI' })
    setModalOpen(false)
  }

  const doReject = async p => {
    if (!p?.proposal_id) return
    const ok = window.confirm(`確定要拒絕 proposal ${p.proposal_id}？`)
    if (!ok) return
    await act('reject', p.proposal_id, { actor: 'operator', reason: 'manual reject via UI' })
    setModalOpen(false)
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="text-sm font-semibold">策略執行模組</div>
            <div className="mt-1 text-xs text-slate-400">策略提案（pending/approved/rejected/executed）+ 詳細決策內容（proposal_json）+ SSE 即時刷新。</div>
          </div>

          <div className="flex flex-col items-start gap-2">
            <div className="text-[11px] text-slate-500">操作驗證：後端需設定 STRATEGY_OPS_TOKEN；前端以 X-OPS-TOKEN 呼叫 approve/reject。</div>
            <div className="flex items-center gap-2">
              <input
                value={opsToken}
                onChange={e => saveOpsToken(e.target.value)}
                placeholder="輸入 ops token（儲存在 localStorage）"
                className="w-72 max-w-full rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-500"
              />
              <button
                onClick={() => saveOpsToken('')}
                className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 transition-colors"
            >
              {memOrder === "desc" ? "↑ 高信心優先" : "↓ 低信心優先"}
            </button>
          </div>
          <div className="mt-4">
            <SemanticMemoryTable data={semanticMemories} order={memOrder} />
          </div>
        </div>
      </div>
    </div>
  );
              >
                清除
              </button>
            </div>
          </div>
        </div>

        {error && <div className="mt-4 rounded-lg border border-rose-800 bg-rose-900/20 p-3 text-xs text-rose-300">{error}</div>}

        <div className="mt-5 overflow-auto rounded-xl border border-slate-800">
          <table className="min-w-[980px] w-full text-left text-xs">
            <thead className="bg-slate-950/40 text-slate-400">
              <tr>
                <th className="px-4 py-3">時間</th>
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">股票</th>
                <th className="px-4 py-3">方向</th>
                <th className="px-4 py-3">信心</th>
                <th className="px-4 py-3">狀態</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.length === 0 ? (
                <tr>
                  <td className="px-4 py-5 text-slate-500" colSpan={7}>
                    {loading.proposals ? '載入中...' : '目前沒有策略提案'}
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

        <div className="mt-3 text-[11px] text-slate-500">提示：點擊提案 ID 可查看 proposal_json；SSE 監聽到新決策日誌（llm_traces）會自動刷新提案列表。</div>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <RatingCard rating={marketRating?.rating} basis={marketRating?.basis} />

        <div className="rounded-2xl border border-slate-800 bg-slate-900/20 p-6 shadow-panel lg:col-span-2">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-sm font-semibold">語義記憶庫（semantic_memory）</div>
              <div className="mt-1 text-xs text-slate-400">點擊列可展開 source episodes。預設依 confidence 排序。</div>
            </div>
            <button
              onClick={() => setMemOrder(o => (o === 'desc' ? 'asc' : 'desc'))}
              className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 transition-colors"
            >
              {memOrder === "desc" ? "↑ 高信心優先" : "↓ 低信心優先"}
            </button>
          </div>
          <div className="mt-4">
            <SemanticMemoryTable data={semanticMemories} order={memOrder} />
          </div>
        </div>
      </div>
    </div>
  );
}